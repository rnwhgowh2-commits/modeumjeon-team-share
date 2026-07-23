# -*- coding: utf-8 -*-
"""ProductDraft → 스스 등록 payload. 순수 함수 — DB·네트워크 없음."""
import json

import pytest

from lemouton.registration.compile_smartstore import compile_smartstore, CompileError


class D:
    """ProductDraft 를 흉내내는 최소 fake (ORM 없이 컴파일러를 검증)."""
    def __init__(self, **kw):
        self.name = kw.get('name', '르무통 스니커즈')
        self.brand = kw.get('brand', '르무통')
        self.sale_price = kw.get('sale_price', 75800)
        self.normal_price = kw.get('normal_price', None)
        self.stock_quantity = kw.get('stock_quantity', 0)
        self.notice_type = kw.get('notice_type', 'SHOES')
        self.notice_json = kw.get('notice_json', json.dumps({
            'material': '천연가죽', 'color': '블랙', 'size': '250',
            'manufacturer': '르무통', 'caution': '직사광선 보관 금지',
            'warranty_policy': '구매일로부터 1년',
            'after_service_director': '르무통 고객센터 02-1234-5678',
        }, ensure_ascii=False))
        self.cdn_images_json = kw.get('cdn_images_json',
                                      json.dumps(['https://shop-phinf.pstatic.net/a.jpg']))
        self.detail_html = kw.get('detail_html', '<p>상세</p>')
        self.options_json = kw.get('options_json', json.dumps([
            {'color': '블랙', 'size': '250', 'stock': 3, 'extra_price': 0, 'sku': 'BK-250'},
        ], ensure_ascii=False))
        self.origin_area_code = kw.get('origin_area_code', '0200037')
        self.importer = kw.get('importer', '')
        self.delivery_fee = kw.get('delivery_fee', 3000)
        self.return_fee = kw.get('return_fee', 5000)
        self.minor_purchasable = kw.get('minor_purchasable', True)
        self.after_service_phone = kw.get('after_service_phone', '02-1234-5678')
        self.after_service_guide = kw.get('after_service_guide', '평일 10-18시 고객센터')


def test_compile_basic_shape():
    body, _ = compile_smartstore(D(), category_code='50000167')
    op = body['originProduct']
    assert op['leafCategoryId'] == '50000167'
    assert op['name'] == '르무통 스니커즈'
    assert op['salePrice'] == 75800
    assert op['detailContent'] == '<p>상세</p>'
    assert body['smartstoreChannelProduct']['naverShoppingRegistration'] is True


def test_compile_keeps_live_verified_detail_attribute_fields():
    """라이브 검증된 payload(create_product.py:81-94)에 있는 필수 필드를 빠뜨리지 않는다.

    minorPurchasable·afterServiceInfo·originAreaInfo 가 없으면 실등록이 거부된다.
    """
    da = compile_smartstore(D(), category_code='1')[0]['originProduct']['detailAttribute']
    assert da['minorPurchasable'] is True
    assert da['afterServiceInfo']['afterServiceTelephoneNumber'] == '02-1234-5678'
    assert da['afterServiceInfo']['afterServiceGuideContent'] == '평일 10-18시 고객센터'
    assert da['originAreaInfo']['originAreaCode'] == '0200037'
    assert da['originAreaInfo']['importer'] == '-', '빈 importer 는 "-" 로 (검증된 동작)'


def test_compile_rejects_missing_after_service_phone():
    """A/S 번호 없으면 가짜 번호로 때우지 말고 막는다 (폴백 금지 원칙).

    기존 모음전 코드(create_product.py:87)는 `or '02-0000-0000'` 로 때우는데,
    그건 실제 판매 상품에 존재하지 않는 번호를 게시하는 것이다.
    """
    with pytest.raises(CompileError) as e:
        compile_smartstore(D(after_service_phone=''), category_code='1')
    assert 'A/S' in str(e.value)


