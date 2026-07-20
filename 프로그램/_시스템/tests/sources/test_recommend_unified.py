"""추천기 통일 — 변동률 밴드 대신 **등급 체계**로 (사장님 5번 = 가).

■ 왜 통일하나
  같은 「계수를 몇으로 할까」를 두 방식이 서로 다르게 답하고 있었다.
    기존: 변동률 → 계수 (경계 2/5/10/20%) — 코드 주석에 "실측 없이 정한 출발점"
    신규: 강도 → 6등급 → 하루 N회 — 사장님이 7항목을 직접 정한 체계
  둘을 같이 띄우면 서로 다른 숫자를 권해 혼선이 난다.

■ 이어붙이는 방법
  recommend_weight 하나만 고치면 그걸 쓰는 화면이 전부 따라온다.
  다만 등급식은 **하루 크롤 횟수**를 알아야 강도를 낼 수 있다 →
  crawls_per_day 를 받으면 등급식, 없으면 옛 밴드(하위호환).
"""
import pytest

from lemouton.sources.crawl_change_stats import MIN_OBSERVATIONS, recommend_weight


# ── 표본 부족은 그대로 보류 ─────────────────────────────────────

def test_표본이_모자라면_보류(_=None):
    w, why = recommend_weight(rate=0.5, observed=MIN_OBSERVATIONS - 1)
    assert w is None
    assert "표본" in why


def test_변동률_미상이면_보류():
    w, why = recommend_weight(rate=None, observed=100)
    assert w is None


# ── 🔴 등급식 (crawls_per_day 를 주면) ──────────────────────────

def test_하루크롤을_주면_등급식으로_답한다():
    """변동률 20% × 하루 10회 = 강도 200% → 하루 2회 (상한).

    옛 밴드였다면 20% 는 계수 ×5 였다 — 전혀 다른 답이다.
    """
    w, why = recommend_weight(rate=0.2, observed=100, crawls_per_day=10)
    assert w == 2
    assert "강도" in why


def test_조용하면_낮게_권한다():
    w, why = recommend_weight(rate=0.01, observed=100, crawls_per_day=1)
    assert w == 1                      # 1% → 월간급 → 3일 1회 → 계수로는 1(최소)
    assert "강도" in why


def test_등급_이름이_근거에_들어간다():
    _, why = recommend_weight(rate=0.2, observed=100, crawls_per_day=10)
    assert "하루 2회 이상" in why


def test_관측과_변동_횟수도_근거에_남는다():
    """숫자 근거 없이 '계수 2' 만 보이면 사람이 판단할 수 없다."""
    _, why = recommend_weight(rate=0.2, observed=100, crawls_per_day=10)
    assert "100" in why and "20" in why


def test_계수는_1에서_5로_클램프():
    w, _ = recommend_weight(rate=1.0, observed=100, crawls_per_day=100)
    assert 1 <= w <= 5


# ── 하위호환 (crawls_per_day 없으면 옛 밴드) ────────────────────

def test_하루크롤을_모르면_옛_밴드로_답한다():
    """하루 크롤 횟수를 모르면 강도를 못 낸다 — 지어내지 않고 옛 방식으로."""
    w, why = recommend_weight(rate=0.25, observed=100)
    assert w == 5                      # 옛 밴드: 20% 이상 → ×5
    assert "변동률" in why


def test_변동없으면_계수1():
    w, why = recommend_weight(rate=0.0, observed=100)
    assert w == 1


# ── 두 방식이 다르다는 것 자체를 고정 ──────────────────────────

def test_같은_입력에_두_방식이_다른_답을_낸다():
    """이 차이가 「추천기가 둘」 문제의 실체다 — 통일 전까지 화면에 둘 다 띄우면 안 된다."""
    old, _ = recommend_weight(rate=0.2, observed=100)
    new, _ = recommend_weight(rate=0.2, observed=100, crawls_per_day=10)
    assert old != new
