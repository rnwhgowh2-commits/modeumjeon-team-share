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
    required_top = {
        'freeShipOverAmount', 'deliveryChargeOnReturn', 'unionDeliveryType',
        'vendorUserId', 'requiredDocuments', 'extraInfoMessage',
        'displayCategoryCode', 'sellerProductName', 'vendorId',
        'deliveryCompanyCode', 'returnChargeName', 'returnZipCode', 'items',
    }
    missing = required_top - set(p)
    assert not missing, f'라이브 필수 top-level 필드 누락: {missing}'
    assert 'placeAddressZipCode' not in p, 'createProduct 필드가 아님 — 제거됐어야'


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