def test_compile_status_type_is_suspension():
    """서버는 statusType 을 무시하고 SALE 로 등록한다. 초안은 등록 후 mark_suspension.

    검증된 payload 와 같은 값을 보낸다 (추측한 saleType 등 미검증 필드는 넣지 않는다).
    """
    op = compile_smartstore(D(), category_code='1')[0]['originProduct']
    assert op['statusType'] == 'SUSPENSION'
    assert 'saleType' not in op
    assert 'customerBenefit' not in op


def test_compile_uses_notice_builder_not_hardcoded_shoes():
    body, _ = compile_smartstore(D(notice_type='WEAR', notice_json=json.dumps({
        'material': '면 100%', 'color': '블랙', 'size': '95',
        'manufacturer': '르무통', 'caution': '단독세탁',
        'warranty_policy': '구매일로부터 1년',
        'after_service_director': '르무통 02-1234-5678',
    }, ensure_ascii=False)), category_code='1')
    n = body['originProduct']['detailAttribute']['productInfoProvidedNotice']
    assert n['productInfoProvidedNoticeType'] == 'WEAR'
    assert 'wear' in n and 'shoes' not in n


def test_compile_includes_option_combinations():
    body, _ = compile_smartstore(D(options_json=json.dumps([
        {'color': '블랙', 'size': '250', 'stock': 3, 'extra_price': 0},
        {'color': '블랙', 'size': '260', 'stock': 1, 'extra_price': 1000},
    ], ensure_ascii=False)), category_code='1')
    oi = body['originProduct']['detailAttribute']['optionInfo']
    assert oi['optionCombinationGroupNames'] == {
        'optionGroupName1': '색상', 'optionGroupName2': '사이즈'}
    assert len(oi['optionCombinations']) == 2


def test_compile_reports_excluded_options_not_silently(D_unused=None):
    """★ 품절·확인불가로 빠진 옵션을 조용히 버리지 않고 돌려준다.

    사용자가 폼에 직접 입력한 행이다. 9개 중 8개가 사라져도 "성공" 만 보이면
    이 저장소가 반복해서 당한 조용한 실패다.
    """
    body, excluded = compile_smartstore(D(options_json=json.dumps([
        {'color': '블랙', 'size': '250', 'stock': 3},
        {'color': '블랙', 'size': '260', 'stock': 0},    # 품절
        {'color': '화이트', 'size': '250', 'stock': -1},  # 확인불가
    ], ensure_ascii=False)), category_code='1')
    assert len(body['originProduct']['detailAttribute']['optionInfo']['optionCombinations']) == 1
    reasons = {(e['color'], e['size']): e['reason'] for e in excluded}
    assert reasons == {('블랙', '260'): '품절', ('화이트', '250'): '확인불가'}


def test_compile_stock_is_sum_of_options():
    body, _ = compile_smartstore(D(options_json=json.dumps([
        {'color': '블랙', 'size': '250', 'stock': 3},
        {'color': '블랙', 'size': '260', 'stock': 1},
    ], ensure_ascii=False)), category_code='1')
    assert body['originProduct']['stockQuantity'] == 4


def test_compile_no_options_uses_flat_stock():
    body, _ = compile_smartstore(D(options_json='[]', stock_quantity=7), category_code='1')
    assert body['originProduct']['stockQuantity'] == 7
    assert 'optionInfo' not in body['originProduct']['detailAttribute']


def test_compile_all_images_not_just_first():
    body, _ = compile_smartstore(D(cdn_images_json=json.dumps([
        'https://shop-phinf.pstatic.net/a.jpg',
        'https://shop-phinf.pstatic.net/b.jpg',
    ])), category_code='1')
    img = body['originProduct']['images']
    assert img['representativeImage'] == {'url': 'https://shop-phinf.pstatic.net/a.jpg'}
    assert img['optionalImages'] == [{'url': 'https://shop-phinf.pstatic.net/b.jpg'}]


