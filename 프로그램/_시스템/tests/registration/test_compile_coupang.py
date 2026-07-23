# -*- coding: utf-8 -*-
"""ProductDraft → 쿠팡 등록 payload. 순수 함수."""
import json

import pytest

from lemouton.registration.compile_coupang import compile_coupang, CompileError


class D:
    def __init__(self, **kw):
        self.name = kw.get('name', '르무통 스니커즈')
        self.brand = kw.get('brand', '르무통')
        self.sale_price = kw.get('sale_price', 75800)
        self.stock_quantity = kw.get('stock_quantity', 0)
        self.detail_html = kw.get('detail_html', '<p>상세</p>')
        self.cdn_images_json = kw.get('cdn_images_json', '[]')
        self.images_json = kw.get('images_json', json.dumps(['https://r2.example.com/a.jpg']))
        self.options_json = kw.get('options_json', json.dumps([
            {'color': '블랙', 'size': '250', 'stock': 3, 'extra_price': 0, 'sku': 'BK-250'},
        ], ensure_ascii=False))
        self.delivery_fee = kw.get('delivery_fee', 3000)
        self.return_fee = kw.get('return_fee', 5000)


VENDOR = {'vendor_id': 'A00012345', 'vendor_user_id': 'lemouton_wing',
          'return_center_code': 'RC1', 'return_charge_name': '르무통 반품지',
          'return_zip': '06236', 'return_address': '서울시 강남구',
          'return_address_detail': '1층', 'return_phone': '02-0000-0000',
          'outbound_place_code': 74010}


def test_compile_basic_shape():
    p, _ = compile_coupang(D(), category_code=63951, vendor=VENDOR)
    assert p['displayCategoryCode'] == 63951
    assert p['sellerProductName'] == '르무통 스니커즈'
    assert p['brand'] == '르무통'
    assert p['requested'] is False, '초안 등록 — 승인요청은 사람이 확인 후'
    assert p['vendorId'] == 'A00012345'


def test_compile_uses_public_url_not_cdn():
    """쿠팡은 공개 URL(R2)을 그대로 받는다 — 네이버 CDN 업로드가 필요 없다."""
    p, _ = compile_coupang(D(), category_code=1, vendor=VENDOR)
    assert p['items'][0]['images'][0]['vendorPath'] == 'https://r2.example.com/a.jpg'


def test_compile_items_from_options():
    p, _ = compile_coupang(D(options_json=json.dumps([
        {'color': '블랙', 'size': '250', 'stock': 3, 'extra_price': 0},
        {'color': '블랙', 'size': '260', 'stock': 1, 'extra_price': 1000},
    ], ensure_ascii=False)), category_code=1, vendor=VENDOR)
    assert len(p['items']) == 2
    assert p['items'][1]['salePrice'] == 76800


def test_compile_requires_category():
    with pytest.raises(CompileError):
        compile_coupang(D(), category_code=0, vendor=VENDOR)


def test_compile_requires_image():
    with pytest.raises(CompileError):
        compile_coupang(D(images_json='[]'), category_code=1, vendor=VENDOR)


def test_compile_rejects_zero_price():
    with pytest.raises(CompileError):
        compile_coupang(D(sale_price=0), category_code=1, vendor=VENDOR)


def test_compile_requires_vendor_id():
    with pytest.raises(CompileError):
        compile_coupang(D(), category_code=1, vendor={})


# ── compile_common 경계 하드닝 (스스와 동일 — 세 버그가 복제되지 않았는지) ──

def test_compile_corrupt_options_json_raises_not_silent():
    """손상된 options_json 은 조용히 '옵션없음' 으로 넘어가지 않는다 (Finding 1)."""
    with pytest.raises(CompileError) as e:
        compile_coupang(D(options_json='{bad'), category_code=1, vendor=VENDOR)
    assert '손상' in str(e.value)


def test_compile_price_with_comma_coerced():
    """'75,800'(엑셀 붙여넣기)은 500 이 아니라 정상 처리 (Finding 2)."""
    p, _ = compile_coupang(D(sale_price='75,800'), category_code=1, vendor=VENDOR)
    assert p['items'][0]['salePrice'] == 75800


