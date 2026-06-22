# -*- coding: utf-8 -*-
"""benefit_parse — 라이브 무신사 실데이터(2026-06-22 mou-m.com/products/4046672) 기반."""
from lemouton.pricing.benefit_parse import (
    parse_musinsa_benefit_amounts, has_musinsa_member_signal,
    extract_dynamic_benefits_from_options,
)


def test_extract_ssf_dynamic():
    # SSF parse 결과 옵션 dict (멤버십포인트·기프트포인트)
    opts = [{"color_text": "블랙", "size_text": "250", "price": 111050, "stock": 5,
             "point_rate": 0.005, "point_amount": 555, "gift_point_amount": 11000}]
    dyn = extract_dynamic_benefits_from_options(opts)
    assert dyn["point_rate"] == 0.005
    assert dyn["gift_point_amount"] == 11000


def test_extract_ssg_dynamic():
    opts = [{"price": 119900, "ssg_money_rate": 0.05, "ssg_money_text": "5% 적립"}]
    dyn = extract_dynamic_benefits_from_options(opts)
    assert dyn["ssg_money_rate"] == 0.05
    assert dyn["ssg_money_text"] == "5% 적립"


def test_extract_skips_zero_and_empty():
    opts = [{"price": 1000, "point_rate": 0, "gift_point_amount": None},
            {"price": 2000, "point_rate": 0.01}]
    dyn = extract_dynamic_benefits_from_options(opts)
    # 첫 옵션은 전부 0/None → 스킵, 둘째 옵션 채택
    assert dyn == {"point_rate": 0.01}


def test_extract_empty_when_none():
    assert extract_dynamic_benefits_from_options([{"price": 1000}]) == {}
    assert extract_dynamic_benefits_from_options([]) == {}

# 라이브 무신사 페이지에서 확장과 동일하게 수집한 실제 라인 (표면가 116,900)
LIVE_LINES = [
    "등급 할인 불가",
    "사용가능 쿠폰 없음",
    "적립금 선할인 불가",
    "후기 적립2,500원",
    "96,720원나의 할인가",
    "상품 쿠폰사용가능 쿠폰 없음",
    "구매 적립 (+4,340원)",
    "무신사머니 결제 시 4% 적립",
    "무신사머니 결제 시 4% 적립3,860원",
    "등급 적립(LV.9 블랙다이아몬드 · 4%)",
    "등급 적립(LV.9 블랙다이아몬드 · 4%)4,340원",
    "10,700원 최대 적립LV.9 블랙다이아몬드",
    "무신사페이 × 무신사 삼성카드 10만원 이상 결제 시-12,000원",
]


def test_grade_reward_extracted():
    out = parse_musinsa_benefit_amounts(LIVE_LINES, surface_price=116900)
    assert out['grade_reward_amount'] == 4340


def test_money_reward_extracted():
    out = parse_musinsa_benefit_amounts(LIVE_LINES, surface_price=116900)
    assert out['money_reward_amount'] == 3860
    assert out['money_active'] is True


def test_grade_discount_zero_when_불가():
    out = parse_musinsa_benefit_amounts(LIVE_LINES, surface_price=116900)
    assert out['grade_discount_amount'] == 0


def test_coupon_zero_when_없음():
    out = parse_musinsa_benefit_amounts(LIVE_LINES, surface_price=116900)
    assert out['coupon_amount'] == 0


def test_total_matches_max_accrual():
    # 등급적립 4340 + 무신사머니 3860 + 후기적립(별도) → '최대 적립 10,700' 과 정합
    out = parse_musinsa_benefit_amounts(LIVE_LINES, surface_price=116900)
    assert out['grade_reward_amount'] + out['money_reward_amount'] == 8200  # +후기2500=10700


def test_member_signal_true():
    assert has_musinsa_member_signal(LIVE_LINES) is True


def test_member_signal_false_when_no_amounts():
    # 비로그인: 적립 금액 없는 라인들만
    nolines = ["등급 할인 불가", "사용가능 쿠폰 없음", "역대급 할인 최대 80%"]
    assert has_musinsa_member_signal(nolines) is False
    out = parse_musinsa_benefit_amounts(nolines, surface_price=116900)
    assert out['grade_reward_amount'] == 0 and out['money_reward_amount'] == 0


def test_guard_rejects_absurd_amount():
    # 표면가 대비 40% 초과 비정상 값은 거부(0)
    bad = ["등급 적립(LV.9 · 4%)99,999원"]
    out = parse_musinsa_benefit_amounts(bad, surface_price=100000)
    assert out['grade_reward_amount'] == 0
