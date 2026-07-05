from lemouton.pricing.benefit_gate import pick_best_coupon

GRADE = {
    'name': '상품 쿠폰', 'triggers': [], 'match': 'any',
    'excludes': ['다이아몬드', '플래티넘', '골드', '실버', '브론즈'],
    'exclude_match': 'any',
}

def test_excludes_grade_keeps_next_best():
    coupons = [{'name': '다이아몬드 등급 쿠폰', 'amount': 12000},
               {'name': '무탠다드 상품쿠폰', 'amount': 5000}]
    out = pick_best_coupon(coupons, GRADE)
    assert out is not None
    assert out['amount'] == 5000
    assert out['name'] == '무탠다드 상품쿠폰'

def test_all_excluded_returns_none():
    coupons = [{'name': '다이아몬드 쿠폰', 'amount': 12000},
               {'name': '골드 쿠폰', 'amount': 8000}]
    assert pick_best_coupon(coupons, GRADE) is None

def test_no_excludes_picks_highest():
    b = {'name': '상품 쿠폰', 'triggers': [], 'excludes': []}
    coupons = [{'name': 'A', 'amount': 3000}, {'name': 'B', 'amount': 7000}]
    assert pick_best_coupon(coupons, b)['amount'] == 7000

def test_triggers_filter_only_matching():
    b = {'name': '상품 쿠폰', 'triggers': ['상품'], 'match': 'any', 'excludes': []}
    coupons = [{'name': '상품 쿠폰 5%', 'amount': 5000},
               {'name': '배송비 쿠폰', 'amount': 9000}]
    out = pick_best_coupon(coupons, b)
    assert out['name'] == '상품 쿠폰 5%'

def test_empty_list_returns_none():
    assert pick_best_coupon([], GRADE) is None

def test_zero_or_negative_amount_skipped():
    assert pick_best_coupon([{'name': '무탠다드 상품쿠폰', 'amount': 0}], GRADE) is None

def test_common_exclude_rules_applied():
    coupons = [{'name': '정기 쿠폰', 'amount': 9000},
               {'name': '무탠다드 상품쿠폰', 'amount': 5000}]
    out = pick_best_coupon(coupons, {'name': '상품 쿠폰', 'excludes': []},
                           exclude_rules=[{'word': '정기'}])
    assert out['name'] == '무탠다드 상품쿠폰'
