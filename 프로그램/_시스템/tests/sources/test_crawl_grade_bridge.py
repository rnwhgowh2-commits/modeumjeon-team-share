"""기존 랩 통계(CrawlChangeStat) → 등급 강도(%) 다리.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §2

기존 통계는 **크롤 1회당 변동 확률**(변동률 r)로 센다.
등급 엔진은 **하루에 몇 번 바뀌나**(강도 %)로 센다.
둘은 같은 얘기를 다른 자로 잰 것이다:

    강도(%) = 변동률 r × 하루 크롤 횟수 × 100

하루 10번 크롤해서 그중 20%가 변동이면 → 하루 2회 변동 → 강도 200%.
"""
import pytest

from lemouton.sources.crawl_grade_bridge import (
    MIN_OBSERVATIONS,
    change_rate,
    estimate_union_count,
    intensity_from_rate,
    summarize_composition,
)


# ── 변동률 ──────────────────────────────────────────────────────

def test_변동률은_변동_나누기_관측():
    assert change_rate(observed=100, changed=20) == pytest.approx(0.2)


def test_관측이_모자라면_변동률을_말하지_않는다():
    """표본이 적으면 숫자가 요동친다. 모르면 모른다고 해야 계수가 안 튄다."""
    assert change_rate(observed=MIN_OBSERVATIONS - 1, changed=5) is None


def test_관측이_0이면_None():
    assert change_rate(observed=0, changed=0) is None


def test_변동이_관측보다_많으면_거부():
    """있을 수 없는 데이터 — 조용히 1.0 으로 만들지 않고 터뜨린다."""
    with pytest.raises(ValueError):
        change_rate(observed=10, changed=11)


def test_음수는_거부():
    with pytest.raises(ValueError):
        change_rate(observed=-1, changed=0)
    with pytest.raises(ValueError):
        change_rate(observed=10, changed=-1)


# ── 변동률 → 강도 ───────────────────────────────────────────────

def test_하루10번_크롤에_변동률20퍼센트면_강도200():
    assert intensity_from_rate(0.2, crawls_per_day=10) == pytest.approx(200.0)


def test_하루1번_크롤에_변동률100퍼센트면_강도100():
    assert intensity_from_rate(1.0, crawls_per_day=1) == pytest.approx(100.0)


def test_3일에_1번_크롤에_변동률100퍼센트면_강도는_33퍼센트():
    """뜸하게 긁으면 매번 바뀌어 있어도 실제 변동 빈도는 낮다."""
    assert intensity_from_rate(1.0, crawls_per_day=1 / 3) == pytest.approx(33.33, abs=0.01)


def test_변동률이_None이면_강도도_None():
    assert intensity_from_rate(None, crawls_per_day=10) is None


def test_크롤횟수가_0이하면_거부():
    with pytest.raises(ValueError):
        intensity_from_rate(0.2, crawls_per_day=0)


def test_더_자주_긁어도_강도_추정은_안정적이다():
    """같은 상품을 2배로 긁으면 관측이 2배 늘고 변동률은 절반이 된다 → 강도는 그대로.

    이게 이 추정식의 핵심 성질이다. 크롤을 늘렸다고 '더 자주 바뀐다'고 오판하면
    계수가 스스로 부풀어 오른다.
    """
    a = intensity_from_rate(change_rate(observed=100, changed=20), crawls_per_day=5)
    b = intensity_from_rate(change_rate(observed=200, changed=20), crawls_per_day=10)
    assert a == pytest.approx(b)


# ── 강도 → 변동 횟수(등급 엔진 입력) ────────────────────────────

def test_강도와_기간으로_변동횟수를_되돌린다():
    """crawl_grade.summarize 는 '기간 내 변동 횟수'를 받는다. 강도에서 되돌린다."""
    assert estimate_union_count(intensity_pct=200.0, window_days=30) == pytest.approx(60)
    assert estimate_union_count(intensity_pct=16.667, window_days=30) == pytest.approx(5, abs=0.01)


def test_강도0이면_변동횟수도_0():
    assert estimate_union_count(intensity_pct=0.0, window_days=30) == 0


# ── 구성 요약 ───────────────────────────────────────────────────

def _sum(observed=1000, changed=200, crawls_per_day=10, **kw):
    return summarize_composition(
        source_key="musinsa", brand="나이키",
        observed=observed, changed=changed,
        price_changed=kw.pop("price_changed", 120),
        stock_changed=kw.pop("stock_changed", 150),
        crawls_per_day=crawls_per_day, window_days=30, **kw)


def test_구성_요약이_등급을_낸다():
    out = _sum()                      # r=0.2 × 10회/일 = 강도 200% → 0등급
    assert out["intensity_pct"] == pytest.approx(200.0)
    assert out["grade"] == 0
    assert out["proposed_per_day"] == pytest.approx(2.0)


def test_구성_요약에_축별_강도가_담긴다():
    out = _sum()
    assert out["axes"]["price"]["intensity_pct"] == pytest.approx(120 / 1000 * 10 * 100)
    assert out["axes"]["stock"]["intensity_pct"] == pytest.approx(150 / 1000 * 10 * 100)


def test_축별_합이_합집합보다_커도_괜찮다():
    """같은 크롤에 가격·재고가 같이 바뀌면 changed 는 1로 세므로 축 합 > 합집합이 정상."""
    out = _sum(changed=200, price_changed=120, stock_changed=150)   # 120+150 > 200
    assert out["grade"] == 0


def test_합집합이_축_최댓값보다_작으면_거부한다():
    """있을 수 없는 데이터. 조용히 계산하면 계수가 틀어진다."""
    with pytest.raises(ValueError):
        _sum(changed=100, price_changed=120, stock_changed=150)


def test_표본이_모자라면_등급을_말하지_않는다():
    out = _sum(observed=MIN_OBSERVATIONS - 1, changed=5,
               price_changed=3, stock_changed=4)
    assert out["grade"] is None
    assert out["intensity_pct"] is None
    assert "표본" in out["note"]


def test_모순된_데이터는_표본이_적어도_터뜨린다():
    """불변식 검사가 표본 검사보다 먼저다 — 모순은 표본 크기와 무관하게 모순이다."""
    with pytest.raises(ValueError):
        _sum(observed=MIN_OBSERVATIONS - 1, changed=5,
             price_changed=120, stock_changed=150)


def test_요약에_구성_이름이_붙는다():
    out = _sum()
    assert out["composition"] == "musinsa > 나이키"


def test_이것은_구성_평균이지_상품별이_아님을_명시한다():
    """상품별 산포(시안 11 상세)는 이 데이터로 못 만든다 — 화면이 오해하면 안 된다."""
    out = _sum()
    assert out["granularity"] == "composition"
