from webapp.routes.api_benefits import _musinsa_effective_from_crawl


GUIDE_BENEFITS = [
    {"name": "상품쿠폰", "triggers": ["쿠폰"], "match": "any", "method": "정액(원)"},
    {"name": "등급할인", "triggers": ["등급 할인", "등급할인"], "match": "any", "method": "정액(원)"},
    {"name": "무신사머니 결제 적립", "triggers": ["무신사 머니", "무신사머니"], "match": "any", "method": "정액(원)"},
]
EXCLUDES = [{"word": "불가", "with": [], "except": []}]


def test_fresh_crawl_gates_on_present_lines_only():
    snap = {
        "benefits_ok": True,
        "lines": ["상품 쿠폰", "등급 할인 불가"],
        "amounts": {"상품쿠폰": {"type": "amount", "value": 6145},
                    "등급할인": {"type": "amount", "value": 5000}},
    }
    eff = _musinsa_effective_from_crawl(GUIDE_BENEFITS, EXCLUDES, snap)
    names_on = [it.benefit_name for _k, it in eff if it.enabled]
    assert "상품쿠폰" in names_on
    assert "등급할인" not in names_on


def test_not_fresh_returns_none_no_fallback():
    eff = _musinsa_effective_from_crawl(GUIDE_BENEFITS, EXCLUDES, None)
    assert eff is None


def test_rate_value_over_one_is_normalized_to_fraction():
    # 확장이 5(=5%)를 잘못 보내도 0.05 로 정규화 (500% 차감→매입가0 사고 방지)
    snap = {
        "benefits_ok": True,
        "lines": ["등급 적립 5%"],
        "amounts": {"등급적립": {"type": "rate", "value": 5}},
    }
    guide = [{"name": "등급적립", "triggers": ["등급 적립"], "match": "any", "method": "정률(%)"}]
    eff = _musinsa_effective_from_crawl(guide, [], snap)
    it = [it for _k, it in eff if it.benefit_name == "등급적립"][0]
    assert it.benefit_type == "rate"
    assert it.value == 0.05
    assert it.enabled is True


def test_rate_value_already_fraction_unchanged():
    snap = {
        "benefits_ok": True,
        "lines": ["등급 적립"],
        "amounts": {"등급적립": {"type": "rate", "value": 0.05}},
    }
    guide = [{"name": "등급적립", "triggers": ["등급 적립"], "match": "any", "method": "정률(%)"}]
    eff = _musinsa_effective_from_crawl(guide, [], snap)
    it = [it for _k, it in eff if it.benefit_name == "등급적립"][0]
    assert it.value == 0.05