def test_compile_price_garbage_raises():
    with pytest.raises(CompileError):
        compile_coupang(D(sale_price='abc'), category_code=1, vendor=VENDOR)


def test_compile_non_string_image_raises():
    """[null]·[123] 같은 원소는 500 대신 CompileError (Finding 3)."""
    with pytest.raises(CompileError):
        compile_coupang(D(images_json='[null]'), category_code=1, vendor=VENDOR)
    with pytest.raises(CompileError):
        compile_coupang(D(images_json='[123]'), category_code=1, vendor=VENDOR)


# ── 라이브 createProduct 필수필드 회귀 (green 테스트가 못 잡는 400 방지) ──

def test_payload_matches_live_build_payload_required_fields():
    """라이브 검증된 coupang.py::_build_payload 가 내보내는 필수 필드가 빠지지 않았는지.

    '새로 만들지 말고 검증된 형제를 diff 하라' 를 강제한다 — 처음엔 6개 top-level +
    item.maximumBuyForPersonPeriod 가 통째로 빠져 400 을 냈다.
    """
    p, _ = compile_coupang(D(), category_code=1, vendor=VENDOR)
    # 하드코딩 목록 대신 지도(SOT)에서 [필수] 필드를 파생 — 스펙과 드리프트 못 하게.
    required_top, required_item = _required_fields_from_map()
    missing_top = required_top - set(p)
    missing_item = required_item - set(p['items'][0])
    assert not missing_top, f'라이브 필수 top-level 누락: {missing_top}'
    assert not missing_item, f'라이브 필수 item 누락: {missing_item}'
    assert 'placeAddressZipCode' not in p, 'createProduct 필드가 아님 — 제거됐어야'


def _required_fields_from_map():
    """marketplace_api_map.json 의 coupang create-product 에서 [필수] 필드 집합을 뽑는다.

    지도가 없는 환경(테스트 격리)에서는 skip — 지도는 라이브 저장소에만 있다.
    """
    import io
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, 'webapp', 'data', 'marketplace_api_map.json')
    if not os.path.exists(path):
        pytest.skip('marketplace_api_map.json 없음 (지도 미배치 환경)')
    j = json.load(io.open(path, encoding='utf-8'))
    api = next((x for x in j['apis']
                if x.get('id') == 'coupang.products.product-creation'), None)
    if api is None:
        pytest.skip('coupang create-product api 항목 없음')
    top, item = set(), set()
    for it in api.get('fields', []):
        if '[필수]' not in (it.get('meaning') or ''):
            continue
        k = it.get('key', '').replace('요청.', '')
        if k in ('code', 'message'):
            continue
        if k.startswith('items.') and k.count('.') == 1:
            item.add(k.split('.')[1])
        elif k.count('.') == 0:
            top.add(k)
    return top, item




def test_item_numeric_fields_are_strings_like_live_payload():
    """item 수량계열은 문자열(int 로 보내면 400) + maximumBuyForPersonPeriod 존재."""
    p, _ = compile_coupang(D(), category_code=1, vendor=VENDOR)
    it = p['items'][0]
    assert it['maximumBuyForPersonPeriod'] == '1'
    assert isinstance(it['maximumBuyCount'], str)
    assert isinstance(it['maximumBuyForPerson'], str)
    assert isinstance(it['outboundShippingTimeDay'], str)
    assert isinstance(it['unitCount'], str)
    assert isinstance(it['pccNeeded'], str)


def test_return_charge_name_is_name_not_center_code():
    """returnChargeName 은 반품지'명' — center code 를 넣으면 라이브에 잘못된 데이터."""
    p, _ = compile_coupang(D(), category_code=1, vendor=VENDOR)
    assert p['returnChargeName'] == '르무통 반품지'
    assert p['returnChargeName'] != VENDOR['return_center_code']


