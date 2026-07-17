# -*- coding: utf-8 -*-
"""스마트스토어 상품고시정보 4종 빌더 (의류·신발·가방·패션잡화).

공식 규격 출처: marketplace_api_map.json → smartstore.create-product-product
  POST /v2/products · productInfoProvidedNotice

기존 lemouton/registration/smartstore.py:_build_default_shoes_notice() 는 신발 고정에
공통 필수 5개(청약철회·품질보증·환불절차·분쟁처리)가 빠져 있다. 그 함수는 모음전
경로가 쓰는 중이라 두고, 신규 경로는 이 모듈을 쓴다.
"""
# [2026-07-17] 대량등록 Phase 1A Task 3

NOTICE_TYPES = ('WEAR', 'SHOES', 'BAG', 'FASHION_ITEMS')

# 유형 → payload body 키
_BODY_KEY = {
    'WEAR': 'wear',
    'SHOES': 'shoes',
    'BAG': 'bag',
    'FASHION_ITEMS': 'fashionItems',
}

# 4종 공통 필수 7 — 법정 문구라 기본값을 제공한다(사용자 수정 가능).
_COMMON_DEFAULTS = {
    'returnCostReason': '제품의 하자 또는 오배송인 경우 판매자가 반품 비용을 부담합니다.',
    'noRefundReason': '전자상거래 등에서의 소비자보호에 관한 법률 제17조 제2항에 해당하는 경우 청약철회가 제한될 수 있습니다.',
    'qualityAssuranceStandard': '소비자분쟁해결기준(공정거래위원회 고시)에 따릅니다.',
    'compensationProcedure': '대금 환불 및 환불 지연에 따른 배상금 지급은 전자상거래 등에서의 소비자보호에 관한 법률에 따라 처리합니다.',
    'troubleShootingContents': '소비자 피해보상, 불만 처리, 분쟁 처리는 소비자분쟁해결기준에 따릅니다.',
    'warrantyPolicy': '구매일로부터 1년',
    'afterServiceDirector': '',   # 기본값 없음 — 판매자가 넣어야 한다
}

# 유형별 추가 필수 (공통 7 제외). snake_case 입력 키 → camelCase payload 키
_PER_TYPE_REQUIRED = {
    'WEAR': ('material', 'color', 'size', 'manufacturer', 'caution'),
    'SHOES': ('material', 'color', 'size', 'manufacturer', 'caution'),
    'BAG': ('type', 'material', 'color', 'size', 'manufacturer', 'caution'),
    'FASHION_ITEMS': ('type', 'material', 'size', 'manufacturer', 'caution'),
}

# 유형별 선택 필드
_PER_TYPE_OPTIONAL = {
    'WEAR': ('packDate', 'packDateText'),
    'SHOES': ('height',),
    'BAG': (),
    'FASHION_ITEMS': (),
}


class NoticeFieldMissing(ValueError):
    """필수 고시 필드 누락. 조용한 폴백 대신 실패시킨다 (프로젝트 폴백 금지 원칙)."""


def _camel(snake: str) -> str:
    head, *rest = snake.split('_')
    return head + ''.join(w.capitalize() for w in rest)


def build_notice(notice_type: str, data: dict) -> dict:
    """고시 유형 + 입력값 → productInfoProvidedNotice payload.

    Args:
        notice_type: 'WEAR' | 'SHOES' | 'BAG' | 'FASHION_ITEMS'
        data: snake_case 키 dict. 공통 7 은 미입력 시 _COMMON_DEFAULTS 로 채운다.

    Raises:
        ValueError: 알 수 없는 notice_type
        NoticeFieldMissing: 유형별 필수 필드가 비어 있음
    """
    if notice_type not in NOTICE_TYPES:
        raise ValueError(
            f"notice_type 은 {NOTICE_TYPES} 중 하나여야 합니다. 받은 값: {notice_type!r}")

    out = {}

    # 공통 7 — 사용자 값 우선, 없으면 기본 법정문구
    for camel_key, default in _COMMON_DEFAULTS.items():
        snake_key = _snake(camel_key)
        val = (data.get(snake_key) or data.get(camel_key) or default or '').strip()
        if not val:
            raise NoticeFieldMissing(f"고시 공통 필수 누락: {camel_key}")
        out[camel_key] = val

    # 유형별 필수
    for key in _PER_TYPE_REQUIRED[notice_type]:
        val = (data.get(key) or '').strip()
        if not val:
            raise NoticeFieldMissing(f"고시 필수 누락({notice_type}): {key}")
        out[_camel(key)] = val

    # 유형별 선택 — 값이 있을 때만
    for key in _PER_TYPE_OPTIONAL[notice_type]:
        val = (data.get(_snake(key)) or data.get(key) or '').strip()
        if val:
            out[key] = val

    return {
        'productInfoProvidedNoticeType': notice_type,
        _BODY_KEY[notice_type]: out,
    }


def _snake(camel: str) -> str:
    out = []
    for ch in camel:
        if ch.isupper():
            out.append('_')
            out.append(ch.lower())
        else:
            out.append(ch)
    return ''.join(out)
