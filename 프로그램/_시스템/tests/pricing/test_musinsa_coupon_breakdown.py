"""무신사 상품쿠폰 = product_coupon_list 에서 제외 키워드 필터 후 최고 선택."""
from lemouton.pricing.benefit_gate import pick_best_coupon

GRADE = {'name': '상품 쿠폰', 'triggers': [], 'match': 'any',
         'excludes': ['다이아몬드', '플래티넘', '골드', '실버', '브론즈'],
         'exclude_match': 'any'}

def _coupon_amount(dynamic_benefits, benefit, exclude_rules=None):
    """compute_breakdown 이 쓰는 것과 동일 규칙(라이브 배선의 진실 기준)."""
    pcl = dynamic_benefits.get('product_coupon_list')
    if pcl:
        picked = pick_best_coupon(pcl, benefit, exclude_rules)
        return picked['amount'] if picked else 0
    return float(dynamic_benefits.get('coupon_amount') or 0)

def test_grade_excluded_uses_next_best():
    dyn = {'product_coupon_list': [
        {'name': '다이아몬드 등급 쿠폰', 'amount': 12000},
        {'name': '무탠다드 상품쿠폰', 'amount': 5000}]}
    assert _coupon_amount(dyn, GRADE) == 5000

def test_only_grade_gives_zero():
    dyn = {'product_coupon_list': [{'name': '골드 쿠폰', 'amount': 9000}]}
    assert _coupon_amount(dyn, GRADE) == 0

def test_legacy_fallback_when_no_list():
    dyn = {'coupon_amount': 4000}
    assert _coupon_amount(dyn, GRADE) == 4000
