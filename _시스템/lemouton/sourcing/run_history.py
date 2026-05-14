"""모음전 실행 이력 기록 헬퍼.

`record_start()` → 실행 시작 시 1행 INSERT, run_id 반환.
`record_end()` → 실행 종료 시 동일 run을 status/details/ended_at 으로 UPDATE.

크롤링은 소싱처별 결과를, 업로드는 마켓별 결과를 details_json 에 적재.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from shared.db import SessionLocal
from lemouton.sourcing.models import BundleRun, Model


SOURCE_KEYS = ("lemouton", "musinsa", "ssf", "lotteon", "ss_lemouton")
MARKET_KEYS = ("smartstore", "coupang")


def record_start(*, model_code: Optional[str], phase: str,
                 triggered_by: str = "manual") -> int:
    """run 시작 — id 반환."""
    s = SessionLocal()
    try:
        row = BundleRun(
            model_code=model_code,
            phase=phase,
            triggered_by=triggered_by,
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        s.add(row)
        s.commit()
        return row.id
    finally:
        s.close()


def record_end(run_id: int, *, status: str,
               details: Optional[dict] = None,
               error: Optional[str] = None) -> None:
    """run 종료 — status/ended_at/details_json/error 갱신.

    status: 'ok' | 'partial' | 'failed'
    또한 phase 가 crawl/full 이면 Model.last_crawled_at,
              upload/full 이면 Model.last_uploaded_at 갱신 (status != 'failed' 시).
    """
    s = SessionLocal()
    try:
        row = s.query(BundleRun).filter_by(id=run_id).first()
        if row is None:
            return
        row.status = status
        row.ended_at = datetime.now(timezone.utc)
        if details is not None:
            row.details_json = json.dumps(details, ensure_ascii=False)
        if error:
            row.error = error[:1000]

        # 모델 단위 last_*_at 갱신 — 단일 모델 run 일 때만
        if row.model_code and status != "failed":
            m = s.query(Model).filter_by(model_code=row.model_code).first()
            if m is not None:
                if row.phase in ("crawl", "full"):
                    m.last_crawled_at = row.ended_at
                if row.phase in ("upload", "full"):
                    m.last_uploaded_at = row.ended_at
        s.commit()
    finally:
        s.close()


def list_active(*, limit: int = 50) -> list[dict]:
    """실시간 로그 패널용 — 실행 중 + 최근 종료된 run 목록.

    정렬: 실행 중(running) 우선 → started_at 내림차순.
    완료된 run 도 일정 수만큼 함께 반환해 사용자가 결과를 확인할 수 있게 함.
    """
    s = SessionLocal()
    try:
        rows = (
            s.query(BundleRun)
            .order_by(BundleRun.started_at.desc())
            .limit(limit)
            .all()
        )
        out = []
        for r in rows:
            details = {}
            if r.details_json:
                try:
                    details = json.loads(r.details_json)
                except Exception:
                    details = {}
            out.append({
                "id": r.id,
                "model_code": r.model_code,
                "phase": r.phase,
                "triggered_by": r.triggered_by,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "status": r.status,
                "is_bulk": r.model_code is None,
                "sources": details.get("sources") or {},
                "markets": details.get("markets") or {},
                "duration_sec": details.get("duration_sec"),
                "error": (r.error or "")[:500],
            })
        # running 우선 정렬
        out.sort(key=lambda x: (0 if x["status"] == "running" else 1,
                                 -(int(x["id"]))))
        return out
    finally:
        s.close()


def get_run(run_id: int) -> dict | None:
    """단일 run 상세 — 행 펼치기 모달용."""
    s = SessionLocal()
    try:
        r = s.query(BundleRun).filter_by(id=run_id).first()
        if r is None:
            return None
        details = {}
        if r.details_json:
            try:
                details = json.loads(r.details_json)
            except Exception:
                details = {}
        return {
            "id": r.id,
            "model_code": r.model_code,
            "phase": r.phase,
            "triggered_by": r.triggered_by,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "status": r.status,
            "is_bulk": r.model_code is None,
            "sources": details.get("sources") or {},
            "markets": details.get("markets") or {},
            "duration_sec": details.get("duration_sec"),
            "mode": details.get("mode"),
            "requested_markets": details.get("requested_markets") or [],
            "error": r.error or "",
        }
    finally:
        s.close()


def list_for_bundle(model_code: str, *, limit: int = 20) -> list[dict]:
    """편집 페이지 '실행 이력' 섹션용 — 최근 N건."""
    s = SessionLocal()
    try:
        rows = (
            s.query(BundleRun)
            .filter(
                (BundleRun.model_code == model_code) | (BundleRun.model_code.is_(None))
            )
            .order_by(BundleRun.started_at.desc())
            .limit(limit)
            .all()
        )
        out = []
        for r in rows:
            details = {}
            if r.details_json:
                try:
                    details = json.loads(r.details_json)
                except Exception:
                    details = {}
            out.append({
                "id": r.id,
                "phase": r.phase,
                "triggered_by": r.triggered_by,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "status": r.status,
                "is_bulk": r.model_code is None,
                "sources": details.get("sources") or {},
                "markets": details.get("markets") or {},
                "duration_sec": details.get("duration_sec"),
                "error": r.error,
            })
        return out
    finally:
        s.close()


def summarize_status(d: dict) -> str:
    """details dict 에서 ok/partial/failed 자동 산정."""
    sources = d.get("sources") or {}
    markets = d.get("markets") or {}
    statuses: list[bool] = []
    for v in sources.values():
        statuses.append(bool(v.get("ok")))
    for v in markets.values():
        statuses.append(bool(v.get("ok")))
    if not statuses:
        return "ok"
    if all(statuses):
        return "ok"
    if any(statuses):
        return "partial"
    return "failed"
