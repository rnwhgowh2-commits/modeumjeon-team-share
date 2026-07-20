"""계수 제안을 실제 규칙으로 적용 — 스코프 판정.

사장님 4번 = 나 (버튼만 만들어 놓기).

■ 🔴 구조적 틈
  제안은 **(소싱처 × 브랜드)** 단위인데, 계수 규칙 스코프는
  `url · model · brand · source` 넷뿐이다 — **그 조합을 담을 자리가 없다.**
  brand 로 적용하면 그 브랜드가 **다른 소싱처에도** 걸린다.
  그래서 겹치는지 먼저 보고, 겹치면 **경고를 달아** 사람이 알고 누르게 한다.
"""
import pytest

from lemouton.sources.grade_apply import (
    ApplyPlan,
    plan_apply,
)


def test_브랜드가_한_소싱처에만_있으면_그대로_적용():
    p = plan_apply(source_key="musinsa", brand="나이키", proposed_weight=2,
                   brands_by_source={"musinsa": {"나이키", "아디다스"}})
    assert p.scope_type == "brand"
    assert p.scope_key == "나이키"
    assert p.weight == 2
    assert p.safe is True
    assert p.warning is None


def test_브랜드가_여러_소싱처에_걸치면_경고():
    """brand 규칙은 소싱처를 안 가린다 — 누르면 SSG 나이키도 같이 바뀐다."""
    p = plan_apply(source_key="musinsa", brand="나이키", proposed_weight=2,
                   brands_by_source={"musinsa": {"나이키"}, "ssg": {"나이키"}})
    assert p.safe is False
    assert p.warning
    assert "ssg" in p.warning
    assert p.affected_sources == ["musinsa", "ssg"]


def test_경고가_있어도_계획_자체는_만들어진다():
    """막지 않는다 — 사람이 알고 누르면 그대로 적용한다(확인 후 적용)."""
    p = plan_apply(source_key="musinsa", brand="나이키", proposed_weight=3,
                   brands_by_source={"musinsa": {"나이키"}, "ssg": {"나이키"}})
    assert p.scope_type == "brand"
    assert p.weight == 3


def test_브랜드가_비면_소싱처_전체로():
    """브랜드 미지정 구성 — 그 소싱처 전체에 건다."""
    p = plan_apply(source_key="musinsa", brand="", proposed_weight=2,
                   brands_by_source={"musinsa": set()})
    assert p.scope_type == "source"
    assert p.scope_key == "musinsa"
    assert p.safe is True


def test_괄호_브랜드도_미지정으로_본다():
    """통계가 '(브랜드 미지정)' 문자열을 쓴다 — 그걸 브랜드 이름으로 저장하면 안 된다."""
    p = plan_apply(source_key="musinsa", brand="(브랜드 미지정)", proposed_weight=2,
                   brands_by_source={"musinsa": set()})
    assert p.scope_type == "source"


# ── 계수 범위 ───────────────────────────────────────────────────

def test_계수는_0에서_5로_클램프():
    """스케줄러가 min(5, int) 로 접는다 — 여기서 미리 맞춰 화면과 실제가 안 어긋나게."""
    assert plan_apply(source_key="s", brand="b", proposed_weight=9,
                      brands_by_source={"s": {"b"}}).weight == 5
    assert plan_apply(source_key="s", brand="b", proposed_weight=-1,
                      brands_by_source={"s": {"b"}}).weight == 0


def test_계수0은_크롤_제외라_따로_알린다():
    """0 = 크롤 제외. 실수로 누르면 그 URL 이 영영 안 긁힌다."""
    p = plan_apply(source_key="s", brand="b", proposed_weight=0,
                   brands_by_source={"s": {"b"}})
    assert p.weight == 0
    assert p.warning and "크롤 제외" in p.warning
    assert p.safe is False


def test_소싱처가_비면_거부():
    with pytest.raises(ValueError):
        plan_apply(source_key="", brand="b", proposed_weight=2, brands_by_source={})


# ── dict 변환 ───────────────────────────────────────────────────

def test_화면에_넘길_dict():
    d = plan_apply(source_key="musinsa", brand="나이키", proposed_weight=2,
                   brands_by_source={"musinsa": {"나이키"}}).to_dict()
    assert d["scope_type"] == "brand"
    assert d["safe"] is True
    assert "label" in d and "나이키" in d["label"]


def test_ApplyPlan은_그대로_들고다닐_수_있다():
    p = ApplyPlan(scope_type="brand", scope_key="나이키", weight=2,
                  safe=True, warning=None, affected_sources=["musinsa"])
    assert p.to_dict()["weight"] == 2
