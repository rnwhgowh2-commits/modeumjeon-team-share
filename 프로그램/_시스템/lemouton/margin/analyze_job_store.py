# -*- coding: utf-8 -*-
"""분석 백그라운드 작업 상태 저장소 (DB, 워커 공유) — pending_store.py 와 같은 이유.

🔴 프로세스 전역 dict 를 쓰면 안 되는 이유 — 앱은 gunicorn 워커 여러 개로 돈다.
   `/analyze/start` 가 스레드를 띄운 워커와 `/analyze/status` 폴링을 받는 워커가
   다를 수 있어, 작업 상태를 전역 dict 에 두면 다른 워커에서 "알 수 없는 작업"이 뜬다.
"""
from __future__ import annotations

import datetime as _dt

from lemouton.margin.models import MarginAnalyzeJob


def create(session, job_id: str) -> None:
    session.add(MarginAnalyzeJob(id=job_id, status="running"))
    session.commit()


def mark_done(session, job_id: str, analysis_id: int, meta: dict) -> None:
    row = session.get(MarginAnalyzeJob, job_id)
    if row is None:
        return
    row.status = "done"
    row.analysis_id = analysis_id
    row.meta = meta
    row.updated_at = _dt.datetime.utcnow()
    session.commit()


def mark_error(session, job_id: str, error: str, http_status: int) -> None:
    row = session.get(MarginAnalyzeJob, job_id)
    if row is None:
        return
    row.status = "error"
    row.error = (error or "")[:2000]
    row.http_status = http_status
    row.updated_at = _dt.datetime.utcnow()
    session.commit()


def get(session, job_id: str) -> dict | None:
    row = session.get(MarginAnalyzeJob, job_id)
    if row is None:
        return None
    return {
        "status": row.status,
        "analysis_id": row.analysis_id,
        "meta": row.meta,
        "error": row.error,
        "http_status": row.http_status,
    }
