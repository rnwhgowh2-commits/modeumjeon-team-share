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


# ══ 계정정보(vendor) 필수 칸 — 단일 진실 원천 ═══════════════════════════════
#  [2026-07-23 리뷰 C1] 전에는 vendor_id 하나만 검사하고 나머지를 vendor.get(k, '')
#  로 흘렸다. 그래서 「Wing 로그인 ID」 한 칸만 저장해도 사전점검이 ready 라고 말하고,
#  반품지 주소·우편번호·전화가 **빈 채로** 등록 payload 에 실렸다.
#  빈 반품지로 등록되면 반품이 엉뚱한 곳으로 가거나 접수 자체가 안 된다 = 금전 손실.
#
#  이 목록이 정본이다 — 저장소(coupang_vendor.SAVED_KEYS)도 화면의 「모두 저장됨」
#  판정(settings_tab)도 여기서 파생한다. 두 벌로 두면 언젠가 갈린다.
#  ⚠ 「상세주소가 없는 반품지」가 실제로 나오면 여기서 한 줄만 빼면 화면·등록이 같이
#    바뀐다. 조용히 통과시키지는 말 것.
VENDOR_KEY_LABELS = {
    'vendor_id': '판매자 ID',                      # `.env` {prefix}_VENDOR_ID
    'vendor_user_id': 'Wing 로그인 ID',
    'return_center_code': '반품지 코드',
    'return_charge_name': '반품지 이름',
    'return_zip': '반품지 우편번호',
    'return_address': '반품지 주소',
    'return_address_detail': '반품지 상세주소',
    'return_phone': '반품지 전화번호',
    'outbound_place_code': '출고지 코드',
}

#: compile_coupang 이 실제로 요구하는 칸. 하나라도 비면 등록·사전점검을 막는다.
VENDOR_REQUIRED_KEYS = tuple(VENDOR_KEY_LABELS)


def missing_vendor_keys(vendor) -> list:
    """비어 있는 필수 칸의 **키 목록** (순서는 VENDOR_REQUIRED_KEYS 그대로).

    0 도 '비었음' 으로 본다 — 출고지 코드 0 은 유효한 코드가 아니고, 나머지 칸은
    애초에 문자열이다.
    """
    v = vendor if isinstance(vendor, dict) else {}
    return [k for k in VENDOR_REQUIRED_KEYS
            if not str(v.get(k) or '').strip()]


def describe_vendor_keys(keys) -> str:
    """키 목록 → 사장님이 읽는 이름 목록. 영문 키는 화면에 내보내지 않는다."""
    return ', '.join(VENDOR_KEY_LABELS.get(k, k) for k in keys)


def _digits(v) -> str:
    return ''.join(c for c in str(v or '') if c.isdigit())


def _check_vendor(vendor) -> None:
    """계정정보 전수 검사 — 비었으면 **어느 칸인지 이름을 대며** 막는다(리뷰 C1·M4)."""
    missing = missing_vendor_keys(vendor)
    if missing:
        # 어디서 채우는지(설정 탭 안내)는 라우트가 COUPANG_VENDOR_HINT 로 덧붙인다 —
        # 여기서도 쓰면 같은 문장이 두 번 나온다.
        raise CompileError(
            f'쿠팡 계정정보가 비어 있습니다 — {describe_vendor_keys(missing)}.')

    # 형식 최소 검증(리뷰 M4) — 「채워는 놨는데 값이 아닌」 경우를 라이브 400 전에 잡는다.
    zip_digits = _digits(vendor.get('return_zip'))
    if len(zip_digits) not in (5, 6):        # 신 5자리 · 구 6자리
        raise CompileError(
            f'반품지 우편번호 형식이 이상합니다({vendor.get("return_zip")!r}) — '
            f'5자리(신) 또는 6자리(구) 숫자여야 합니다.')
    if len(_digits(vendor.get('return_phone'))) < 7:
        raise CompileError(
            f'반품지 전화번호 형식이 이상합니다({vendor.get("return_phone")!r}) — '
            f'숫자가 너무 적습니다. 반품 접수가 안 되는 번호로 등록됩니다.')