def test_compile_rejects_non_cdn_image():
    """스스는 CDN URL 만 받는다 — 외부 URL 을 조용히 보내지 않는다."""
    with pytest.raises(CompileError) as e:
        compile_smartstore(D(cdn_images_json=json.dumps(['https://r2.example.com/a.jpg'])),
                           category_code='1')
    assert 'CDN' in str(e.value)


def test_compile_requires_category():
    with pytest.raises(CompileError):
        compile_smartstore(D(), category_code='')


def test_compile_requires_image():
    with pytest.raises(CompileError):
        compile_smartstore(D(cdn_images_json='[]'), category_code='1')


def test_compile_rejects_zero_price():
    """0원 등록 차단 (price_guard 와 같은 취지)."""
    with pytest.raises(CompileError):
        compile_smartstore(D(sale_price=0), category_code='1')


# ── 경계 하드닝 회귀 (코드리뷰 Finding 1~3) ────────────────────────────────────

def test_compile_malformed_options_json_is_not_silent():
    """★ Finding 1: 손상된 options_json 은 조용히 [](옵션 없음)로 뭉개지 말고 막는다.

    잘려 저장된 옵션 JSON 이 default 로 넘어가면 옵션 있는 상품이 단일 SKU 로
    조용히 등록되던 조용한 실패. 이제 CompileError.
    """
    with pytest.raises(CompileError) as e:
        compile_smartstore(D(options_json='[{"color":"블랙"'), category_code='1')
    assert '손상' in str(e.value)


def test_compile_malformed_images_json_is_not_silent():
    with pytest.raises(CompileError) as e:
        compile_smartstore(D(cdn_images_json='["https://shop-phinf.pstatic.net/a.jpg'),
                           category_code='1')
    assert '손상' in str(e.value)


def test_compile_malformed_notice_json_is_not_silent():
    with pytest.raises(CompileError) as e:
        compile_smartstore(D(notice_json='{"material":'), category_code='1')
    assert '손상' in str(e.value)


def test_compile_coerces_comma_and_decimal_price():
    """★ Finding 2: '75,800'·'75800.0' 는 500 이 아니라 coerce 되어 통과한다."""
    b1, _ = compile_smartstore(D(sale_price='75,800'), category_code='1')
    assert b1['originProduct']['salePrice'] == 75800
    b2, _ = compile_smartstore(D(sale_price='75800.0'), category_code='1')
    assert b2['originProduct']['salePrice'] == 75800


def test_compile_rejects_unparseable_price():
    with pytest.raises(CompileError):
        compile_smartstore(D(sale_price='abc'), category_code='1')


def test_compile_rejects_non_string_image_elements():
    """★ Finding 3: [null]·[123] 은 500(TypeError) 대신 CompileError."""
    with pytest.raises(CompileError):
        compile_smartstore(D(cdn_images_json='[null]'), category_code='1')
    with pytest.raises(CompileError):
        compile_smartstore(D(cdn_images_json='[123]'), category_code='1')


def test_compile_rejects_missing_after_service_guide():
    """A/S 안내도 폴백 없이 막는다 (번호만 테스트되던 빈틈)."""
    with pytest.raises(CompileError) as e:
        compile_smartstore(D(after_service_guide=''), category_code='1')
    assert 'A/S' in str(e.value)


def test_compile_literal_null_json_is_treated_as_empty_not_500():
    """★ Finding A: json.loads('null')==None. 문자열 'null' 은 비어있지 않아 파싱을
    통과하지만, 빈 필드와 똑같이 다뤄야 한다.

    notice_json='null' → build_notice(type, None) → None.get() → AttributeError 가
    except NoticeError 를 통과해 500 이 되던 것. 이제 빈 dict 취급 → 고시 필수누락 →
    CompileError (AttributeError 아님).
    """
    with pytest.raises(CompileError):
        compile_smartstore(D(notice_json='null'), category_code='1')
    # options_json·cdn_images_json 의 'null' 도 조용히 안전(빈 것 취급)한지 확인.
    with pytest.raises(CompileError):
        compile_smartstore(D(cdn_images_json='null'), category_code='1')  # 이미지 없음
    body, _ = compile_smartstore(D(options_json='null', stock_quantity=5), category_code='1')
    assert body['originProduct']['stockQuantity'] == 5  # 옵션 없음 → 평면 재고
    assert 'optionInfo' not in body['originProduct']['detailAttribute']


