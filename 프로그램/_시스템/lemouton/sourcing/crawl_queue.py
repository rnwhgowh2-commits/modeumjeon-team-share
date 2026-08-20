"""다중 워커 크롤 잡 큐 — 등록(enqueue)·조회·리스 만료 회수(reaper)·워커 생존 판정.

'그 크롤 PC 가 지금 켜져 있나'(온라인 판정)도 여기 산다 — 폰 리모컨의 🟢/⚪ 근거다.

설계: docs/crawl-worker-system.md
서버(스케줄러/버튼)는 여기 enqueue 만 하고, 실제 크롤은 로컬 PC 워커(Phase 2)가
원자적으로 선점·실행한다. 본 모듈은 큐의 단일 진실 원천.

원자적 선점(claim) 로직 자체는 워커 측(Phase 2)에서 FOR UPDATE SKIP LOCKED 로
구현한다 — 여기서는 등록/회수/조회만 담당한다.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError

from shared.db import SessionLocal
from lemouton.sourcing.models import CrawlJob, CrawlWorker

# ── 정책 상수 ──────────────────────────────────────────────
# [2026-08-04] 90 → 180. 생존 신호를 보내는 확장(moum-crawler)의 크롤 폴링 주기가
#   chrome.alarms 최소값인 **1분**이다. 90초면 여유가 30초뿐이라 한 번만 늦어도
#   🟢→⚪ 로 깜빡인다. MV3 서비스워커 알람은 PC 절전·부하 시 실제로 지연된다
#   (알람 전환 자체가 SW 언로드 때문이었다 — background.js v0.7.15 주석).
#   3주기(180초)면 두 번 연속 놓쳐야 꺼진 것으로 본다.
HEARTBEAT_ONLINE_SEC = 180     # 마지막 하트비트 이내면 온라인 (확장 폴링 1분 × 3)
LEASE_SEC = 300                # 선점 후 5분간 하트비트 없으면 잡 회수
MAX_ATTEMPTS = 3               # 회수 누적 N회 초과 시 failed 처리

# 잡이 "살아있다(이미 처리 중/대기)"고 보는 상태 — 중복 등록 판정용
LIVE_STATUSES = ("pending", "claimed", "running")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """DB 컬럼(DateTime)은 naive UTC 로 저장된다 — 비교 전에 tz 를 붙인다.

    안 붙이면 aware 인 _now() 와 비교하는 순간 TypeError 다.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _is_online(last_heartbeat_at: Optional[datetime], now: Optional[datetime] = None) -> bool:
    """온라인 판정 단일 원천 — 마지막 생존 신호가 HEARTBEAT_ONLINE_SEC 이내인가.

    워커 목록(online_workers)과 폰 리모컨(worker_presence)이 **같은 규칙**을 쓰게 한다.
    따로 두면 한쪽만 고쳐져 화면마다 다른 답을 낸다.
    """
    last = _as_utc(last_heartbeat_at)
    if last is None:
        return False
    return ((now or _now()) - last).total_seconds() <= HEARTBEAT_ONLINE_SEC


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
    now = _as_utc(now) or _now()
    s = SessionLocal()
    try:
        # 센티널 행(CRAWL_PC_NAME)은 사람이 등록한 PC 가 아니라 '폴링이 다녀갔다'는
        #   표식일 뿐이다 — 워커 목록 화면에 정체불명 이름으로 뜨면 안 된다.
        q = s.query(CrawlWorker).filter(CrawlWorker.name != CRAWL_PC_NAME)
        if enabled_only:
            q = q.filter(CrawlWorker.enabled.is_(True))
        out = []
        for w in q.order_by(CrawlWorker.priority.asc()).all():
            # 🔴 예전엔 naive 컬럼을 aware cutoff 와 직접 비교해 TypeError 였다.
            #   컬럼이 늘 NULL 이라 단락평가로 안 터졌을 뿐이다(첫 writer 가 생기면 터진다).
            online = _is_online(w.last_heartbeat_at, now)
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


