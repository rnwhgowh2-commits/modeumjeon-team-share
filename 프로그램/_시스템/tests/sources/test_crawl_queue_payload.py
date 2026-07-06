from datetime import datetime

from lemouton.sources.crawl_schedule import due_crawl_payload
from lemouton.sources.models import SourceProduct
from lemouton.pricing.settings import get_or_init

NOW = datetime(2026, 7, 4, 12, 0, 0)


def _enable(db, on=True, hours=6, minutes=0):
    s = get_or_init(db)
    s.crawl_auto_enabled = on
    s.crawl_interval_hours = hours
    s.crawl_interval_minutes = minutes
    db.flush()


def _sp(db, url, *, last=None, weight=1):
    sp = SourceProduct(site="musinsa", url=url, crawl_weight=weight,
                       no_change_streak=0, last_fetched_at=last)
    db.add(sp); db.flush()
    return sp


def test_disabled_returns_empty_and_flag(db):
    _enable(db, on=False)
    _sp(db, "u/never", last=None)  # due 지만 정지 상태
    out = due_crawl_payload(db, now=NOW)
    assert out["enabled"] is False
    assert out["items"] == [] and out["count"] == 0


def test_enabled_returns_due_items_with_fields(db):
    _enable(db, on=True)
    sp = _sp(db, "u/never", last=None, weight=3)  # 미크롤 → due
    out = due_crawl_payload(db, now=NOW)
    assert out["enabled"] is True
    assert out["count"] == 1
    item = out["items"][0]
    assert item["source_product_id"] == sp.id
    assert item["url"] == "u/never"
    assert item["site"] == "musinsa"
    assert item["crawl_weight"] == 3
    assert item["last_fetched_at"] is None
    assert out["base_interval_seconds"] == 6 * 3600


def test_last_fetched_at_serialized_iso(db):
    _enable(db, on=True)
    from datetime import timedelta
    _sp(db, "u/old", last=NOW - timedelta(hours=20))  # 크게 연체 → due
    out = due_crawl_payload(db, now=NOW)
    assert isinstance(out["items"][0]["last_fetched_at"], str)  # iso 문자열


def test_payload_includes_lap_stats(db):
    """링 박스(항목4) — 오늘 바퀴/평균/막대 데이터가 페이로드에 포함."""
    from lemouton.sources.models import CrawlLapRun
    from datetime import datetime as _dt, timedelta as _td
    _enable(db, on=True)
    _sp(db, "u/a")
    base = _dt(2026, 7, 5, 15, 0, 0)             # 6일 00:00 KST
    for m in (0, 30, 70):
        db.add(CrawlLapRun(completed_at=base + _td(minutes=m)))
    db.flush()
    st = due_crawl_payload(db, now=_dt(2026, 7, 6, 5, 0, 0))["lap_stats"]
    assert st["laps_today"] == 3
    assert st["current_lap_no"] == 4
    assert st["recent_lap_minutes"] == [30, 40]
    assert st["avg_lap_minutes"] == 35


def test_payload_includes_lap_progress(db):
    """링('이번 한 바퀴')이 읽는 가중 랩 진행률 — 항상 포함(정지 상태여도)."""
    from lemouton.sources.crawl_schedule import (
        set_crawl_weight_rule, record_crawl_served,
    )
    _enable(db, on=True)
    a = _sp(db, "u/a")                       # 계수1
    b = _sp(db, "u/b")                        # 계수2(규칙)
    set_crawl_weight_rule(db, "url", "u/b", 2); db.flush()
    prog = due_crawl_payload(db, now=NOW)["lap_progress"]
    assert prog["total"] == 3 and prog["served"] == 0 and prog["pct"] == 0
    # A 1회 크롤 = served 1/3
    record_crawl_served(a); db.flush()
    prog2 = due_crawl_payload(db, now=NOW)["lap_progress"]
    assert prog2["served"] == 1 and prog2["pct"] == 33
