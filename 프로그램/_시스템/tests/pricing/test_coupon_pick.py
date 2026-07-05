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

def test_triggers_are_ignored_for_coupons():
    # ★ 2026-07-05 — 적용 키워드(triggers)는 쿠폰 선택에 영향 없음. 제외만 필터.
    b = {'name': '상품 쿠폰', 'triggers': ['배송'], 'match': 'any', 'excludes': []}
    coupons = [{'name': '상품 쿠폰 5%', 'amount': 5000},
               {'name': '배송비 쿠폰', 'amount': 9000}]
    out = pick_best_coupon(coupons, b)
    assert out['amount'] == 9000  # triggers 무시 → 전부 후보 → 최고 선택

def test_default_name_trigger_does_not_reject_all_coupons():
    # ★ 회귀방지: 기본 트리거 '상품 쿠폰'이 실제 쿠폰명(…정기 쿠폰 블랙다이아몬드 등급)을
    #   오탈락시키면 안 됨. 제외 키워드('정기')만 걸러 일반 쿠폰은 살아남아야.
    b = {'name': '상품 쿠폰', 'triggers': ['상품 쿠폰'], 'match': 'any',
         'excludes': ['정기'], 'exclude_match': 'any'}
    coupons = [{'name': '7월 무신사 회원 정기 쿠폰 블랙다이아몬드 등급', 'amount': 6390},
               {'name': '무탠다드 상품쿠폰', 'amount': 5000}]
    out = pick_best_coupon(coupons, b)
    assert out is not None
    assert out['name'] == '무탠다드 상품쿠폰'
    assert out['amount'] == 5000

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
