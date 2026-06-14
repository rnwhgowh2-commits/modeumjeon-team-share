from webapp.routes.api_benefits import _musinsa_effective_from_crawl
from lemouton.pricing.final_price import compute_final_price

# 가이드(사용자 정의 2026-06-14):
#   후기적립 = 고정 500원(텍스트후기만, 사진후기 2,500 제외).
#   결제적립 트리거 = '무신사머니 결제' — '무신사 삼성카드 결제 시 무신사머니 포인트'(수집용)는 제외,
#     오직 '무신사머니 결제 시 X% 적립'만 계산에 사용. 결제적립 없으면 현대카드 2.73% fallback.
GUIDE = [
    {"name": "등급 할인", "triggers": ["등급 할인"], "match": "any", "apply": "preapplied", "value": None},
    {"name": "상품 쿠폰", "triggers": ["상품 쿠폰"], "match": "any", "apply": "preapplied", "value": None},
    {"name": "구매적립", "triggers": ["구매 적립"], "match": "any", "apply": "accrue", "value": None},
    {"name": "후기 적립", "triggers": ["후기 적립"], "match": "any", "apply": "accrue", "value": 500},
    {"name": "결제 적립", "triggers": ["무신사머니 결제"], "match": "any", "apply": "payment", "value": None},
]
EXCL = [{"word": "등급 할인 불가"}, {"word": "쿠폰 없음"}, {"word": "적용 안함"}, {"word": "정기"}]

ACC1 = ["등급 할인 불가", "상품 쿠폰사용가능 쿠폰 없음", "보유 적립금 사용 (현재 1,055,728원 보유)-8,600원", "구매 적립 (+4,570원)적립금 선할인 불가4,570원", "결제수단 즉시할인카카오페이 × 페이머니 10만원 이상 결제 시-4,000원적용 안함", "등급 적립(LV.9 블랙다이아몬드 · 4%)4,570원", "후기 적립2,500원", "무신사 삼성카드 결제 시 무신사머니 포인트 10% 적립 예상9,499원", "무신사머니 결제 시 4% 적립4,400원", "무신사머니 첫 결제 시 10% 추가 적립"]
ACC2 = ["등급 할인 불가", "상품 쿠폰사용가능 쿠폰 없음", "보유 적립금 사용 (현재 31,903원 보유)-8,600원", "구매 적립 (+3,420원)적립금 선할인 불가3,420원", "결제수단 즉시할인카카오페이 × 페이머니 10만원 이상 결제 시-4,000원적용 안함", "등급 적립(LV.8 다이아몬드 · 3%)3,420원", "후기 적립2,500원", "무신사 삼성카드 결제 시 무신사머니 포인트 10% 적립11,030원", "무신사머니 결제 시 3.5% 적립3,850원", "무신사 삼성카드로 첫 결제 할인(결제금액 31,000원 이상 사용 가능)-30,000원"]
GUEST = ["2,500원 최대 적립", "첫 구매 20% 쿠폰 받으러 가기"]

# 결합행: '무신사머니 결제 시'(클린) 라인이 별도로 있고, 삼성카드 결합행은 트리거 미매칭으로 제외.
ACC2_COMBINED = ["등급 할인 불가", "상품 쿠폰사용가능 쿠폰 없음", "보유 적립금 사용 (현재 31,903원 보유)-8,600원",
    "구매 적립 (+3,420원)적립금 선할인 불가3,420원",
    "기본 적립등급 적립(LV.8 다이아몬드 · 3%)3,420원후기 적립2,500원",
    "무신사 삼성카드 결제 시 무신사머니 포인트 10% 적립11,030원",
    "무신사머니 결제 시 3.5% 적립3,850원",
    "결제수단 적립무신사 삼성카드 결제 시 무신사머니 포인트 10% 적립11,030원무신사머니 결제 시 3.5% 적립3,850원적용 안함",
    "결제수단 즉시할인카카오페이 × 페이머니 10만원 이상 결제 시-4,000원적용 안함"]

HYUNDAI = "현대카드 2.73% (결제 fallback)"


def _enabled(eff):
    return {it.benefit_name: it.value for _k, it in eff if it.enabled}


def test_acc1_payment_uses_musinsa_money_not_samsung_card():
    on = _enabled(_musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": ACC1}))
    # 결제적립 = 무신사머니 결제 4% = 4,400 (삼성카드 라인 9,499 아님). 후기적립=고정500.
    assert on == {"구매적립": 4570, "후기 적립": 500, "결제 적립": 4400}


def test_acc1_final_price():
    eff = _musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": ACC1})
    res = compute_final_price(122900, eff, base_override=122900)
    assert res["final_price"] == 113430  # 122900 - 4570 - 500 - 4400


def test_acc2_payment_uses_musinsa_money():
    on = _enabled(_musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": ACC2}))
    # 결제적립 = 무신사머니 결제 3.5% = 3,850 (삼성 11,030 / 첫결제 30,000 제외)
    assert on == {"구매적립": 3420, "후기 적립": 500, "결제 적립": 3850}


def test_acc2_final_price():
    eff = _musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": ACC2})
    res = compute_final_price(122900, eff, base_override=122900)
    assert res["final_price"] == 115130  # 122900 - 3420 - 500 - 3850


def test_combined_row_uses_fixed_review_and_musinsa_money():
    on = _enabled(_musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": ACC2_COMBINED}))
    assert on == {"구매적립": 3420, "후기 적립": 500, "결제 적립": 3850}


def test_combined_row_final_price():
    eff = _musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": ACC2_COMBINED})
    res = compute_final_price(122900, eff, base_override=122900)
    assert res["final_price"] == 115130


def test_guest_hyundai_card_fallback_when_no_musinsa_money():
    on = _enabled(_musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": GUEST}))
    assert on == {HYUNDAI: 0.0273}


def test_guest_final_price_hyundai():
    eff = _musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": GUEST})
    res = compute_final_price(122900, eff, base_override=122900)
    assert res["final_price"] == 119545  # 122900 - int(122900*0.0273)=3355


def test_acc1_no_hyundai_when_musinsa_money_present():
    on = _enabled(_musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": ACC1}))
    assert HYUNDAI not in on


def test_not_fresh_returns_none_no_fallback():
    assert _musinsa_effective_from_crawl(GUIDE, EXCL, None) is None