def test_flat_no_option_has_at_least_one_attribute():
    """옵션 없는 단일상품도 items.attributes 는 비면 안 된다(≥1 필수)."""
    p, _ = compile_coupang(D(options_json='[]', stock_quantity=5),
                           category_code=1, vendor=VENDOR)
    assert len(p['items']) == 1
    assert len(p['items'][0]['attributes']) >= 1


# ══ 반품지 계정정보 전수 검증 (2026-07-23 리뷰 C1·C2·M4) ═══════════════════
#  금전 경로다 — 반품지 한 칸이 비면 반품이 엉뚱한 곳으로 가거나 접수 자체가 안 된다.
#  전에는 vendor_id 하나만 보고 나머지를 vendor.get(k, '') 로 흘려, 한 칸만 저장해도
#  빈 반품지·빈 전화로 등록 payload 가 나갔다.

def _v(**over):
    v = dict(VENDOR)
    v.update(over)
    return v


def test_필수칸이_하나라도_비면_이름을_대며_막는다():
    from lemouton.registration.compile_coupang import VENDOR_KEY_LABELS
    for key, label in VENDOR_KEY_LABELS.items():
        with pytest.raises(CompileError) as e:
            compile_coupang(D(), category_code=1, vendor=_v(**{key: ''}))
        assert label in str(e.value), f'{key} 가 비었는데 이름({label})을 안 댄다'


def test_필수칸이_공백문자만_있어도_빈칸으로_본다():
    with pytest.raises(CompileError) as e:
        compile_coupang(D(), category_code=1, vendor=_v(return_address='   '))
    assert '반품지 주소' in str(e.value)


def test_한_칸만_저장된_부분값은_통과하지_못한다():
    """vendor_user_id 만 저장한 상태 — 예전엔 ready 로 통과했다."""
    with pytest.raises(CompileError) as e:
        compile_coupang(D(), category_code=1,
                        vendor={'vendor_id': 'A00012345', 'vendor_user_id': 'wing'})
    msg = str(e.value)
    assert '반품지 코드' in msg and '출고지 코드' in msg


def test_전부_채우면_통과한다():
    p, _ = compile_coupang(D(), category_code=1, vendor=_v())
    assert p['vendorId'] == 'A00012345'


def test_출고지_코드는_문자열로_와도_숫자로_나간다():
    """DB 컬럼은 String, logistics._s() 도 항상 str — 라이브 검증된 경로는 int."""
    p, _ = compile_coupang(D(), category_code=1, vendor=_v(outbound_place_code='74010'))
    assert p['outboundShippingPlaceCode'] == 74010
    assert isinstance(p['outboundShippingPlaceCode'], int)


def test_출고지_코드가_비면_0으로_뭉개지_않고_막는다():
    with pytest.raises(CompileError) as e:
        compile_coupang(D(), category_code=1, vendor=_v(outbound_place_code=''))
    assert '출고지 코드' in str(e.value)


def test_출고지_코드가_0이면_막는다():
    """0 은 유효한 출고지 코드가 아니다 — 0 으로 등록되면 출고지가 붙지 않는다."""
    with pytest.raises(CompileError) as e:
        compile_coupang(D(), category_code=1, vendor=_v(outbound_place_code='0'))
    assert '출고지 코드' in str(e.value)


def test_우편번호_형식_최소검증():
    for bad in ('123', '서울시', '1234567890'):
        with pytest.raises(CompileError) as e:
            compile_coupang(D(), category_code=1, vendor=_v(return_zip=bad))
        assert '우편번호' in str(e.value), bad
    # 신(5자리)·구(6자리) 둘 다 통과
    for ok in ('06236', '135-090'):
        compile_coupang(D(), category_code=1, vendor=_v(return_zip=ok))


def test_반품지_전화_형식_최소검증():
    with pytest.raises(CompileError) as e:
        compile_coupang(D(), category_code=1, vendor=_v(return_phone='없음'))
    assert '전화' in str(e.value)
    compile_coupang(D(), category_code=1, vendor=_v(return_phone='010-1234-5678'))
