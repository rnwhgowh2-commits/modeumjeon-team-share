"""Unit tests for lemouton.pricing.benefit_gate — 포함/제외 키워드 게이트.

순수 함수 — DB·Flask 불필요. 르무통 메이트 실제 혜택 라인을 픽스처로 사용.
"""
from lemouton.pricing.benefit_gate import (
    line_matches_triggers, line_excluded, gate_benefit, gate_benefits,
)


# 2026-06-11 라이브 추출 — 르무통 메이트 (musinsa.com/products/4046672) 혜택 라인
MOUM_LINES = [
    "등급 할인 불가",
    "상품 쿠폰",
    "적립금 사용",
    "구매 적립 / 선할인",
    "최대 적립",
    "10% 추가 적립",
    "결제혜택",
    "무신사 회원은 전 품목 무료배송",
]


# ── 포함 any/all ────────────────────────────────────────────────────────────
def test_any_matches_when_one_present():
    assert line_matches_triggers("구매 적립 / 선할인", ["적립", "캐시백"], "any") is True


def test_all_fails_when_one_missing():
    assert line_matches_triggers("구매 적립 / 선할인", ["적립", "캐시백"], "all") is False


def test_all_passes_when_every_present():
    assert line_matches_triggers("구매 적립 / 선할인", ["구매", "적립"], "all") is True


def test_empty_triggers_always_pass():
    """포함 키워드 미설정 = 게이트 없음 → 항상 통과."""
    assert line_matches_triggers("아무 텍스트", [], "any") is True
    assert line_matches_triggers("아무 텍스트", [], "all") is True


# ── 제외 word/with/except ───────────────────────────────────────────────────
def test_exclude_standalone_word():
    """with 비면 word 단독 존재로 제외 발동."""
    rule = {"word": "불가", "with": [], "except": []}
    assert line_excluded("등급 할인 불가", [rule]) is not None


def test_exclude_requires_with():
    """with 지정 시 word + with 둘 다 있어야 제외."""
    rule = {"word": "할인", "with": ["불가"], "except": []}
    assert line_excluded("등급 할인 불가", [rule]) is not None       # 할인+불가 → 제외
    assert line_excluded("상품 쿠폰 할인", [rule]) is None            # 불가 없음 → 통과


def test_exclude_cancelled_by_except():
    """except 키워드 존재 시 제외 취소."""
    rule = {"word": "불가", "with": [], "except": ["회원"]}
    assert line_excluded("회원 등급 할인 불가", [rule]) is None       # 회원 있음 → 제외 취소


# ── 게이트 통합: "등급 할인 불가" 핵심 케이스 ─────────────────────────────────
def test_grade_discount_vetoed_by_bulga():
    """등급 할인은 포함('등급 할인')엔 맞지만 제외('불가')에 걸려 미적용."""
    benefit = {"name": "등급 할인", "triggers": ["등급 할인"], "match": "any"}
    excludes = [{"word": "불가", "with": [], "except": []}]
    out = gate_benefit(benefit, MOUM_LINES, excludes)
    assert out["applied"] is False
    assert len(out["excluded"]) == 1
    assert "veto" in out["reason"]


def test_coupon_applied():
    """상품 쿠폰은 '쿠폰' 매칭 + 제외 없음 → 적용."""
    benefit = {"name": "상품 쿠폰", "triggers": ["쿠폰"], "match": "any"}
    out = gate_benefit(benefit, MOUM_LINES, [])
    assert out["applied"] is True
    assert "상품 쿠폰" in out["matched_lines"]


def test_any_vs_all_diverge_on_real_lines():
    """동일 혜택·키워드에서 any 는 적용, all 은 미적용 (실데이터 분기 증명)."""
    triggers = ["적립", "캐시백"]
    any_b = {"name": "구매적립", "triggers": triggers, "match": "any"}
    all_b = {"name": "구매적립", "triggers": triggers, "match": "all"}
    assert gate_benefit(any_b, MOUM_LINES, [])["applied"] is True
    assert gate_benefit(all_b, MOUM_LINES, [])["applied"] is False


def test_gate_benefits_batch():
    benefits = [
        {"name": "등급 할인", "triggers": ["등급 할인"], "match": "any"},
        {"name": "상품 쿠폰", "triggers": ["쿠폰"], "match": "any"},
    ]
    excludes = [{"word": "불가", "with": [], "except": []}]
    res = gate_benefits(benefits, MOUM_LINES, excludes)
    by_name = {r["name"]: r["applied"] for r in res}
    assert by_name == {"등급 할인": False, "상품 쿠폰": True}
