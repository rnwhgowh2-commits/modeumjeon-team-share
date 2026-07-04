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


def test_weight_none_or_zero_treated_as_one():
    assert effective_interval_seconds(BASE, None, 0) == BASE
    assert effective_interval_seconds(BASE, 0, 0) == BASE


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
