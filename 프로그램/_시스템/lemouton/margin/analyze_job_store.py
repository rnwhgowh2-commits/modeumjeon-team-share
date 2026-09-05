# -*- coding: utf-8 -*-
"""분석 백그라운드 작업 상태 저장소 (DB, 워커 공유) — pending_store.py 와 같은 이유.

🔴 프로세스 전역 dict 를 쓰면 안 되는 이유 — 앱은 gunicorn 워커 여러 개로 돈다.
   `/analyze/start` 가 스레드를 띄운 워커와 `/analyze/status` 폴링을 받는 워커가
   다를 수 있어, 작업 상태를 전역 dict 에 두면 다른 워커에서 "알 수 없는 작업"이 뜬다.

🔴 STALE_AFTER — 라이브 실측(2026-09-05): 대용량 매입 엑셀 분석 도중 워커가
   (gunicorn `--timeout 180` 안전망 또는 OOM-kill — 컨테이너가 1코어·900MB 상한,
   Dockerfile 참고) 조용히 죽으면 이 작업 행은 "running" 에서 영영 안 바뀐다.
   실제 작업 스레드는 진행 중일 때 주기적으로 `touch()` 를 호출해 살아있음을
   증명한다 — 그 하트비트가 STALE_AFTER 이상 끊기면 "죽었다"로 판정해 화면에
   무한 스피너 대신 재시도 가능한 에러를 보여준다(하트비트 주기 20초 대비 충분한
   여유).
"""
from __future__ import annotations

import datetime as _dt

from lemouton.margin.models import MarginAnalyzeJob

STALE_AFTER = _dt.timedelta(minutes=3)


def create(session, job_id: str) -> None:
    session.add(MarginAnalyzeJob(id=job_id, status="running"))
    session.commit()


def touch(session, job_id: str) -> None:
    """살아있음 하트비트 — 오래 도는 계산 중 주기적으로 호출."""
    row = session.get(MarginAnalyzeJob, job_id)
    if row is None:
        return
    row.updated_at = _dt.datetime.utcnow()
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
    status = row.status
    error = row.error
    http_status = row.http_status
    if status == "running" and _dt.datetime.utcnow() - row.updated_at > STALE_AFTER:
        # 하트비트가 끊겼다 = 워커가 응답 없이 죽었다(무한 스피너 대신 재시도 가능한 에러).
        status = "error"
        error = ("분석 도중 서버 응답이 끊겼습니다(워커 재시작 등). "
                 "매입 엑셀은 이미 저장돼 있으니 「분석 시작」을 다시 눌러 주세요.")
        http_status = 504
    return {
        "status": status,
        "analysis_id": row.analysis_id,
        "meta": row.meta,
        "error": error,
        "http_status": http_status,
    }