def test_compile_string_zero_normal_price_omits_key():
    """★ Finding B: '0'/'0.0' 은 원시값이 truthy 라 normalPrice: 0 이 나가던 것.
    코어스 후 값으로 판단해 키를 아예 뺀다.
    """
    body, _ = compile_smartstore(D(normal_price='0'), category_code='1')
    assert 'normalPrice' not in body['originProduct']
    body2, _ = compile_smartstore(D(normal_price='0.0'), category_code='1')
    assert 'normalPrice' not in body2['originProduct']
    # 진짜 정가는 그대로 실린다.
    body3, _ = compile_smartstore(D(normal_price='89,000'), category_code='1')
    assert body3['originProduct']['normalPrice'] == 89000


def test_require_cdn_images_false_compiles_without_images():
    """게이트 앞 예비 컴파일 — CDN 이미지가 없어도 A/S·옵션 오류를 잡고 통과한다.

    이미지 업로드는 라이브 호출이라 게이트 뒤에서만 도는데, compile-before-gate 가
    이미지를 필수로 요구하면 게이트 OFF 에서 'CDN 없음' 으로 먼저 실패해 '실등록 꺼짐'
    메시지에 닿지 못한다. False 면 이미지 검사·images 키를 생략한다.
    """
    body, _ = compile_smartstore(D(cdn_images_json='[]'), category_code='1',
                                 require_cdn_images=False)
    assert 'images' not in body['originProduct'], '예비 컴파일 body 엔 images 를 넣지 않는다'
    # 그래도 A/S 누락 같은 비이미지 오류는 여전히 잡는다.
    with pytest.raises(CompileError):
        compile_smartstore(D(cdn_images_json='[]', after_service_phone=''),
                           category_code='1', require_cdn_images=False)


def test_require_cdn_images_true_is_default_and_still_requires():
    """기본값 True — 현행 동작 그대로. 이미지 없으면 CompileError, 있으면 images 블록 포함."""
    with pytest.raises(CompileError):
        compile_smartstore(D(cdn_images_json='[]'), category_code='1')  # 기본 True
    body, _ = compile_smartstore(D(), category_code='1')  # D 기본 cdn_images 는 CDN URL
    assert 'images' in body['originProduct']
    assert body['originProduct']['images']['representativeImage']['url']


# ── [2026-07-23 리뷰 I2] 평면 재고 3상태를 뭉개지 않는다 ────────────────────

def test_평면재고_확인불가는_거짓_ready_로_통과하지_않는다():
    """-1(확인불가)은 「있다」가 아니다. 다른 5마켓은 전부 막는데 스스만 통과했다."""
    with pytest.raises(CompileError) as e:
        compile_smartstore(D(options_json='[]', stock_quantity=-1), category_code='1')
    assert '확인' in str(e.value)


def test_평면재고_미크롤을_품절로_뭉개지_않는다():
    """None(미크롤)을 0(품절)으로 바꾸면 소싱처에 확인하러 갈 근거를 잃는다."""
    with pytest.raises(CompileError) as e:
        compile_smartstore(D(options_json='[]', stock_quantity=None), category_code='1')
    assert '크롤' in str(e.value)


def test_평면재고_0_은_품절이라는_뜻_있는_값이라_통과한다():
    """스스는 재고 0 등록이 가능하다 — 0 까지 막으면 정상 흐름이 끊긴다."""
    body, _ = compile_smartstore(D(options_json='[]', stock_quantity=0), category_code='1')
    assert body['originProduct']['stockQuantity'] == 0
