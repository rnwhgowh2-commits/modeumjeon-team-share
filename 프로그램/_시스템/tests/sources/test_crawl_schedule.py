from datetime import datetime, timedelta, timezone

from lemouton.sources.crawl_schedule import (
    effective_interval_seconds, overdue_seconds, is_due,
    RELAX_STEP, RELAX_CAP,
)

HOUR = 3600
BASE = 6 * HOUR  # 기준주기 6시간


def test_weight_divides_interval():
    # 계수 2 = 절반 주기
    assert effective_interval_seconds(BASE, 2, 0) == BASE / 2
    # 계수 1 = 그대로
    assert effective_interval_seconds(BASE, 1, 0) == BASE


def test_streak_relaxes_up_to_cap():
    # 무변동 2회 → 1 + 2*0.5 = 2배
    assert effective_interval_seconds(BASE, 1, 2) == BASE * 2
    # 완화는 최대 RELAX_CAP(4배)까지만
    assert effective_interval_seconds(BASE, 1, 100) == BASE * RELAX_CAP


def test_high_weight_stays_frequent_even_relaxed():
    # 계수5·완화 최대여도 기준주기보다 자주(간격 < 기준)
    assert effective_interval_seconds(BASE, 5, 100) < BASE


def test_weight_none_defaults_to_one():
    assert effective_interval_seconds(BASE, None, 0) == BASE


def test_weight_zero_excludes_from_crawl():
    # [2026-07-10] 계수 0 = 크롤 제외 → 간격 무한대(마감 안 됨)
    assert effective_interval_seconds(BASE, 0, 0) == float("inf")
    now = datetime(2026, 7, 4, 12, 0, 0)
    # 아무리 오래됐어도 due 아님
    lf = now - timedelta(days=365)
    assert overdue_seconds(now, lf, BASE, 0, 0) == float("-inf")
    assert is_due(now, lf, BASE, 0, 0) is False
    # 한 번도 안 긁었어도(last_fetched None) due 아님 — 첫 크롤도 스킵
    assert overdue_seconds(now, None, BASE, 0, 0) == float("-inf")
    assert is_due(now, None, BASE, 0, 0) is False


def test_never_crawled_is_infinitely_overdue():
    now = datetime(2026, 7, 4, 12, 0, 0)
    assert overdue_seconds(now, None, BASE, 1, 0) == float("inf")
    assert is_due(now, None, BASE, 1, 0) is True


def test_overdue_and_due_threshold():
    now = datetime(2026, 7, 4, 12, 0, 0)
    # 정확히 기준주기 전에 긁음 → 연체 0, due True
    lf = now - timedelta(seconds=BASE)
    assert overdue_seconds(now, lf, BASE, 1, 0) == 0
    assert is_due(now, lf, BASE, 1, 0) is True
    # 절반만 지남 → 아직 아님
    lf2 = now - timedelta(seconds=BASE / 2)
    assert is_due(now, lf2, BASE, 1, 0) is False


def test_aware_and_naive_mixed_do_not_crash():
    now_naive = datetime(2026, 7, 4, 12, 0, 0)
    lf_aware = datetime(2026, 7, 4, 5, 0, 0, tzinfo=timezone.utc)  # 7시간 전
    # 섞여도 정규화되어 비교됨 (7h > 6h → due)
    assert is_due(now_naive, lf_aware, BASE, 1, 0) is True


from lemouton.sources.crawl_schedule import due_products
from lemouton.sources.models import SourceProduct

NOW = datetime(2026, 7, 4, 12, 0, 0)


def _sp(db, url, *, last, weight=1, streak=0):
    sp = SourceProduct(site="musinsa", url=url, crawl_weight=weight,
                       no_change_streak=streak, last_fetched_at=last)
    db.add(sp); db.flush()
    return sp


def test_due_products_orders_most_overdue_first(db):
    base = 6 * 3600
    a = _sp(db, "u/a", last=NOW - timedelta(hours=7))    # 1h 연체
    b = _sp(db, "u/b", last=NOW - timedelta(hours=20))   # 크게 연체
    c = _sp(db, "u/c", last=NOW - timedelta(hours=1))    # 아직 아님(6h 미만)
    never = _sp(db, "u/n", last=None)                    # 최우선
    out = due_products(db, base_interval_seconds=base, now=NOW)
    ids = [p.id for p in out]
    assert c.id not in ids               # 아직 마감 안 됨
    assert ids[0] == never.id            # 미크롤 최우선
    assert ids.index(b.id) < ids.index(a.id)   # 더 오래 밀린 b가 앞


def test_weight_makes_due_sooner(db):
    # [2026-07-05] 큐 계수는 이제 crawl_weight 컬럼이 아닌 계층 규칙(resolve_crawl_weight)이
    # 결정. 소싱처 규칙 ×2 를 건 사이트가 유효간격 3h → 딱 due, 규칙 없는 사이트는 6h → 아직.
    from lemouton.sources.crawl_schedule import set_crawl_weight_rule
    base = 6 * 3600
    # 3시간 전 크롤, 소싱처 규칙 ×2 → 유효간격 3h → 딱 due
    w2 = _sp(db, "u/w2", last=NOW - timedelta(hours=3))
    # 3시간 전 크롤, 규칙 없음(계수1) → 유효간격 6h → 아직 아님
    w1 = SourceProduct(site="ssf", url="u/w1", no_change_streak=0,
                       last_fetched_at=NOW - timedelta(hours=3))
    db.add(w1); db.flush()
    set_crawl_weight_rule(db, "source", "musinsa", 2); db.flush()
    ids = [p.id for p in due_products(db, base_interval_seconds=base, now=NOW)]
    assert w2.id in ids and w1.id not in ids


def test_streak_relaxation_delays_due(db):
    base = 6 * 3600
    # 7시간 전 크롤. 계수1·무변동2회 → 유효간격 12h → 아직 아님
    relaxed = _sp(db, "u/r", last=NOW - timedelta(hours=7), weight=1, streak=2)
    ids = [p.id for p in due_products(db, base_interval_seconds=base, now=NOW)]
    assert relaxed.id not in ids


def test_soft_deleted_excluded(db):
    base = 6 * 3600
    sp = _sp(db, "u/del", last=None)
    sp.deleted_at = NOW
    db.flush()
    ids = [p.id for p in due_products(db, base_interval_seconds=base, now=NOW)]
    assert sp.id not in ids


from lemouton.sources.crawl_schedule import (
    base_crawl_interval_seconds, select_due_products,
)
from lemouton.pricing.settings import get_or_init


def test_base_interval_from_settings(db):
    s = get_or_init(db)
    s.crawl_interval_hours = 6
    s.crawl_interval_minutes = 30
    db.flush()
    assert base_crawl_interval_seconds(db) == 6 * 3600 + 30 * 60


def test_select_due_products_uses_settings(db):
    s = get_or_init(db)
    s.crawl_interval_hours = 6
    s.crawl_interval_minutes = 0
    db.flush()
    _sp(db, "u/x", last=None)  # 미크롤 → 반드시 뽑힘
    out = select_due_products(db, now=NOW)
    assert any(p.url == "u/x" for p in out)