def compile_coupang(draft, *, category_code: int, vendor: dict):
    """ProductDraft → (쿠팡 상품 생성 payload, 제외된 옵션 목록).

    excluded 를 함께 돌려주는 이유는 compile_smartstore 와 같다 — 사용자가 입력한
    옵션이 조용히 사라지지 않게.

    Args:
        vendor: 계정별 고정값 — vendor_id, vendor_user_id(Wing 로그인 ID),
                return_center_code, return_charge_name(반품지명, 코드와 다른 사람이 읽는 이름),
                return_zip, return_address, return_address_detail, return_phone,
                outbound_place_code

    Raises:
        CompileError: 카테고리·이미지·판매가 누락, 또는 계정정보 9키 중 빈 칸이 있을 때
            (빈 칸은 **이름을 대며** 막는다 — VENDOR_KEY_LABELS)
    """
    require_category(category_code, what='쿠팡 displayCategoryCode')
    cat_code = coerce_int(category_code, '쿠팡 displayCategoryCode')
    # ★ 9키 **전수** 검사. vendor_id 만 보고 나머지를 흘리면 반쯤 빈 반품지로 등록된다.
    _check_vendor(vendor)
    # 출고지 코드는 라이브 검증된 coupang.py:115 와 같이 **정수**로 나간다. DB 컬럼은
    # String 이고 logistics._s() 도 str 로 만들어서, 변환 없이 넣으면 문자열이 나갔다.
    # 빈칸은 위에서 이미 막았고, 0 도 유효한 코드가 아니라 여기서 다시 막는다.
    outbound_code = coerce_int(vendor.get('outbound_place_code'), '출고지 코드')
    if not outbound_code:
        raise CompileError(
            f'출고지 코드가 유효하지 않습니다({vendor.get("outbound_place_code")!r}) — '
            f'0 으로 등록하면 출고지가 붙지 않습니다.')

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
            # items.attributes 는 "한개 이상 필수 등록" — 빈 [] 는 쿠팡이 400 으로 거부한다.
            # 옵션 분기는 늘 색상 attribute 를 내보내므로, 옵션 없는 단일상품도 같은
            # 축(색상=단일)으로 최소 1개를 합성한다. ⚠ Phase 1A 에서 옵션 없는 쿠팡
            # 등록이 실사용될지는 미확정 — 라이브 검증 시 이 합성값 재확인 필요.
            'attributes': [{'attributeTypeName': '색상', 'attributeValueName': '단일'}],
        }]

    for it in items:
        # ★ 라이브 검증된 coupang.py::_build_payload 는 item 수량계열 필드를 문자열로
        #   보낸다(int 로 보내면 400). 그 shape 를 그대로 맞춘다.
        it['maximumBuyCount'] = str(it.get('maximumBuyCount', 0))
        it.update({
            'contents': [{'contentsType': 'HTML',
                          'contentDetails': [{'content': draft.detail_html or '',
                                              'detailType': 'TEXT'}]}],
            'notices': [],   # Phase 2 — 쿠팡 noticeCategories 매핑
            'maximumBuyForPerson': '0',
            'maximumBuyForPersonPeriod': '1',   # 필수 — _build_payload 에 있고 우리 초안엔 빠졌던 것
            'outboundShippingTimeDay': '3',
            'unitCount': '1',
            'adultOnly': 'EVERYONE',
            'taxType': 'TAX',
            'parallelImported': 'NOT_PARALLEL_IMPORTED',
            'overseasPurchased': 'NOT_OVERSEAS_PURCHASED',
            'pccNeeded': 'false',
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
        'freeShipOverAmount': 0,
        'deliveryChargeOnReturn': return_fee,   # 초도반품배송비
        'remoteAreaDeliverable': 'N',
        'unionDeliveryType': 'UNION_DELIVERY',
        'returnCenterCode': vendor.get('return_center_code', ''),
        # returnChargeName = 반품지'명'(사람이 읽는 이름). 코드가 아니다 —
        # _build_payload 는 return_charge_vendor(별도 값)를 쓴다.
        'returnChargeName': vendor.get('return_charge_name', ''),
        'returnAddress': vendor.get('return_address', ''),
        'returnAddressDetail': vendor.get('return_address_detail', ''),
        'returnCharge': return_fee,
        'returnZipCode': vendor.get('return_zip', ''),
        'companyContactNumber': vendor.get('return_phone', ''),
        'outboundShippingPlaceCode': outbound_code,   # Number (지도·라이브 경로와 동일)
        'vendorUserId': vendor.get('vendor_user_id', ''),   # Wing 로그인 ID
        'requested': False,   # 초안 — 사람이 확인 후 승인요청
        'items': items,
        'requiredDocuments': [],
        'extraInfoMessage': '',
    }
    return payload, excluded
