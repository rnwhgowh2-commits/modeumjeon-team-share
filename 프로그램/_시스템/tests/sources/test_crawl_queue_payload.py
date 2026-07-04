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
