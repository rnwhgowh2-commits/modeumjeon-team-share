# -*- coding: utf-8 -*-
"""마켓별 **실측 상한** — 지도(marketplace_api_map.json)에서 확인된 것만.

왜 따로 두나:
  가공 규칙의 `name.max_len` 기본값 100 은 `process_rule_schema.py:74` 에 **전 마켓 공통**
  으로 박혀 있다. 실제 상한은 마켓마다 다르고, 지도에는 서술 문자열로만 흩어져 있어
  코드가 읽을 수 없었다. 그 문장들을 사람이 읽고 **확인된 것만** 여기에 구조화한다.

★ 지어내지 않는다 (프로젝트 최상위 원칙 · 폴백 금지)
  확인 못 한 마켓은 :data:`NAME_MAX_UNKNOWN` 에 **왜 확인 못 했는지**와 함께 남기고,
  상한을 **적용하지 않는다.** 잘못된 상한으로 상품명을 자르면 그게 더 큰 손해다
  (마켓이 거부하면 등록이 실패로 보이지만, 우리가 잘못 자르면 잘린 채로 팔린다).

★ 근거는 전부 `webapp/data/marketplace_api_map.json` 의 **상품 등록 API** 항목이다.
  같은 필드를 다른 API(조회·클레임 응답)가 선언한 길이는 근거로 쓰지 않는다 —
  등록이 받는 길이와 조회가 돌려주는 길이는 다를 수 있다.
  (consult-market-map 스킬 3-③ 「그래도 못 구한 칸은 확인불가로 명시」)
"""
# [2026-07-23] M4 가공 규칙 적용 엔진 — 마켓별 상품명 상한

#: 상품명 **글자수** 상한 — 등록 API 스펙에 글자수로 명시된 마켓만.
#:
#: smartstore : marketplace_api_map.json:103531 (smartstore.create-product-1-product)
#:              "추가 문구를 포함한 노출 상품명은 최대 100자까지 입력 가능합니다."
#:              → 추가 문구를 쓰지 않는 우리 경로에서는 상품명 자체가 100자 상한이다.
#: coupang    : marketplace_api_map.json:16047 · 16611 (coupang.products.product-creation)
#:              "(Body) 등록상품명  발주서에 사용되는 상품명  최대 길이 : 100 자"
#:              (노출상품명 displayProductName 도 같은 100자 — :16071)
#: eleven11   : marketplace_api_map.json:81443 · 82647 (eleven11.81 상품 등록)
#:              "상품명 · string [필수] · … 글자수는 100자로 제한됩니다."
NAME_MAX_LEN = {
    'smartstore': 100,
    'coupang': 100,
    'eleven11': 100,
}

#: **확인 불가** — 상한을 적용하지 않는 마켓과 그 이유. 화면에 그대로 보여준다.
#:
#: auction/gmarket : 지도에 **byte 기준**으로만 있고, 그마저 API 마다 값이 다르다.
#:   · auction.esm.20 / gmarket.esm.20 (일반 상품등록, 우리가 쓰는 POST /item/v1/goods)
#:     marketplace_api_map.json:35875 · 38459
#:     "검색용 상품명 (국문). 검색용+프로모션용 최대 100byte 까지 가능"
#:   · auction.esm.114 / gmarket.esm.114 (풀필먼트 스타배송 상품등록)
#:     marketplace_api_map.json:75683 · 77391
#:     "검색용 + 프로모션용 최대 50byte까지 입력 가능"
#:   byte 를 글자수로 바꾸려면 인코딩(EUC-KR 2byte / UTF-8 3byte)을 알아야 하는데
#:   지도에 없다. 게다가 「검색용 + 프로모션용 **합계**」라 상품명 단독 상한도 아니다.
#: lotteon : 등록 API(lotteon.product.create) 스펙에는 `spdNm(판매자상품명)` 만 있고
#:   **길이가 적혀 있지 않다**(marketplace_api_map.json:2249). 다른 롯데온 API 들이
#:   같은 필드를 `String(100)` 으로 선언하지만(예: :4130 송장전송 요청),
#:   등록 API 의 근거가 아니라 상한으로 쓰지 않는다.
NAME_MAX_UNKNOWN = {
    'auction': ('옥션 상품명 상한은 byte 기준(검색용+프로모션용 합계)이라 글자수로 '
                '바꿀 수 없습니다 — 지도에 인코딩이 없어 「확인 불가」로 둡니다. '
                '자르지 않고 그대로 보냅니다.'),
    'gmarket': ('G마켓 상품명 상한은 byte 기준(검색용+프로모션용 합계)이라 글자수로 '
                '바꿀 수 없습니다 — 지도에 인코딩이 없어 「확인 불가」로 둡니다. '
                '자르지 않고 그대로 보냅니다.'),
    'lotteon': ('롯데온 상품등록 API 스펙에 상품명 길이가 적혀 있지 않습니다 — '
                '「확인 불가」로 두고 자르지 않습니다.'),
}

#: 참고용 — 이번 범위(상품명·브랜드·금지어·태그)에 **쓰지 않는** 값이지만, 다음 사람이
#: 다시 지도를 뒤지지 않게 같이 남긴다. 옵션 항목(§7-9)을 만들 때 여기서 가져다 쓴다.
#:   coupang 업체상품옵션명 150자 — marketplace_api_map.json:16215 · 16751
OPTION_NAME_MAX_LEN = {
    'coupang': 150,
}


def name_max_len(market):
    """그 마켓의 상품명 글자수 상한. **확인 못 했으면 None** (= 상한 적용 안 함)."""
    return NAME_MAX_LEN.get(str(market or '').strip())


def name_limit_unknown_reason(market):
    """상한을 적용하지 않는 이유(확인 불가). 상한을 아는 마켓이면 None."""
    mk = str(market or '').strip()
    if not mk or mk in NAME_MAX_LEN:
        return None
    return NAME_MAX_UNKNOWN.get(mk)
