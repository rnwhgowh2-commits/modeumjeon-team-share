"""등급 제안을 기존 스케줄러 단위로 옮기기 — 「하루 N회」 ↔ crawl_weight.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §4-1

기존 스케줄러: 유효간격 = 기준주기 ÷ crawl_weight × 완화배수
그런데 effective_interval_seconds 가 int(weight) · min(5, ...) 로 접는다.
→ 「3일에 1회」(=0.33) 를 그대로 넣으면 int() 가 0 으로 만들고, 0 은 '크롤 제외'다.
   이 함정을 조용히 지나가면 상품이 영영 안 긁힌다.
"""
import pytest

from lemouton.sources.crawl_grade import GradeConfig
from lemouton.sources.crawl_grade_apply import (
    DAY_SECONDS,
    CoefficientProposal,
    build_proposal,
    per_day_to_interval_seconds,
    should_resurface,
    weight_for,
    weight_is_expressible,
)


# ── 하루 N회 → 간격(초) ──────────────────────────────────────────

def test_하루_2회는_12시간_간격():
    assert per_day_to_interval_seconds(2.0) == pytest.approx(DAY_SECONDS / 2)


def test_하루_1회는_24시간_간격():
    assert per_day_to_interval_seconds(1.0) == pytest.approx(DAY_SECONDS)


def test_3일_1회는_72시간_간격():
    assert per_day_to_interval_seconds(1 / 3) == pytest.approx(DAY_SECONDS * 3)


def test_0회는_거부():
    with pytest.raises(ValueError):
        per_day_to_interval_seconds(0)


# ── 간격 → crawl_weight ─────────────────────────────────────────

def test_기준주기가_하루면_하루2회는_계수2():
    assert weight_for(2.0, base_interval_seconds=DAY_SECONDS) == pytest.approx(2.0)


def test_기준주기가_하루면_3일1회는_계수_3분의1():
    assert weight_for(1 / 3, base_interval_seconds=DAY_SECONDS) == pytest.approx(1 / 3)


def test_기준주기가_12시간이면_하루2회는_계수1():
    assert weight_for(2.0, base_interval_seconds=DAY_SECONDS / 2) == pytest.approx(1.0)


def test_기준주기가_0이면_거부():
    """기준주기 0 = '항상 마감'(연속). 나눗셈이 성립하지 않는다."""
    with pytest.raises(ValueError):
        weight_for(1.0, base_interval_seconds=0)


# ── 🔴 표현 가능성 — int() 절삭 함정 ─────────────────────────────

def test_1에서_5사이_정수만_지금_스케줄러가_표현한다():
    assert weight_is_expressible(1.0) is True
    assert weight_is_expressible(2.0) is True
    assert weight_is_expressible(5.0) is True


def test_5를_넘으면_표현_못한다():
    """effective_interval_seconds 가 min(5, ...) 로 접는다."""
    assert weight_is_expressible(6.0) is False


def test_1미만은_표현_못한다_이게_제일_위험하다():
    """int(0.33) == 0 이고, 계수 0 은 '크롤 제외'(간격 무한대)다.

    그대로 넣으면 상품이 영영 안 긁힌다. 반드시 막아야 하는 경로.
    """
    assert weight_is_expressible(1 / 3) is False
    assert weight_is_expressible(0.5) is False
    assert weight_is_expressible(0.99) is False


def test_정수가_아니면_표현_못한다():
    assert weight_is_expressible(1.5) is False
    assert weight_is_expressible(2.7) is False


def test_0과_음수도_표현_못한다():
    assert weight_is_expressible(0) is False
    assert weight_is_expressible(-1) is False


# ── 제안 만들기 ─────────────────────────────────────────────────

def _p(union_count, current_weight=1, **kw):
    return build_proposal(
        target_id="musinsa:DD1391-100",
        label="덩크 로우 레트로 팬다",
        union_count=union_count,
        window_days=30,
        current_weight=current_weight,
        base_interval_seconds=DAY_SECONDS,
        **kw,
    )


def test_자주_바뀌면_계수를_올리자고_제안한다():
    p = _p(union_count=75)          # 250% → 하루 2회 (상한)
    assert p.proposed_per_day == pytest.approx(2.0)
    assert p.direction == "up"
    assert p.applicable is True