# ══════════════════════════════════════════════════════════════════════
# 폰 크롤 리모컨용 — 로컬 PC 생존 신호
#
# 확장(moum-crawler)이 /api/crawl/due-bundles 를 부르는 순간을 서버가 기록해서
# '지금 크롤 PC 가 켜져 있나'를 판정한다. 확장은 v0.7.69 부터 크롤이 멈춰 있어도
# 1분마다 이 엔드포인트를 부른다(상시 폴링) — 그래서 이 신호가 곧 PC 생존이다.
#
# 🔴 /api/crawl/queue 에는 절대 붙이지 않는다. 거기는 확장이 아니라 **PC 자동화
#    화면 JS** 가 1.5초마다 부르는 곳이라, 붙이면 확장이 꺼져 있어도 🟢 로 보인다
#    = 사장님이 '눌러도 아무 일 없는 버튼'을 누르게 된다(2026-08-04 실측 교정).
#
# 지금 크롤 PC 는 한 대다 → 행 하나(CRAWL_PC_NAME)만 쓴다. 여러 대를 구분해야
# 하면 CrawlWorker 가 이미 name 별 다중 행을 지원하므로 그때 확장한다.
# ══════════════════════════════════════════════════════════════════════
# ★센티널 이름 — 사람이 등록하는 별명과 절대 겹치면 안 된다. CrawlWorker.name 은
#   모델 주석대로 '사용자가 붙이는 별명'이라, 팀원이 자기 PC 를 "크롤 PC" 로 등록하면
#   같은 행을 두고 싸우다 ip_address 까지 덮어쓴다. 화면에 보일 한글 이름은 표시할 때 붙인다.
CRAWL_PC_NAME = "__crawl_poll__"
HEARTBEAT_WRITE_MIN_SEC = 30      # 이 안에 다시 오면 DB 를 안 건드린다

_MOBILE_UA_MARKERS = ("iphone", "ipad", "android", "mobile")

# 프로세스 로컬 문지기 — 세션을 열기 **전에** 거른다. 이게 없으면 폴링마다
#   SessionLocal() + SELECT 왕복이 생긴다(Supabase 무료 티어에 불필요한 부하).
#   워커 프로세스마다 따로여도 지연 상한은 그대로 HEARTBEAT_WRITE_MIN_SEC 라 정확도 손실 없음.
_last_touch_monotonic = 0.0


def _looks_like_phone(user_agent: Optional[str]) -> bool:
    ua = (user_agent or "").lower()
    return any(m in ua for m in _MOBILE_UA_MARKERS)


def touch_worker_heartbeat(*, ip_address: Optional[str] = None,
                           user_agent: Optional[str] = None,
                           now: Optional[datetime] = None) -> None:
    """크롤 폴링이 들어온 순간을 남긴다. 폰에서 온 요청은 무시한다.

    폰으로 PC용 자동화 화면을 열어도 'PC 연결됨'이 되면 안 된다 —
    그러면 눌러도 아무 일 없는 버튼을 누르게 된다.

    now: 시험·재생용 시계 주입(같은 파일 reap_expired_jobs·online_workers 관행).
         주입하면 프로세스 로컬 문지기는 건너뛴다 — 호출자가 시계를 통제하므로
         monotonic(벽시계와 무관) 기준으로 거르는 게 무의미해진다.
    """
    global _last_touch_monotonic
    if _looks_like_phone(user_agent):
        return

    if now is None:
        mono = time.monotonic()
        if (mono - _last_touch_monotonic) < HEARTBEAT_WRITE_MIN_SEC:
            return                      # DB 를 열지도 않는다
        _last_touch_monotonic = mono    # 왕복을 '지금 한다'고 선점(결과와 무관하게 30초 잠금)

    now = _as_utc(now) or _now()
    s = SessionLocal()
    try:
        w = s.query(CrawlWorker).filter(CrawlWorker.name == CRAWL_PC_NAME).first()
        if w is None:
            s.add(CrawlWorker(name=CRAWL_PC_NAME,
                              last_heartbeat_at=now.replace(tzinfo=None),
                              ip_address=ip_address))
            try:
                s.commit()
                return
            except IntegrityError:
                # 동시 폴링 2건이 둘 다 '행 없음'을 봤다 — name 유니크에 걸린 쪽은
                #   진 게 아니라 늦은 것뿐이다. 되돌리고 UPDATE 경로로 1회 승계한다.
                #   (라우트의 광범위 except 에 맡기면 매번 풀 트레이스백이 로그를 더럽힌다.)
                s.rollback()
                w = s.query(CrawlWorker).filter(CrawlWorker.name == CRAWL_PC_NAME).first()
                if w is None:
                    return              # 유니크 말고 다른 이유였다 — 다음 폴링에 맡긴다
        last = _as_utc(w.last_heartbeat_at)
        if last is not None and (now - last).total_seconds() < HEARTBEAT_WRITE_MIN_SEC:
            return
        w.last_heartbeat_at = now.replace(tzinfo=None)
        if ip_address:
            w.ip_address = ip_address
        s.commit()
    finally:
        s.close()


def worker_presence(now: Optional[datetime] = None) -> dict:
    """폰 리모컨용 — {'online': bool, 'last_seen_at': iso|None, 'seconds_ago': int|None}"""
    now = _as_utc(now) or _now()
    s = SessionLocal()
    try:
        w = s.query(CrawlWorker).filter(CrawlWorker.name == CRAWL_PC_NAME).first()
        last = _as_utc(w.last_heartbeat_at) if w is not None else None
    finally:
        s.close()
    if last is None:
        return {"online": False, "last_seen_at": None, "seconds_ago": None}
    return {
        "online": _is_online(last, now),
        "last_seen_at": last.isoformat(),
        "seconds_ago": int((now - last).total_seconds()),
    }
