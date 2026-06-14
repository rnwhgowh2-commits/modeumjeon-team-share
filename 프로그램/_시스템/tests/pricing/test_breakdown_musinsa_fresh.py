from webapp.routes.api_benefits import _musinsa_effective_from_crawl
from lemouton.pricing.final_price import compute_final_price

GUIDE = [
    {"name": "등급 할인", "triggers": ["등급 할인"], "match": "any", "apply": "preapplied"},
    {"name": "상품 쿠폰", "triggers": ["상품 쿠폰"], "match": "any", "apply": "preapplied"},
    {"name": "구매적립", "triggers": ["구매 적립"], "match": "any", "apply": "accrue"},
    {"name": "후기 적립", "triggers": ["후기 적립"], "match": "any", "apply": "accrue"},
    {"name": "결제 적립", "triggers": ["무신사머니"], "match": "any", "apply": "payment"},
]
EXCL = [{"word": "등급 할인 불가"}, {"word": "쿠폰 없음"}, {"word": "적용 안함"}, {"word": "정기"}]

ACC1 = ["등급 할인 불가", "상품 쿠폰사용가능 쿠폰 없음", "보유 적립금 사용 (현재 1,055,728원 보유)-8,600원", "구매 적립 (+4,570원)적립금 선할인 불가4,570원", "결제수단 즉시할인카카오페이 × 페이머니 10만원 이상 결제 시-4,000원적용 안함", "등급 적립(LV.9 블랙다이아몬드 · 4%)4,570원", "후기 적립2,500원", "무신사 삼성카드 결제 시 무신사머니 포인트 10% 적립 예상9,499원", "무신사머니 결제 시 4% 적립4,400원", "무신사머니 첫 결제 시 10% 추가 적립"]
ACC2 = ["등급 할인 불가", "상품 쿠폰사용가능 쿠폰 없음", "보유 적립금 사용 (현재 31,903원 보유)-8,600원", "구매 적립 (+3,420원)적립금 선할인 불가3,420원", "결제수단 즉시할인카카오페이 × 페이머니 10만원 이상 결제 시-4,000원적용 안함", "등급 적립(LV.8 다이아몬드 · 3%)3,420원", "후기 적립2,500원", "무신사 삼성카드 결제 시 무신사머니 포인트 10% 적립11,030원", "무신사머니 결제 시 3.5% 적립3,850원", "무신사 삼성카드로 첫 결제 할인(결제금액 31,000원 이상 사용 가능)-30,000원"]
GUEST = ["2,500원 최대 적립", "첫 구매 20% 쿠폰 받으러 가기"]


def _enabled(eff):
    return {it.benefit_name: it.value for _k, it in eff if it.enabled}


def test_acc1_amounts_from_lines():
    on = _enabled(_musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": ACC1}))
    assert on == {"구매적립": 4570, "후기 적립": 2500, "결제 적립": 9499}


def test_acc1_final_price():
    eff = _musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": ACC1})
    res = compute_final_price(122900, eff, base_override=122900)
    assert res["final_price"] == 106331


def test_acc2_first_purchase_line_does_not_pollute_payment():
    on = _enabled(_musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": ACC2}))
    # 결제 적립 = 11,030 (삼성 무신사머니), NOT 30,000/31,000 (첫결제 할인 라인 오매칭 방지)
    assert on == {"구매적립": 3420, "후기 적립": 2500, "결제 적립": 11030}


def test_acc2_final_price():
    eff = _musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": ACC2})
    res = compute_final_price(122900, eff, base_override=122900)
    assert res["final_price"] == 105950


def test_guest_all_off():
    on = _enabled(_musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": GUEST}))
    assert on == {}


def test_guest_final_price_is_surface():
    eff = _musinsa_effective_from_crawl(GUIDE, EXCL, {"lines": GUEST})
    res = compute_final_price(122900, eff, base_override=122900)
    assert res["final_price"] == 122900


def test_not_fresh_returns_none_no_fallback():
    assert _musinsa_effective_from_crawl(GUIDE, EXCL, None) is None
