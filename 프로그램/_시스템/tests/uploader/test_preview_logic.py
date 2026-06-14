"""_resolve_option_upload 오프라인 단위 테스트 (DB 불필요).

르무통식 정책(스마트 소싱=마진금액, 쿠팡 소싱=지정가, 사입=지정가)으로
재고 기반 우선공급·지정가·옵션 override 가 매트릭스 규칙과 동일하게 동작하는지
결정적으로 검증한다.
"""
import types

from lemouton.uploader.preview import _resolve_option_upload


def _tpl(**kw):
    base = dict(
        boxhero_purchase_price=95000, price_source_priority='template', rounding_unit=100,
        ss_mode_sourcing='amount', ss_rate_sourcing=0.0945, ss_amount_sourcing=5000,
        ss_mode_purchase='fixed', ss_rate_purchase=0.0945, ss_amount_purchase=0,
        ss_external_sale_price=0, ss_boxhero_sale_price=116900,
        ss_fee_rate=0.0945, ss_delivery_fee=0,
        coupang_mode_sourcing='fixed', coupang_rate_sourcing=0.1242, coupang_amount_sourcing=0,
        coupang_mode_purchase='fixed', coupang_rate_purchase=0.1242, coupang_amount_purchase=0,
        coupang_external_sale_price=133900, coupang_boxhero_sale_price=128900,
        coupang_fee_rate=0.1155, coupang_delivery_fee=0,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def _opt(**kw):
    base = dict(
        boxhero_avg_purchase_price=0, purchase_priority='auto',
        src_fixed_ss_active=False, src_fixed_ss_price=0,
        src_fixed_cp_active=False, src_fixed_cp_price=0,
        pur_fixed_ss_active=False, pur_fixed_ss_price=0,
        pur_fixed_cp_active=False, pur_fixed_cp_price=0,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_source_side_when_no_stock():
    # 재고 0 → 소싱 우선. 쿠팡 소싱 지정가 133,900 그대로, 스마트 amount 역산.
    tpl = _tpl()
    r = _resolve_option_upload(_opt(), None, tpl, [{'source_id': 'lemouton', 'crawled_price': 95700}], 0)
    assert r['resolved_side'] == 'source'
    assert r['upload']['cp'] == 133900           # 쿠팡 소싱 지정가
    # 스마트 소싱 amount: (95700+5000)/(1-0.0945) ≈ 111,200 (100원 라운딩)
    assert r['upload']['ss'] == r['src']['ss']
    assert r['pur'] is None


def test_purchase_side_when_stock():
    # 재고≥1 → 사입 우선. 사입 지정가 ss 116,900 / cp 128,900.
    tpl = _tpl()
    r = _resolve_option_upload(_opt(boxhero_avg_purchase_price=90000), None, tpl, [], 3)
    assert r['resolved_side'] == 'purchase'
    assert r['upload']['ss'] == 116900
    assert r['upload']['cp'] == 128900


def test_no_source_and_purchase_blocked_yields_no_price():
    # [2026-06-14 #1 폴백금지] 크롤 소싱가 없음(sources=[]) + 사입가 0(차단) →
    #   메울 폴백(가짜 95000) 금지 → 양쪽 다 None(가격없음). 이 옵션은 crawl_blocked 로
    #   판매 제외 대상이며, 옛 코드는 여기서 95000→133900 가짜 소싱가를 만들어 올렸다(버그).
    tpl = _tpl(boxhero_purchase_price=0)
    r = _resolve_option_upload(_opt(boxhero_avg_purchase_price=0), None, tpl, [], 5)
    assert r['purchase_blocked'] is True
    assert r['pur'] is None
    assert r['src']['ss'] is None and r['src']['cp'] is None   # 크롤가 없음 → 소싱 None
    assert r['upload']['ss'] is None and r['upload']['cp'] is None  # 가짜 95000 폴백 금지


def test_option_fixed_override_source():
    # 옵션별 소싱 지정가 토글 ON → 템플릿 정책보다 우선
    tpl = _tpl()
    r = _resolve_option_upload(
        _opt(src_fixed_cp_active=True, src_fixed_cp_price=140000),
        None, tpl, [{'source_id': 'lemouton', 'crawled_price': 95700}], 0)
    assert r['upload']['cp'] == 140000           # 옵션 override 우선


def test_option_fixed_override_purchase():
    tpl = _tpl()
    r = _resolve_option_upload(
        _opt(boxhero_avg_purchase_price=90000,
             pur_fixed_ss_active=True, pur_fixed_ss_price=120000),
        None, tpl, [], 2)
    assert r['resolved_side'] == 'purchase'
    assert r['upload']['ss'] == 120000


def test_priority_purchase_zero_stock_no_source_yields_no_price():
    # 재고 0 + purchase_priority='purchase' → 우선공급은 purchase 이지만 사입 가격은
    # 재고≥1 에서만 산출 → pur=None. 이때 크롤 소싱가도 없으면(sources=[])
    # [2026-06-14 #1 폴백금지] 가짜 95000 소싱가 산출 금지 → upload None(가격없음).
    tpl = _tpl()
    r = _resolve_option_upload(
        _opt(purchase_priority='purchase', boxhero_avg_purchase_price=90000),
        None, tpl, [], 0)
    assert r['resolved_side'] == 'purchase'
    assert r['pur'] is None                       # 재고 0 → 사입 가격 미산출
    assert r['upload']['cp'] is None              # 크롤 소싱가 없음 → 폴백 금지(가격없음)


def test_real_source_still_falls_back_when_purchase_unavailable():
    # 회귀 가드: 크롤 '실제가'가 있으면 사입 불가 시 소싱가로 정상 산출(폴백금지는 '가짜값'만 막는다).
    tpl = _tpl(boxhero_purchase_price=0)
    r = _resolve_option_upload(
        _opt(boxhero_avg_purchase_price=0), None, tpl,
        [{'source_id': 'lemouton', 'crawled_price': 95700}], 5)
    assert r['purchase_blocked'] is True
    assert r['pur'] is None
    assert r['upload']['cp'] == 133900            # 실제 크롤가 기반 소싱 지정가 — 정상
