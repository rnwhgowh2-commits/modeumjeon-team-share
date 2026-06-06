"""다중 워커 크롤 잡 큐 — 등록(enqueue)·조회·리스 만료 회수(reaper).

설계: docs/crawl-worker-system.md
서버(스케줄러/버튼)는 여기 enqueue 만 하고, 실제 크롤은 로컬 PC 워커(Phase 2)가
원자적으로 선점·실행한다. 본 모듈은 큐의 단일 진실 원천.

원자적 선점(claim) 로직 자체는 워커 측(Phase 2)에서 FOR UPDATE SKIP LOCKED 로
구현한다 — 여기서는 등록/회수/조회만 담당한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from shared.db import SessionLocal
from lemouton.sourcing.models import CrawlJob, CrawlWorker

# ── 정책 상수 ──────────────────────────────────────────────
HEARTBEAT_ONLINE_SEC = 90      # 마지막 하트비트 이내면 온라인
LEASE_SEC = 300                # 선점 후 5분간 하트비트 없으면 잡 회수
MAX_ATTEMPTS = 3               # 회수 누적 N회 초과 시 failed 처리

# 잡이 "살아있다(이미 처리 중/대기)"고 보는 상태 — 중복 등록 판정용
LIVE_STATUSES = ("pending", "claimed", "running")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_crawl(
    model_code: Optional[str] = None,
    *,
    triggered_by: str = "manual",
    routing: str = "queue",
    assigned_worker: Optional[str] = None,
    required_login: Optional[str] = None,
    priority: int = 100,
    dedup: bool = True,
) -> dict:
    """크롤 잡 1건 등록. 중복 방지(dedup) 시 같은 대상의 미완 잡이 있으면 재사용.

    Args:
        model_code: 대상 번들. None = 전체 번들.
        routing: 'queue'(우선순위 경쟁) | 'pinned'(assigned_worker 전용).
        assigned_worker: pinned 일 때 대상 워커 별명.
        required_login: 이 잡에 꼭 필요한 로그인 소싱처(예 'musinsa'). None=아무 워커.
        dedup: True 면 동일 (model_code, routing, assigned_worker) 의 미완 잡 재사용.

    Returns:
        {'id': int, 'created': bool, 'status': str}
    """
    s = SessionLocal()
    try:
        if dedup:
            q = (s.query(CrawlJob)
                 .filter(CrawlJob.status.in_(LIVE_STATUSES))
                 .filter(CrawlJob.routing == routing))
            # NULL 비교는 is_ 로 (== None 은 SQL 에서 항상 NULL)
            q = (q.filter(CrawlJob.model_code.is_(None)) if model_code is None
                 else q.filter(CrawlJob.model_code == model_code))
            q = (q.filter(CrawlJob.assigned_worker.is_(None)) if assigned_worker is None
                 else q.filter(CrawlJob.assigned_worker == assigned_worker))
            existing = q.order_by(CrawlJob.id.desc()).first()
            if existing is not None:
                return {"id": existing.id, "created": False, "status": existing.status}

        job = CrawlJob(
            model_code=model_code,
            phase="crawl",
            status="pending",
            routing=routing,
            required_login=required_login,
            priority=priority,
            assigned_worker=assigned_worker,
            triggered_by=triggered_by,
            created_at=_now(),
        )
        s.add(job)
        s.commit()
        return {"id": job.id, "created": True, "status": "pending"}
    finally:
        s.close()


def reap_expired_jobs(now: Optional[datetime] = None) -> dict:
    """리스 만료된 claimed/running 잡을 회수.

    lease_expires_at < now 이면 워커가 죽은 것으로 보고:
      - attempts < MAX_ATTEMPTS → pending 으로 되돌림(attempts++), 다른 워커가 승계
      - attempts >= MAX_ATTEMPTS → failed (무한 재시도 방지)

    Returns: {'requeued': int, 'failed': int}
    """
    now = now or _now()
    s = SessionLocal()
    requeued = failed = 0
    try:
        rows = (s.query(CrawlJob)
                .filter(CrawlJob.status.in_(("claimed", "running")))
                .filter(CrawlJob.lease_expires_at.isnot(None))
                .filter(CrawlJob.lease_expires_at < now)
                .all())
        for j in rows:
            j.attempts = (j.attempts or 0) + 1
            j.worker_name = None
            j.claimed_at = None
            j.lease_expires_at = None
            if j.attempts >= MAX_ATTEMPTS:
                j.status = "failed"
                j.finished_at = now
                j.error = (j.error or "") + " | 리스 만료 재시도 초과로 실패"
                failed += 1
            else:
                j.status = "pending"
                requeued += 1
        s.commit()
        return {"requeued": requeued, "failed": failed}
    finally:
        s.close()


def online_workers(now: Optional[datetime] = None, *, enabled_only: bool = True) -> list[dict]:
    """온라인(최근 하트비트) 워커 목록 — 우선순위 ASC."""
    now = now or _now()
    cutoff = now - timedelta(seconds=HEARTBEAT_ONLINE_SEC)
    s = SessionLocal()
    try:
        q = s.query(CrawlWorker)
        if enabled_only:
            q = q.filter(CrawlWorker.enabled.is_(True))
        out = []
        for w in q.order_by(CrawlWorker.priority.asc()).all():
            online = bool(w.last_heartbeat_at and w.last_heartbeat_at >= cutoff)
            out.append({
                "name": w.name, "owner": w.owner, "priority": w.priority,
                "online": online, "enabled": w.enabled,
                "logins": _loads(w.logins_json),
                "ip_address": w.ip_address,
            })
        return out
    finally:
        s.close()


def list_jobs(*, limit: int = 50, statuses: Optional[tuple] = None) -> list[dict]:
    """잡 큐 조회 — 최신순."""
    s = SessionLocal()
    try:
        q = s.query(CrawlJob)
        if statuses:
            q = q.filter(CrawlJob.status.in_(statuses))
        rows = q.order_by(CrawlJob.id.desc()).limit(limit).all()
        return [{
            "id": j.id, "model_code": j.model_code, "status": j.status,
            "routing": j.routing, "required_login": j.required_login,
            "assigned_worker": j.assigned_worker, "worker_name": j.worker_name,
            "priority": j.priority, "attempts": j.attempts,
            "triggered_by": j.triggered_by,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "error": (j.error or "")[:300] or None,
        } for j in rows]
    finally:
        s.close()


def queue_counts() -> dict:
    """대기/실행/완료 카운트 (대시보드용)."""
    s = SessionLocal()
    try:
        from sqlalchemy import func
        rows = (s.query(CrawlJob.status, func.count())
                .group_by(CrawlJob.status).all())
        return {st: n for st, n in rows}
    finally:
        s.close()


def cleanup_stale_bundle_runs(*, older_than_min: int = 30, now: Optional[datetime] = None) -> int:
    """기존 bundle_runs 의 좀비 'running' 정리 (1-D).

    스케줄러가 서버에서 크롤하던 시절 중단된 채 영원히 'running' 으로 남은 행을
    'expired' 로 마감한다. older_than_min 분 이상 안 끝난 running 만 대상.

    Returns: 정리된 행 수
    """
    now = now or _now()
    cutoff = now - timedelta(minutes=older_than_min)
    s = SessionLocal()
    try:
        from lemouton.sourcing.models import BundleRun
        rows = (s.query(BundleRun)
                .filter(BundleRun.status == "running")
                .filter(BundleRun.started_at < cutoff)
                .all())
        n = 0
        for r in rows:
            r.status = "expired"
            r.ended_at = now
            r.error = (r.error or "") + " | 서버 크롤 중단(좀비) — 워커 전환으로 정리"
            n += 1
        s.commit()
        return n
    finally:
        s.close()


def _loads(raw: Optional[str]) -> list:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def enqueue_verify(
    verify_url: str,
    *,
    required_login: Optional[str] = None,
    triggered_by: str = "guide_verify",
    priority: int = 50,
) -> dict:
    """가이드 ④ 검증용 단건 URL 크롤 잡 등록. phase='verify'.

    같은 URL 의 미완 verify 잡이 있으면 재사용(dedup). priority 50 = 일반 크롤(100)보다 우선.
    """
    if not (verify_url.startswith("http://") or verify_url.startswith("https://")):
        raise ValueError("verify_url must be http(s)")
    s = SessionLocal()
    try:
        existing = (s.query(CrawlJob)
                    .filter(CrawlJob.status.in_(LIVE_STATUSES))
                    .filter(CrawlJob.phase == "verify")
                    .filter(CrawlJob.verify_url == verify_url)
                    .order_by(CrawlJob.id.desc()).first())
        if existing is not None:
            return {"id": existing.id, "created": False, "status": existing.status}
        job = CrawlJob(
            model_code=None, phase="verify", status="pending", routing="queue",
            required_login=required_login, priority=priority,
            verify_url=verify_url, triggered_by=triggered_by, created_at=_now(),
        )
        s.add(job)
        s.commit()
        return {"id": job.id, "created": True, "status": "pending"}
    finally:
        s.close()


def get_job(job_id: int) -> Optional[dict]:
    """잡 1건 상태/결과 조회(폴링용)."""
    import json as _json
    s = SessionLocal()
    try:
        job = s.query(CrawlJob).get(job_id)
        if job is None:
            return None
        result = None
        if job.result_json:
            try:
                result = _json.loads(job.result_json)
            except Exception:
                result = None
        return {"id": job.id, "status": job.status, "phase": job.phase,
                "worker_name": job.worker_name, "verify_url": job.verify_url,
                "result": result, "error": job.error}
    finally:
        s.close()