def test_조용하면_계수를_내리자고_제안한다():
    p = _p(union_count=1, current_weight=2)   # 3.3% → 월간급 → 3일 1회
    assert p.proposed_per_day == pytest.approx(1 / 3)
    assert p.direction == "down"


def test_바꿀_게_없으면_제안하지_않는다():
    p = _p(union_count=30, current_weight=1)  # 100% → 하루 2회? 아니 100%는 1등급
    # 100% = 1등급(하루 1회) → 제안 2회/일. 현재 1회/일 → 올림.
    assert p.direction == "up"
    same = _p(union_count=15, current_weight=1)   # 50% → 2등급 → 1회/일 = 현재와 같음
    assert same.direction == "same"
    assert same.is_noop is True


def test_제안에_근거_문장이_들어간다():
    p = _p(union_count=75)
    assert "30일" in p.reason
    assert "75" in p.reason


def test_근거에_상한에_걸린_사실이_보인다():
    p = _p(union_count=75)           # 250% → 제안 3회지만 상한 2회
    assert p.capped is True
    assert "상한" in p.reason


# ── 🔴 표현 못 하는 제안은 자동 적용 금지 ────────────────────────

def test_3일1회_제안이_이제_적용된다():
    """느리게배수 도입 전에는 계수 1/3 이 int() 에 잘려 '크롤 제외'가 됐다.

    이제 (계수 1, 느리게 3) 두 손잡이로 쪼개 정확히 표현한다.
    """
    p = _p(union_count=1, current_weight=2)
    assert p.proposed_per_day == pytest.approx(1 / 3)
    assert p.applicable is True
    assert p.proposed_weight_int == 1
    assert p.proposed_slowdown == pytest.approx(3.0)
    assert p.blocked_reason is None


def test_하루2회는_계수2_느리게1로_쪼개진다():
    p = _p(union_count=75)
    assert p.proposed_weight_int == 2
    assert p.proposed_slowdown == pytest.approx(1.0)
    assert p.applicable is True


def test_기준주기가_너무_길면_자주_긁기가_막힌다():
    """계수 상한 5 로도 모자라면 느리게배수로는 해결이 안 된다 — 사실대로 말한다."""
    p = build_proposal(
        target_id="t", label="l", union_count=75, window_days=30,
        current_weight=1, base_interval_seconds=DAY_SECONDS * 20)   # 기준주기 20일
    assert p.applicable is False
    assert p.blocked_reason and "기준 주기" in p.blocked_reason


def test_적용가능한_제안은_계수까지_계산해_준다():
    p = _p(union_count=75)
    assert p.proposed_weight == pytest.approx(2.0)
    assert p.applicable is True
    assert p.blocked_reason is None


# ── 무시한 제안 다시 안 올리기 (§4-1) ────────────────────────────

def test_무시한_뒤_등급이_그대로면_다시_안_올린다():
    assert should_resurface(current_grade=2, dismissed_at_grade=2) is False


def test_무시한_뒤_등급이_바뀌면_다시_올린다():
    assert should_resurface(current_grade=1, dismissed_at_grade=2) is True
    assert should_resurface(current_grade=3, dismissed_at_grade=2) is True


def test_무시한_적이_없으면_당연히_올린다():
    assert should_resurface(current_grade=2, dismissed_at_grade=None) is True


# ── 사장님 설정이 제안에 반영된다 ────────────────────────────────

def test_상한을_올리면_제안도_따라_올라간다():
    cfg = GradeConfig(ceiling_per_day=6.0)
    p = _p(union_count=75, config=cfg)
    assert p.proposed_per_day == pytest.approx(3.0)
    assert p.capped is False


def test_하한을_내리면_조용한_상품_제안도_내려간다():
    cfg = GradeConfig(floor_per_day=1 / 7)
    p = _p(union_count=0, current_weight=1, config=cfg)
    assert p.proposed_per_day == pytest.approx(1 / 7)


def test_제안은_dict로_뽑을_수_있다():
    d = _p(union_count=75).to_dict()
    assert d["proposed_text"] == "2회/일"
    assert d["applicable"] is True
    assert "reason" in d
