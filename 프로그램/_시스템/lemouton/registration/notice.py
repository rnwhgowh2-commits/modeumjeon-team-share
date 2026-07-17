# -*- coding: utf-8 -*-
"""스마트스토어 상품고시정보 4종 빌더 (의류·신발·가방·패션잡화).

공식 규격 출처: marketplace_api_map.json → smartstore.create-product-product
  POST /v2/products · productInfoProvidedNotice

기존 lemouton/registration/smartstore.py:_build_default_shoes_notice() 는 신발 고정에
공통 필수 5개(청약철회·품질보증·환불절차·분쟁처리·피해보상)가 빠져 있다. 그 함수는
모음전 경로가 쓰는 중이라 두고, 신규 경로는 이 모듈을 쓴다.

[기본값 원칙 — 폴백 금지]
  네이버가 공식 문구를 제공하는 필드에만 기본값을 넣는다. 그 외에는 기본값을 두지
  않고 NoticeFieldMissing 을 던진다. 판매자가 약속한 적 없는 법적·금전적 약정
  (품질보증 기간, A/S 책임자)을 우리가 지어내서 라이브 리스팅에 게시하면 안 된다.
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

# "안 넣음" 과 "일부러 빈칸" 을 구분하는 센티넬.
# data.get(k) or default 로 하면 사용자가 의도적으로 비운 값에 기본값이 덮어씌워진다.
_UNSET = object()

# ─────────────────────────────────────────────────────────────────────────────
# 공통 필수 7 — 기본값
#
# ★ 아래 3개 문구는 네이버 공식 문구 option 0 을 marketplace_api_map.json
#   (smartstore.create-product-product → fields → 각 키의 meaning) 에서
#   **글자 그대로** 뽑은 것이다. 절대 손으로 고치거나 '다듬지' 말 것.
#   우리가 판매자를 대신해 법적 문구를 창작하는 셈이 된다.
#   재확인법: meaning 문자열의 "0 (...)" 안쪽을 괄호 균형으로 추출(중첩 괄호 있음).
#
# ★ returnCostReason / compensationProcedure 는 원본 meaning 이 문장 중간에서
#   잘려 있어(각각 237/285자에서 끊김 · 닫는 괄호도 option 1 도 없음) option 0 을
#   확보하지 못했다. 잘린 문구를 그대로 보내는 것도, 내가 말을 지어 채우는 것도
#   금지라 기본값 없이 두어 미입력 시 실패하게 한다. → 문구 확보 후 채울 것.
#
# ★ warrantyPolicy / afterServiceDirector 는 네이버가 프리셋을 제공하지 않는
#   자유 입력 필드다(품질보증 <=1500자, A/S책임자 <=200자). 판매자별 약속이라
#   기본값을 두면 안 된다.
# ─────────────────────────────────────────────────────────────────────────────
_COMMON_DEFAULTS = {
    # 네이버 공식 문구 option 0 — 원본 잘림으로 미확보
    'returnCostReason': '',
    # 네이버 공식 문구 option 0 (verbatim)
    'noRefundReason': '전자상거래 등에서의 소비자보호에 관한 법률 등에 의한 청약철회 제한 사유에 해당하는 경우 및 기타 객관적으로 이에 준하는 것으로 인정되는 경우 청약철회가 제한될 수 있습니다.',
    # 네이버 공식 문구 option 0 (verbatim)
    'qualityAssuranceStandard': '소비자분쟁해결기준(공정거래위원회 고시) 및 관계법령에 따릅니다.',
    # 네이버 공식 문구 option 0 — 원본 잘림으로 미확보
    'compensationProcedure': '',
    # 네이버 공식 문구 option 0 (verbatim)
    'troubleShootingContents': '소비자분쟁해결기준(공정거래위원회 고시) 및 관계법령에 따릅니다.',
    # 기본값 없음 — 판매자별 약속이라 넣어주면 안 된다 (폴백 금지)
    'warrantyPolicy': '',
    # 기본값 없음 — 판매자가 넣어야 한다
    'afterServiceDirector': '',
}

# 공통 7 — payload camel 키 → 입력 snake 키.
# (입력 dict 은 UI 에서 오므로 snake·camel 둘 다 받아준다)
_COMMON_IN_KEY = {
    'returnCostReason': 'return_cost_reason',
    'noRefundReason': 'no_refund_reason',
    'qualityAssuranceStandard': 'quality_assurance_standard',
    'compensationProcedure': 'compensation_procedure',
    'troubleShootingContents': 'trouble_shooting_contents',
    'warrantyPolicy': 'warranty_policy',
    'afterServiceDirector': 'after_service_director',
}

# 유형별 추가 필수 (공통 7 제외).
# 입력 키 = payload 키 (전부 소문자 한 단어라 변환이 필요 없다).
_PER_TYPE_REQUIRED = {
    'WEAR': ('material', 'color', 'size', 'manufacturer', 'caution'),
    'SHOES': ('material', 'color', 'size', 'manufacturer', 'caution'),
    'BAG': ('type', 'material', 'color', 'size', 'manufacturer', 'caution'),
    'FASHION_ITEMS': ('type', 'material', 'size', 'manufacturer', 'caution'),
}

# 유형별 선택 필드 — (입력 snake 키, payload camel 키)
_PER_TYPE_OPTIONAL = {
    'WEAR': (('pack_date', 'packDate'), ('pack_date_text', 'packDateText')),
    'SHOES': (('height', 'height'),),
    'BAG': (),
    'FASHION_ITEMS': (),
}


class NoticeError(ValueError):
    """고시정보 생성 실패 — 상위(컴파일러)가 이 하나만 잡으면 된다."""


class NoticeFieldMissing(NoticeError):
    """필수 고시 필드 누락. 조용한 폴백 대신 실패시킨다 (프로젝트 폴백 금지 원칙)."""


class UnknownNoticeType(NoticeError):
    """알 수 없는 고시 유형. notice_type 은 UI 에서 오고 DB 제약이 없다."""


def _text(raw) -> str:
    """자유형 JSON 입력값 → 문자열. int 95 · None 이 와도 터지지 않게.

    AttributeError 는 ValueError 가 아니라서 상위 핸들러를 그냥 통과해 500 이 된다.
    """
    if raw is None:
        return ''
    return str(raw).strip()


def build_notice(notice_type: str, data: dict) -> dict:
    """고시 유형 + 입력값 → productInfoProvidedNotice payload.

    Args:
        notice_type: 'WEAR' | 'SHOES' | 'BAG' | 'FASHION_ITEMS'
        data: snake_case 키 dict. 공통 7 중 네이버 공식 문구가 있는 것만
              미입력 시 _COMMON_DEFAULTS 로 채운다.

    Raises:
        UnknownNoticeType: 알 수 없는 notice_type
        NoticeFieldMissing: 필수 필드가 비어 있음
        (둘 다 NoticeError 하위 — 상위에서 NoticeError 하나만 잡으면 된다)
    """
    if notice_type not in NOTICE_TYPES:
        raise UnknownNoticeType(
            f"notice_type 은 {NOTICE_TYPES} 중 하나여야 합니다. 받은 값: {notice_type!r}")

    out = {}

    # 공통 7 — 사용자 값 우선. 값을 아예 안 넣은 경우(_UNSET)에만 기본값을 쓴다.
    # 일부러 빈칸으로 둔 경우는 기본값으로 덮지 않고 실패시킨다.
    for camel_key, default in _COMMON_DEFAULTS.items():
        snake_key = _COMMON_IN_KEY[camel_key]
        raw = data.get(snake_key, data.get(camel_key, _UNSET))
        val = default if raw is _UNSET else _text(raw)
        if not val:
            raise NoticeFieldMissing(f"고시 공통 필수 누락: {camel_key}")
        out[camel_key] = val

    # 유형별 필수
    for key in _PER_TYPE_REQUIRED[notice_type]:
        val = _text(data.get(key))
        if not val:
            raise NoticeFieldMissing(f"고시 필수 누락({notice_type}): {key}")
        out[key] = val

    # 유형별 선택 — 값이 있을 때만
    for snake_key, camel_key in _PER_TYPE_OPTIONAL[notice_type]:
        val = _text(data.get(snake_key, data.get(camel_key)))
        if val:
            out[camel_key] = val

    return {
        'productInfoProvidedNoticeType': notice_type,
        _BODY_KEY[notice_type]: out,
    }
