"""느리게 배수(crawl_slowdown) — 「3일에 1회」처럼 계수로 표현 못 하던 주기.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §4-1-1

    유효간격 = 기준주기 ÷ 계수 × 느리게배수 × 완화배수

계수(crawl_weight)는 **자주 긁는 쪽**만 표현한다(1~5 정수, Integer 컬럼).
분수 계수를 넣으면 int() 가 0 으로 만들고 0 은 '크롤 제외'라 상품이 영영 안 긁힌다.
그래서 **뜸하게 긁는 쪽은 방향을 갈라** 별도 배수로 표현한다.

    하루 2회  →  계수 2 · 느리게 1
    3일 1회   →  계수 1 · 느리게 3
"""
import pytest

from lemouton.sources.crawl_schedule import (
    RELAX_CAP,
    effective_interval_seconds,
    is_due,
    overdue_seconds,
)

BASE = 3600.0   # 기준주기 1시간


# ── 기본 동작이 안 바뀐다 (하위호환) ─────────────────────────────

def test_느리게배수를_안_주면_예전과_똑같다():
    assert effective_interval_seconds(BASE, 2, 0) == BASE / 2
    assert effective_interval_seconds(BASE, 1, 0) == BASE
    assert effective_interval_seconds(BASE, 1, 2) == BASE * 2


def test_느리게배수_1은_안_준_것과_같다():
    assert effective_interval_seconds(BASE, 2, 0, slowdown=1.0) == BASE / 2


def test_느리게배수_None도_1로_본다():
    """DB 에 아직 값이 없는 기존 행(NULL)이 크롤에서 빠지면 안 된다."""
    assert effective_interval_seconds(BASE, 2, 0, slowdown=None) == BASE / 2


# ── 뜸하게 긁기 ─────────────────────────────────────────────────

def test_느리게_3배면_간격이_3배():
    assert effective_interval_seconds(BASE, 1, 0, slowdown=3.0) == BASE * 3


def test_계수와_함께_쓰면_곱해진다():
    """계수 2(2배 자주) × 느리게 3(3배 뜸하게) = 1.5배 간격."""
    assert effective_interval_seconds(BASE, 2, 0, slowdown=3.0) == pytest.approx(BASE * 1.5)


def test_완화배수와도_같이_곱해진다():
    assert effective_interval_seconds(BASE, 1, 2, slowdown=3.0) == pytest.approx(BASE * 2 * 3)


def test_완화_상한은_그대로_지켜진다():
    assert effective_interval_seconds(BASE, 1, 100, slowdown=2.0) == pytest.approx(
        BASE * RELAX_CAP * 2)


# ── 🔴 안전 규칙 ────────────────────────────────────────────────

def test_계수0은_여전히_크롤_제외다():
    """느리게배수가 뭐든 계수 0 은 '이 URL 은 안 긁는다' 는 뜻이다. 바뀌면 안 된다."""
    assert effective_interval_seconds(BASE, 0, 0, slowdown=3.0) == float("inf")


def test_느리게배수는_1보다_작을_수_없다():
    """1 미만이면 '더 자주'가 되는데, 그건 계수가 할 일이다.

    두 손잡이가 같은 방향을 조절하면 어느 쪽이 이겼는지 알 수 없게 된다.
    """
    with pytest.raises(ValueError):
        effective_interval_seconds(BASE, 1, 0, slowdown=0.5)


def test_느리게배수_0이나_음수도_거부():
    with pytest.raises(ValueError):
        effective_interval_seconds(BASE, 1, 0, slowdown=0)
    with pytest.raises(ValueError):
        effective_interval_seconds(BASE, 1, 0, slowdown=-1)


# ── 연체·마감 판정에도 반영된다 ──────────────────────────────────

def test_느리게_긁는_상품은_늦게_마감난다():
    from datetime import datetime, timedelta
    now = datetime(2026, 7, 19, 12, 0, 0)
    lf = now - timedelta(seconds=BASE * 2)          # 2시간 전에 긁음

    assert is_due(now, lf, BASE, 1, 0) is True                    # 기본이면 벌써 마감
    assert is_due(now, lf, BASE, 1, 0, slowdown=3.0) is False     # 3배 뜸하면 아직


def test_연체초에도_반영된다():
    from datetime import datetime, timedelta
    now = datetime(2026, 7, 19, 12, 0, 0)
    lf = now - timedelta(seconds=BASE * 4)
    od = overdue_seconds(now, lf, BASE, 1, 0, slowdown=3.0)
    assert od == pytest.approx(BASE * 4 - BASE * 3)


def test_한_번도_안_긁은_건_느리게여도_최우선():
    now_ = __import__("datetime").datetime(2026, 7, 19, 12, 0, 0)
    assert overdue_seconds(now_, None, BASE, 1, 0, slowdown=9.0) == float("inf")
