# -*- coding: utf-8 -*-
"""ProductDraft → 쿠팡 등록 payload (순수 함수).

기존 lemouton/registration/coupang.py::_build_payload 는 bundle + Option ORM 을 받고
market_visible_coupang 로 거른다. 드래프트엔 그 개념이 없어 새로 만든다.
하드코딩 규약(requested=False 초안, CJGLS, 판매기간)은 기존과 맞춘다.

쿠팡은 공개 URL(R2 등)을 그대로 받는다 — 스스와 달리 CDN 업로드가 필요 없다.
"""
import json

from lemouton.registration.options import build_coupang_items, OptionError
# ★ 스스 컴파일러(Task 6)가 자유형 JSON 경계 버그 3종을 겪고 compile_common 으로 뽑았다.
#   쿠팡도 같은 경계를 지나므로 그대로 상속한다 — CompileError·loads_json·coerce_int·
#   require_category 를 재구현하지 말 것(그러면 세 버그가 복제된다).
from lemouton.registration.compile_common import (
    CompileError, loads_json, coerce_int, require_category,
)

_SALE_STARTED_AT = '2026-01-01T00:00:00'
_SALE_ENDED_AT = '2099-12-31T23:59:59'
_DELIVERY_COMPANY = 'CJGLS'


def compile_coupang(draft, *, category_code: int, vendor: dict):
    """ProductDraft → (쿠팡 상품 생성 payload, 제외된 옵션 목록).

    excluded 를 함께 돌려주는 이유는 compile_smartstore 와 같다 — 사용자가 입력한
    옵션이 조용히 사라지지 않게.

    Args:
        vendor: 계정별 고정값 — vendor_id, return_center_code, return_zip,
                return_address, return_address_detail, return_phone, outbound_place_code

    Raises:
        CompileError: 카테고리·이미지·판매가·vendor_id 누락 등
    """
    require_category(category_code, what='쿠팡 displayCategoryCode')
    cat_code = coerce_int(category_code, '쿠팡 displayCategoryCode')
    if not vendor.get('vendor_id'):
        raise CompileError('쿠팡 vendorId 가 필요합니다 — 계정 설정을 확인하세요.')

    sale_price = coerce_int(draft.sale_price, '판매가') or 0
    delivery_fee = coerce_int(draft.delivery_fee, '배송비') or 0
    return_fee = coerce_int(draft.return_fee, '반품비') or 0
    if sale_price <= 0:
        raise CompileError(f'판매가가 0 이하입니다({sale_price}) — 등록을 막습니다.')

    images = loads_json(draft.images_json, [], what='이미지')
    if not isinstance(images, list) or not images:
        raise CompileError('대표 이미지가 없습니다.')
    # 쿠팡은 공개 URL(R2 등)을 그대로 받는다 — CDN 호스트 제약은 없지만, 원소가
    # 문자열인지는 검사한다(스스 Finding 3 과 같은 부류: [null]·[123] 이면 500).
    if not isinstance(images[0], str) or not images[0].strip():
        raise CompileError(f'이미지 URL 이 문자열이 아닙니다(손상된 데이터): {images[0]!r}')

    opts = loads_json(draft.options_json, [], what='옵션')
    excluded = []
    if opts:
        # OptionError = 상위 예외 (NoSellableOption·OptionValueInvalid 둘 다).
        try:
            items, excluded = build_coupang_items(opts, sale_price=sale_price,
                                                  image_url=images[0])
        except OptionError as e:
            raise CompileError(f'옵션 문제 — {e}') from e
    else:
        stock = coerce_int(draft.stock_quantity, '재고') or 0
        if stock <= 0:
            raise CompileError('옵션도 없고 재고도 0입니다 — 등록할 것이 없습니다.')
        items = [{
            'itemName': draft.name,
            'originalPrice': sale_price,
            'salePrice': sale_price,
            'maximumBuyCount': stock,
            'externalVendorSku': '',
            'images': [{'imageOrder': 0, 'imageType': 'REPRESENTATION',
                        'vendorPath': images[0]}],
            'attributes': [],
        }]

    for it in items:
        it.update({
            'contents': [{'contentsType': 'HTML',
                          'contentDetails': [{'content': draft.detail_html or '',
                                              'detailType': 'TEXT'}]}],
            'notices': [],   # Phase 2 — 쿠팡 noticeCategories 매핑
            'maximumBuyForPerson': 0,
            'outboundShippingTimeDay': 3,
            'unitCount': 1,
            'adultOnly': 'EVERYONE',
            'taxType': 'TAX',
            'parallelImported': 'NOT_PARALLEL_IMPORTED',
            'overseasPurchased': 'NOT_OVERSEAS_PURCHASED',
            'pccNeeded': False,
        })

    payload = {
        'displayCategoryCode': cat_code,
        'sellerProductName': draft.name,
        'vendorId': vendor['vendor_id'],
        'saleStartedAt': _SALE_STARTED_AT,
        'saleEndedAt': _SALE_ENDED_AT,
        'brand': draft.brand or '',
        'deliveryMethod': 'SEQUENCIAL',
        'deliveryCompanyCode': _DELIVERY_COMPANY,
        'deliveryChargeType': 'FREE' if delivery_fee == 0 else 'NOT_FREE',
        'deliveryCharge': delivery_fee,
        'remoteAreaDeliverable': 'N',
        'returnCenterCode': vendor.get('return_center_code', ''),
        'returnChargeName': vendor.get('return_center_code', ''),
        'placeAddressZipCode': vendor.get('return_zip', ''),
        'returnAddress': vendor.get('return_address', ''),
        'returnAddressDetail': vendor.get('return_address_detail', ''),
        'returnCharge': return_fee,
        'returnZipCode': vendor.get('return_zip', ''),
        'companyContactNumber': vendor.get('return_phone', ''),
        'outboundShippingPlaceCode': vendor.get('outbound_place_code', 0),
        'requested': False,   # 초안 — 사람이 확인 후 승인요청
        'items': items,
    }
    return payload, excluded
