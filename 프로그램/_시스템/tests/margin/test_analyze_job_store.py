# -*- coding: utf-8 -*-
"""analyze_job_store — 하트비트 기반 stale 판정.

2026-09-05 라이브 실측: 대용량 매입 엑셀 분석 도중 워커가 조용히 죽으면(gunicorn
--timeout 180 안전망 또는 OOM-kill) 이 작업 행이 "running" 에서 영영 안 바뀌어
화면이 무한 스피너가 됐다. touch() 하트비트가 STALE_AFTER 이상 끊기면 get() 이
"error"로 승격해 재시도 가능하게 만든다 — 그 판정 경계를 여기서 고정한다.
"""
import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.margin import analyze_job_store as store
from lemouton.margin.models import MarginAnalyzeJob


@pytest.fixture
def session(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", future=True)
    MarginAnalyzeJob.__table__.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    s = Session()
    yield s
    s.close()


def test_fresh_running_job_stays_running(session):
    store.create(session, "j1")
    assert store.get(session, "j1")["status"] == "running"


def test_touch_keeps_it_running_even_past_stale_window(session):
    store.create(session, "j1")
    row = session.get(MarginAnalyzeJob, "j1")
    row.updated_at = _dt.datetime.utcnow() - store.STALE_AFTER * 2
    session.commit()
    # 방금 하트비트가 들어왔다 — 옛 updated_at 을 지금으로 되돌린다.
    store.touch(session, "j1")
    assert store.get(session, "j1")["status"] == "running"


def test_no_heartbeat_past_stale_window_becomes_retryable_error(session):
    store.create(session, "j1")
    row = session.get(MarginAnalyzeJob, "j1")
    row.updated_at = _dt.datetime.utcnow() - store.STALE_AFTER - _dt.timedelta(seconds=1)
    session.commit()
    j = store.get(session, "j1")
    assert j["status"] == "error"
    assert j["http_status"] == 504
    assert "다시" in j["error"]


def test_done_job_ignores_staleness_check(session):
    store.create(session, "j1")
    store.mark_done(session, "j1", analysis_id=42, meta={"counts": {}})
    row = session.get(MarginAnalyzeJob, "j1")
    row.updated_at = _dt.datetime.utcnow() - store.STALE_AFTER * 10
    session.commit()
    j = store.get(session, "j1")
    assert j["status"] == "done"
    assert j["analysis_id"] == 42


def test_unknown_job_returns_none(session):
    assert store.get(session, "nope") is None
