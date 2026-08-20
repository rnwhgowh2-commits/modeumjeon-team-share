# -*- coding: utf-8 -*-
"""정책 13항목 × 6마켓 — **마켓이 등록 때 요구하는가**.

★ 판정 기준은 **마켓 상품등록 API 원문 하나뿐**이다 (사장님 확정 2026-08-02).
  근거는 전부 `webapp/data/marketplace_api_map.json` 의 **상품 등록 API** 항목이고,
  각 칸에 그 원문을 그대로 실어 둔다. 화면이 근거를 같이 보여줘야
  「왜 필수라는 거지」로 되묻는 일이 없다.

★ **지어내지 않는다** (프로젝트 최상위 원칙 · 폴백 금지)
  등록 API 스펙에서 근거를 못 찾은 칸은 :data:`UNKNOWN` 으로 두고 **왜 못 찾았는지**를
  남긴다. `market_limits.py` 가 상품명 상한에 쓴 잣대와 같다 — 「모름」을 「필수 아님」
  으로 읽으면 그게 곧 거짓 안내다(사장님이 안 채우고 등록했다가 거부당한다).

━━ 네 가지 상태 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  REQUIRED    등록 API 가 필수라고 **명시**. `[필수]`·`required=O/Y`·`*` 표기,
              또는 설명문에 「상품 등록 시 필수」라고 적힌 것.
  CONDITIONAL 「~인 경우 필수」 — 조건이 맞을 때만. (예: 스스 KC = 어린이제품 카테고리)
  OPTIONAL    등록 API 에 그 필드가 **있는데 필수 표기가 없다** = 확인된 「선택」.
  UNKNOWN     등록 API 스펙에서 근거를 못 찾음. **필수 아님이 아니라 모름.**

🔴 우리 코드(`compile_*`)가 막는 것과는 **다른 축**이다. 예를 들어 쿠팡 카테고리는
   마켓은 「미입력 시 자동매칭」이라 선택인데 우리 `require_category` 가 막는다.
   그 사실은 `CODE_GATE` 에 따로 적어 두고, 배지는 **마켓 원문만** 따른다.
"""
# [2026-08-02] 정책 생성 화면 「필수」 표시 — consult-market-map 게이트 통과분

REQUIRED = 'required'
CONDITIONAL = 'conditional'
OPTIONAL = 'optional'
UNKNOWN = 'unknown'

#: 마켓 → 근거로 삼은 상품등록 API (marketplace_api_map.json 의 `apis[].id`)
SOURCE_API = {
    'smartstore': 'smartstore.create-product-product',   # POST /v2/products
    'coupang': 'coupang.products.product-creation',      # POST …/seller-products
    'auction': 'auction.esm.20',                         # POST https://sa2.esmplus.com/item/v1/goods
    'gmarket': 'gmarket.esm.20',                         # 〃 (ESM 공용)
    'eleven11': 'eleven11.81',                           # POST http://api.11st.co.kr/rest/prodservices/product
    'lotteon': 'lotteon.product.create',                 # POST …/product/registration/request
}

#: 롯데온 전용 — 지도의 등록 API 항목이 **요약본**이라 대부분을 확인할 수 없다.
#:   params 에 별표(필수)가 붙은 것은 거래·카테고리 계열 8칸뿐이고, 마지막 줄이
#:   "…전체 상품 스키마 38테이블(상세조회 응답과 동일 구조)" 로 끝난다.
#:   ※ 승격 조건: 롯데ON apiNo=87 전문을 확보해 지도에 되채운 뒤
#:     (consult-market-map 3-②) 이 표의 UNKNOWN 을 옮긴다.
LOTTEON_UNKNOWN_REASON = (
    '롯데온 상품등록 API 는 지도에 요약본만 있습니다 — 필수 표기가 거래·카테고리 '
    '계열 8칸뿐이고 나머지는 「전체 상품 스키마 38테이블」로 줄여져 있습니다. '
    '없다고 단정하지 않고 「확인 불가」로 둡니다. 채우지 않고 올리면 롯데온이 '
    '거부할 수 있습니다.'
)

_L = (UNKNOWN, '', LOTTEON_UNKNOWN_REASON)


def _r(evidence, note=''):
    return (REQUIRED, evidence, note)


def _c(evidence, note=''):
    return (CONDITIONAL, evidence, note)


def _o(evidence, note=''):
    return (OPTIONAL, evidence, note)


def _u(reason):
    return (UNKNOWN, '', reason)


#: (마켓, 항목) → (상태, 근거 원문, 덧붙일 말)
#:
#: 🔴 근거 원문은 지도에서 **그대로 옮긴 문자열**이다. 요약하지 않는다 —
#:   요약하는 순간 「어디까지가 마켓 말이고 어디부터가 우리 해석인지」가 사라진다.
TABLE: dict[str, dict[str, tuple]] = {
    # ── 스마트스토어 : 요청 본문(`요청.*`) 필드만 근거로 쓴다 ──────────────
    #    (같은 API 항목에 응답 스키마가 섞여 있어, `요청.` 접두어가 없는 줄은
    #     조회 응답이다. 그걸 근거로 쓰면 등록이 안 받는 칸을 필수라고 하게 된다.)
    'smartstore': {
        'name': _r('요청.name — 상품명 (string) [필수]'),
        'category': _r('요청.leafCategoryId — 리프 카테고리 ID (string) · '
                       '상품 등록 시 필수입니다.'),
        'price': _r('요청.salePrice — 상품 판매 가격 (integer<int64>) [필수]'),
        # 🔴 [실등록 대조] 문서는 「최소 한 개는 입력해야」라고 적혀 있지만, 우리
        #   `compile_smartstore` 는 옵션 없이 평면 재고(stockQuantity)로도 등록한다.
        #   라이브에서 그렇게 등록된 상품이 있으므로 「무조건 필수」라고 하면 거짓이다.
        'options': _c('요청.optionInfo — 옵션 정보 (object) · 단독형 옵션, 조합형 옵션, '
                      '직접 입력형 옵션 중 최소 한 개는 입력해야 합니다.',
                      '옵션 없는 단일 상품은 재고 수량만 보내도 등록됩니다 — 우리 실등록이 '
                      '그렇게 하고 있습니다.'),
        'images': _r('요청.images — 상품 이미지 (object) [필수] · 대표 이미지는 필수이고 '
                     '추가 이미지는 선택 사항입니다.',
                     '이미지 URL 은 「상품 이미지 다건 등록」으로 올려 받은 네이버 CDN '
                     '주소여야 합니다 — 외부 주소는 거부됩니다.'),
        'detail': _r('요청.detailContent — 상품 상세 정보 (string) [필수]'),
        # 🔴 [실등록 대조] `deliveryFee`·`claimDeliveryInfo` 는 둘 다 [필수] 지만
        #   **둘 다 `deliveryInfo` 라는 선택 묶음 안에 있다.** 그 묶음 설명이
        #   "입력하지 않으면 배송 없는 상품으로 등록됩니다" 라, 통째로 빼면 등록은 된다.
        #   실제로 우리 두 등록 경로(compile_smartstore · create_product) 모두
        #   `deliveryInfo` 를 아예 안 보낸다 — 그래서 「무조건 필수」가 아니라 조건부다.
        #   ⚠️ 안 보내면 「배송 없는 상품」이 되는지는 라이브에서 따로 확인해야 한다.
        'shipping': _c('요청.deliveryInfo — 배송 정보 (object) · 입력하지 않으면 배송 없는 '
                       '상품으로 등록됩니다. / 그 안의 요청.deliveryFee — 배송비 정보 '
                       '(object) [필수] · 요청.claimDeliveryInfo — 클레임(반품/교환) 정보 '
                       '(object) [필수]',
                       '배송 정보를 보낼 거면 배송비·반품교환비는 반드시 있어야 합니다. '
                       '통째로 안 보내면 「배송 없는 상품」이 됩니다.'),
        'notice': _r('요청.productInfoProvidedNotice — 상품정보제공고시 (object) · '
                     '상품 등록 시 필수'),
        'brand': _o('요청.brandName — 브랜드명 (string)'),
        'origin': _r('요청.originAreaInfo — 원산지 정보 (object) [필수] / '
                     '요청.originAreaCode — 원산지 상세 지역 코드 (string) [필수]'),
        'kc': _c("요청.productCertificationInfos — 인증 정보 목록 (object[]) · "
                 "'어린이제품 인증 대상' 카테고리 상품인 경우 필수"),
        'tags': _o('요청.sellerTags — 판매자 입력 태그 (object[])'),
        # ── [2026-08-12] 사장님 엑셀 「마켓별 상품등록 정보」 대조로 추가 ──
        'listing': _r('요청.minorPurchasable — 미성년자 구매 가능 여부 (boolean) [필수] / '
                      '요청.taxType — 부가가치세 타입 코드 (string) · 코드: [TAX, DUTYFREE, SMALL] / '
                      '요청.saleType — 상품 판매 유형 코드 (string) · 코드: [NEW, OLD] / '
                      '요청.saleStartDate·saleEndDate — 판매 시작/종료 일시',
                      '묶음 안에서 [필수] 표기가 붙은 것은 미성년자 구매 가능 여부 하나입니다.'),
        'price_compare': _r('요청.naverShoppingRegistration — 네이버 쇼핑 등록 여부 '
                            '(boolean) [필수] · 네이버 쇼핑 광고주가 아닌 경우에는 '
                            'false 로 저장됩니다.'),
        'ids': _o('요청.modelName — 상품 모델명 (string) / 요청.modelId — 상품 모델 ID / '
                  '요청.sellerBarcode — 판매자 바코드 (string). 셋 다 필수 표기가 없습니다.'),
        'banned_words': _o('마켓 등록 API 에 없는 칸입니다 — 우리 쪽 거르개입니다.'),
    },

    # ── 쿠팡 : params 의 required 칸이 'O' 인 것 ──────────────────────────
    'coupang': {
        'name': _r('sellerProductName [필수] — (Body) 등록상품명  발주서에 사용되는 '
                   '상품명  최대 길이 : 100 자'),
        'category': _o('displayCategoryCode — (Body) 노출카테고리코드 · ※ 미입력 시, '
                       '카테고리 자동매칭 서비스에 의해 자동으로 카테고리가 등록될 수 '
                       '있습니다.',
                       '마켓은 선택이지만 우리 프로그램이 막습니다 — 자동매칭이 엉뚱한 '
                       '카테고리에 넣으면 마켓 제재 대상이라 지어내지 않습니다.'),
        'price': _r('items.salePrice [필수] — 판매가격'),
        'options': _r('items.attributes [필수] — 옵션목록(속성)  한개 이상 필수 등록'),
        'images': _r('items.images [필수] — 이미지목록 / items.images.imageType — '
                     'REPRESENTATION(정사각형 대표이미지, 필수)'),
        'detail': _r('items.contents [필수] — 컨텐츠목록'),
        'shipping': _r('deliveryMethod [필수] / deliveryChargeType [필수] / '
                       'deliveryCharge [필수] / returnCenterCode [필수] — 반품지센터코드',
                       '반품지·출고지 칸은 쿠팡 계정정보에서 가져옵니다 — 정책에서 정하는 '
                       '값이 아닙니다.'),
        'notice': _o('items.notices — 상품고시정보 목록'),
        'brand': _o('brand — (Body) 브랜드  브랜드명은 한글/영어 표준이름 입력'),
        'origin': _u('쿠팡 상품등록 API 에 원산지 단독 칸이 없습니다 — 고시정보(notices) '
                     '안에 넣는 구조로 보이나 스펙에 명시가 없어 「확인 불가」로 둡니다.'),
        'kc': _c('items.certifications.certificationType — 인증정보Type  인증대상이 '
                 '아닌 카테고리일 경우 : NOT_REQUIRED'),
        'tags': _o('items.searchTags — 검색어  1개당 20자 이내, 최대 20개'),
        # ── [2026-08-12] 사장님 엑셀 대조로 추가 ──
        'listing': _r('요청.items.taxType — 과세여부 [필수] · TAX=과세(기본값)/FREE=비과세 / '
                      '요청.items.adultOnly — 19세이상 [필수] · ADULT_ONLY/EVERYONE(기본값) / '
                      '요청.saleStartedAt — 판매시작일시 [필수] / 요청.saleEndedAt — '
                      '판매종료일시 · "*2099년 까지 길게 선택"',
                      '🔴 쿠팡은 판매종료일시가 필수라 「설정 안 함」이 없습니다 — 문서가 '
                      '2099년까지 길게 잡으라고 안내합니다. 제조사(요청.manufacture)는 '
                      '「정확히 못 적으면 brand 와 동일하게 입력 가능」입니다.'),
        'price_compare': _o('쿠팡 상품등록 API 에는 가격비교 노출 칸이 없습니다 — '
                            '사장님 엑셀에도 X 로 적혀 있습니다.'),
        'ids': _o('요청.items.modelNo — 모델번호 / 요청.items.barcode — 바코드 / '
                  '요청.items.emptyBarcode — 바코드 없음(없으면 true) / '
                  '요청.items.emptyBarcodeReason — 사유(100자). 필수 표기는 없습니다.',
                  '바코드가 없으면 「없음」이라고 밝히는 칸이 따로 있습니다.'),
        'banned_words': _o('마켓 등록 API 에 없는 칸입니다 — 우리 쪽 거르개입니다.'),
        '_parallel_import': _r('요청.items.parallelImported — 병행수입여부 [필수] · PARALLEL_IMPORTED=병행수입 / NOT_PARALLEL_IMPORTED=병행수입 아님'),
        '_winner': _o('쿠팡 등록 API 에 위너 가격 칸은 없습니다 — 등록 뒤 가격 운영 '
                      '규칙입니다.'),
        '_max_per_person': _r('items.maximumBuyForPerson [필수] — 인당 최대 구매 수량  '
                              "제한 없을 경우 '0'"),
    },

    # ── 옥션 / G마켓 : ESM 공용 등록 API. required 칸이 'Y' 인 것 ──────────
    #    (두 마켓이 같은 전문을 쓴다. 값 칸만 Gmkt / Iac 로 갈린다.)
    'auction': {},   # 아래에서 _ESM 로 채운다
    'gmarket': {},

    # ── 11번가 : 설명문에 `[필수]` 가 박힌 것 ──────────────────────────────
    'eleven11': {
        'name': _r('요청.prdNm — 상품명 · string [필수] · 글자수는 100자로 제한됩니다.'),
        'category': _r('요청.dispCtgrNo — 카테고리번호 · string [필수] · 최하위 '
                       '카테고리만 입력가능합니다.'),
        'price': _r('요청.selPrc — 판매가 · string [필수] · 판매가는 10원 단위로, '
                    '최대 10억 원 미만으로 입력 가능합니다.'),
        'options': _r('요청.colTitle — 옵션명 · string [필수] / 요청.colValue0 — 옵션값 · '
                      'string [필수] / 요청.colCount — 옵션재고수량 · string [필수]',
                      '옵션가격이 0원인 상품이 반드시 1개 이상 있어야 합니다.'),
        'images': _r('요청.prdImage01 — 대표 이미지 URL · string [필수]'),
        'detail': _r('요청.htmlDetail — 상세설명 · string [필수]'),
        'shipping': _r('요청.dlvWyCd — 배송방법 · enum [필수] / 요청.dlvCstInstBasiCd — '
                       '배송비 종류 · enum [필수] / 요청.addrSeqOut — 출고지 주소 코드 · '
                       'string [필수] / 요청.rtngdDlvCst — 반품 배송비 · string [필수]'),
        'notice': _r('요청.ProductNotification — 상품정보제공고시 · string [필수]'),
        'brand': _r('요청.brand — 브랜드 · string [필수] · 브랜드를 정확히 입력하면 해당 '
                    '상품의 검색 노출이 더 많아집니다.',
                    '6마켓 중 브랜드를 필수로 요구하는 곳은 11번가뿐입니다.'),
        'origin': _r('요청.orgnTypCd — 원산지 코드 · enum [필수] / 요청.rmaterialTypCd — '
                     '원재료 유형 코드 · enum [필수]'),
        # 🔴 [실등록 대조 — 문서와 실제가 다름] 문서는 [필수] 인데, 우리 11번가 등록
        #   XML(`shared/platforms/eleven11/products.py`)은 이 칸을 **한 번도 안 보낸다**.
        #   그런데도 2026-07-21 4대 마켓 실등록 라이브 검증을 통과했다.
        #   어느 쪽이 맞는지 라이브로 재확인하기 전까지 **문서 쪽을 표시**하되(사장님이
        #   고른 기준), 실제와 다르다는 사실을 같이 적는다. 한쪽만 말하면 거짓이 된다.
        'kc': _r('요청.crtfGrpObjClfCd — KC인증대상여부 · enum [필수] · '
                 '01=KC인증대상 / 02=KC면제대상 / 03=KC인증대상 아님',
                 '⚠️ 문서는 필수라고 하지만, 우리 실등록은 이 칸 없이 통과했습니다'
                 '(2026-07-21 라이브 검증). 카테고리에 따라 갈릴 수 있어 「확실」이 '
                 '아닙니다.'),
        'tags': _o('11번가 등록 API 에 태그 필수 표기가 없습니다.'),
        # ── [2026-08-12] 사장님 엑셀 대조로 추가 ──
        'listing': _r('suplDtyfrPrdClfCd — 부가세/면세상품코드 [필수] · 01=과세 / '
                      'compPrdVatCd — 부가세 [필수] / minorSelCnYn — 미성년자 구매가능 '
                      '[필수] · Y=가능 / prdStatCd — 상품상태 [필수] · 01=새상품 계열',
                      '11번가는 과세·미성년자·상품상태가 모두 [필수] 입니다. '
                      '제조사(company)는 「제조사/수입사 모두 없을 시 "없음"으로」 입니다.'),
        'price_compare': _o('prcCmpExpYn — 가격비교 사이트 노출 여부 · '
                            '「가격비교사이트 노출은 선택사항이며」 라고 적혀 있습니다. / '
                            'prcDscCmpExpYn — 가격비교 사이트 할인 적용(선택).'),
        'ids': _c('modelNm — 모델명 · 「모델명이 없을 시 "없음"으로 입력합니다」 / '
                  'modelCd — 모델코드',
                  '필수 표기는 없지만 빈칸을 받지 않아 「없음」이라고 적어야 합니다. '
                  '바코드 칸은 11번가 등록 요청 필드에서 찾지 못했습니다.'),
        'banned_words': _o('마켓 등록 API 에 없는 칸입니다 — 우리 쪽 거르개입니다.'),
        '_sell_method': _r('selMthdCd — 판매방식 [필수] · 01=고정가판매 / 04=예약판매 / 05=중고판매'),
    },

    # ── 롯데온 : 지도가 요약본 — 카테고리 계열만 확인된다 ──────────────────
    'lotteon': {
        # 말풍선(title)에 그대로 나가는 글이라 마크다운 기호를 쓰지 않는다 —
        # `**` 가 화면에 별표 두 개로 그대로 보인다(라이브 확인).
        'name': _u('롯데온 등록 API 요약본에 spdNm(판매자상품명) 은 있으나 별표(필수) '
                   '표기가 없습니다. ' + LOTTEON_UNKNOWN_REASON),
        'category': _r('scatNo*(표준카테고리번호) / dcatLst*(전시카테고리) / '
                       'lfDcatNo*(leaf전시카테고리) — 별표 = 필수'),
        'price': _u('요약본의 `itmLst[](단품:sitmNm/slPrc/stkQty/itmOptLst)` 안에 판매가가 '
                    '있으나 별표가 없습니다 — ' + LOTTEON_UNKNOWN_REASON),
        'options': _u(LOTTEON_UNKNOWN_REASON),
        'images': _u(LOTTEON_UNKNOWN_REASON),
        'detail': _u('롯데온은 본보기 상품(spdNo)의 상세를 복사해 등록합니다 — 상세 칸의 '
                     '필수 여부가 스펙에 없습니다. ' + LOTTEON_UNKNOWN_REASON),
        'shipping': _u(LOTTEON_UNKNOWN_REASON),
        'notice': _u(LOTTEON_UNKNOWN_REASON),
        'brand': _u('요약본에 `brdNo(브랜드번호)` 는 있으나 별표가 없습니다 — '
                    + LOTTEON_UNKNOWN_REASON),
        'origin': _u(LOTTEON_UNKNOWN_REASON),
        'kc': _u(LOTTEON_UNKNOWN_REASON),
        'tags': _u(LOTTEON_UNKNOWN_REASON),
        # ── [2026-08-12] 사장님 엑셀 대조 — 롯데온은 지도가 요약본이라 전부 확인 불가 ──
        'listing': _L,
        'price_compare': _L,
        'ids': _L,
        'banned_words': _o('마켓 등록 API 에 없는 칸입니다 — 우리 쪽 거르개입니다.'),
        '_site_discount': _u(LOTTEON_UNKNOWN_REASON),
    },
}

#: 옥션·G마켓 공용 (ESM 전문 하나) — 값 칸만 Iac / Gmkt 로 갈린다.
_ESM = {
    'name': _r('itemBasicInfo > goodsName > kor [필수] — 검색용 상품명 (국문). '
               '검색용+프로모션용 최대 100byte 까지 가능'),
    'category': _r('itemBasicInfo > category > site > catCode [필수] — G마켓/옥션 '
                   '카테고리코드. G마켓/옥션 최하위(Leaf) 카테고리 코드 등록'),
    'price': _r('itemAddtionalInfo > price > Iac / Gmkt [필수] — 판매가격. 10원 이상 '
                '10억 미만 입력 가능. 10원 단위로 입력 가능'),
    'options': _r('itemAddtionalInfo > recommendedOpts > type [필수] — 추천옵션 타입. '
                  '0 : 옵션 미사용 1 : 선택형',
                  '「옵션 미사용(0)」도 골라서 보내야 합니다.'),
    'images': _r('itemAddtionalInfo > images > basicImgURL [필수] — 상품기본이미지. '
                 '사이즈: 최소 600x600, 권장 1000x1000 용량: 2MB 이하 포맷: jpg, png',
                 '옥션은 같은 이미지를 여러 상품에 다시 쓸 수 없습니다.'),
    'detail': _r('itemAddtionalInfo > descriptions > kor > html [필수] — 상품상세정보 '
                 'html. iframe, Script, 및 max-width 등은 사용 불가'),
    'shipping': _r('itemAddtionalInfo > shipping > type [필수] — 배송방법 타입 / '
                   'shipping > policy > placeNo [필수] — 출하지번호 / '
                   'shipping > dispatchPolicyNo [필수] — 발송정책번호'),
    'notice': _r('itemAddtionalInfo > officialNotice > officialNoticeNo [필수] — '
                 '상품정보고시 상품군코드 / details > value [필수] — 상품정보고시 값'),
    'brand': _o('itemBasicInfo > catalog > brandNo — 브랜드코드. 브랜드코드 조회 API로 '
                '확인 가능'),
    'origin': _o('itemAddtionalInfo > origin > goodsType — 원산지 구분. '
                 '0 : 원산지 의무표시 대상 아님 …'),
    'kc': _u('ESM 등록 전문에서 KC 인증 칸을 찾지 못했습니다 — 고시정보(officialNotice) '
             '안에 들어가는 것으로 보이나 스펙에 명시가 없어 「확인 불가」로 둡니다.'),
    'tags': _u('ESM 등록 전문에서 태그 칸을 찾지 못했습니다.'),
    # ── [2026-08-12] 사장님 엑셀 대조로 추가 ──
    'listing': _r('itemAddtionalInfo > isVatFree [필수] — 부가세여부. true=면세/false=과세 / '
                  'itemAddtionalInfo > sellingPeriod > Gmkt [필수] · > Iac [필수] — 판매기간. '
                  '-1(무제한), 15, 30, 60, 90 / itemAddtionalInfo > goodsStatus — 상품상태. '
                  '1=신상품 2=중고상품 / itemAddtionalInfo > isAdultProduct — 미성년자 구매 여부',
                  '판매기간은 -1 을 넣으면 무제한입니다. 제조사 칸은 못 찾았고 '
                  '제조일(manufacturedDate)만 있습니다.'),
    'price_compare': _o('addtionalInfo > pcs > isUse — 가격비교사이트 상품 노출 여부. '
                        'true=노출함 / addtionalInfo > pcs > isUseIacPcsCoupon — '
                        '(옥션용) 가격비교사이트 쿠폰적용여부. 필수 표기는 없습니다.'),
    'ids': _o('itemBasicInfo > catalog > modelName — 모델명 / '
              'itemBasicInfo > catalog > barCode — 바코드 입력. 필수 표기는 없습니다.'),
    'banned_words': _o('마켓 등록 API 에 없는 칸입니다 — 우리 쪽 거르개입니다.'),
    # 🔴 지도에는 **옥션·G마켓 둘 다** 필수(Y)다. `fields.py:EXTRA_ITEMS` 의
    #   `_site_discount` 는 only=['gmarket','lotteon'] 이라 **옥션이 빠져 있다**.
    '_site_discount': _r('addtionalInfo > siteDiscount > gmkt [필수] / '
                         'addtionalInfo > siteDiscount > iac [필수] — 사이트부담 '
                         '지원할인. true : 적용 false : 적용하지 않음'),
}
TABLE['auction'] = dict(_ESM)
TABLE['gmarket'] = dict(_ESM)


# ── 배선 진단 — 정책에 채운 값이 실제로 마켓까지 가는가 ──────────────────
#
# 🔴 여기가 정책 화면의 진짜 함정이다. 항목을 다 채워도 **아직 안 나가는 것이 있다.**
#   [2026-08-12 정정] 전에는 「나가는 것은 판매가와 배송비뿐」이라고 적혀 있었는데,
#   그 사이 배선이 생겨 상품명·브랜드·옵션·상세설명도 나가고 있었다. 주석이 틀린 채
#   남으면 다음 사람이 또 그대로 믿는다 — 그래서 아래 표를 시험이 원본과 대조한다.
#   화면이 이 사실을 말하지 않으면 사장님은 채워 놓고 「왜 안 바뀌지」로 헤맨다.
#
#   판매가·배송비가 나가는 길: lemouton/policy/as_template.py 의 `_PolicyTemplate`
#   이 가격 엔진이 묻는 칸(`<접두>_rate_sourcing` 등)으로 번역해 준다.
#   그 껍데기를 쓰는 곳 = uploader/preview.py · uploader/reconcile.py ·
#   webapp/routes/api_pricing.py (전부 **이미 등록된 상품의 가격 갱신** 경로다).

# ── 실등록으로 확인할 것 (사장님 확정 2026-08-02 — 「나중에 실제로 올려보면서 검증」) ──
#
# 이 표는 **문서를 읽어 만든 것**이지 실제로 올려 본 결과가 아니다. 아래 칸들은
# 문서와 우리 실등록 실적이 어긋나거나, 문서 자체가 없어서 **직접 올려 봐야** 답이 난다.
# 실등록으로 확인되면 그 칸을 고치고 여기서 지운다 — 지우지 않으면 「확인했나 안 했나」가
# 흐려진다.
#
#   ⚠️ 확인 방법은 **일부러 그 칸만 비우고 등록을 시도**하는 것이다. 상품이 실제로
#     올라가므로 반드시 등록 직후 판매중지로 되돌린다(스스는 자동, 나머지는 수동).
TO_VERIFY_BY_LIVE = [
    ('lotteon', '*', '롯데온 13항목 거의 전부 — 등록 문서가 요약본이라 문서로는 영영 '
                     '못 정한다. 카테고리만 확인됨. 실등록이 유일한 길.'),
    ('eleven11', 'kc', '문서는 [필수] 인데 우리 XML 은 이 칸 없이 등록에 성공했다 '
                       '(2026-07-21). 카테고리에 따라 갈리는지 확인.'),
    ('smartstore', 'shipping', '배송 정보를 통째로 안 보내면 「배송 없는 상품」이 되는지 '
                               '확인 — 지금 우리 두 등록 경로 모두 안 보낸다.'),
    ('coupang', 'origin', '원산지 단독 칸이 없다. 고시정보 안에 넣는 게 맞는지 확인.'),
    ('auction', 'kc', 'ESM 전문에서 KC 칸을 못 찾았다. 고시정보로 갈음되는지 확인.'),
    ('auction', 'tags', 'ESM 전문에서 태그 칸을 못 찾았다.'),
]


WIRED = 'wired'          # 정책값이 실제로 밖으로 나간다
STORED_ONLY = 'stored'   # 저장만 된다 — 읽는 코드가 없다

# 🔴 [2026-08-12 실측 정정] 전에는 판매가·배송비 둘만 적혀 있었다. 그 사이
#   `policy/to_payload.py` → `registration/process_apply.apply_rules()` →
#   `send/as_draft.upsert()` 배선이 생겨 **상품명·브랜드·옵션·상세설명도 실제로
#   나가고 있었다.** 화면은 그것들을 「저장만 됩니다」라고 말하고 있었다 —
#   사장님이 「어차피 안 나간다」고 읽고 안 채웠으면 그대로 마켓에 나갔을 값들이다.
#   ★ 판정 근거 = `as_draft.upsert` 가 사본에서 **실제로 옮겨 담는 칸**.
#     그 목록과 이 표가 갈리지 않도록 `test_required_marks.py` 가 묶어 둔다.
WIRING: dict[str, tuple[str, str]] = {
    'name': (WIRED, '여기서 조립한 상품명이 그대로 마켓 초안의 이름이 됩니다 '
                    '(send/as_draft.py).'),
    'brand': (WIRED, '브랜드 표기가 상품명 조립에 쓰입니다 — 브랜드 칸 자체는 '
                     '상품에 저장된 값이 그대로 나갑니다.'),
    'banned_words': (WIRED, '금지어가 상품명에서 걸러진 뒤 나갑니다. '
                            '수집 금지어는 소싱처 단위로 따로 막습니다.'),
    'options': (WIRED, '옵션 구성이 그대로 마켓 초안의 옵션이 됩니다.'),
    'detail': (WIRED, '상세설명이 그대로 마켓 초안의 상세페이지가 됩니다.'),
    'price': (WIRED, '가격 엔진이 이 값으로 판매가를 계산합니다 '
                     '(policy/as_template.py).'),
    # [2026-08-13 2단계] 배송비·반품비가 초안까지 간다 — 전에는 상품 칸 기본값
    #   (3,000·5,000)이 그대로 나갔다.
    'shipping': (WIRED, '배송비와 반품 배송비가 마켓으로 나가고, 배송비는 판매가 '
                        '계산에도 쓰입니다 — 배송방법·출하지는 아직 나가지 않습니다.'),
    # [2026-08-13] 반쪽만 먹는다 — 정확히 그렇게 말한다.
    #   ① 「이미지 제외 브랜드」·「사진 없음」은 여기서 전송을 막는다(실제로 작동).
    #   ② 그런데 어느 사진을 몇 장 올릴지(대표만/추가 N장/범위)는 아직 안 먹는다 —
    #      초안이 옵션 사진을 다시 모아 쓰기 때문(send/as_draft.option_images).
    #   🔴 여기를 이으려면 먼저 사장님 확인이 필요하다: 기본값이 「대표 1장만」이라,
    #      그대로 켜면 지금 사진 전량이 나가는 스마트스토어가 1장으로 줄어든다.
    'images': (STORED_ONLY, '「이미지 제외 브랜드」와 「사진 없음」은 지금도 전송을 '
                            '막습니다. 다만 몇 장을 올릴지는 아직 안 먹습니다 — '
                            '초안이 옵션 사진을 다시 모아 씁니다.'),
    # [2026-08-13 2단계] 원산지가 초안까지 간다 — 전에는 「국내산」 기본값이 그대로
    #   나가서 해외 상품이 전부 국내산으로 등록됐다.
    'origin': (WIRED, '정책에서 「고정값」으로 정하면 그 원산지가 나갑니다. '
                      '「자동」이면 상품에 저장된 값을 그대로 씁니다.'),
    # [2026-08-13 3단계] 네 칸 **전부** 이어졌다 — 「저장만 됩니다」가 사실이 아니게 됐다.
    #   🔴 앞 문구는 「미성년자 구매만 나간다」였다. 그 사이 초안 칸이 생기고
    #     5마켓 배선이 붙었는데 문구만 남아 **화면이 반대로 거짓말**하고 있었다.
    #     (배선을 고치면 그것을 설명하는 표도 같이 낡는다 — 함께 고칠 것)
    #   🔴 마켓 수를 뭉개지 않는다: 제조사는 옥션·G마켓에 **칸 자체가 없다**
    #     (ESM 일반 상품엔 「예약설치」 전용 제조사 칸뿐 — 지도 전수 확인).
    'listing': (WIRED, '과세구분·미성년자 구매는 쿠팡·스마트스토어·11번가·옥션·G마켓 '
                       '다섯 곳으로 나갑니다. 제조사는 쿠팡·스마트스토어·11번가 세 곳입니다 '
                       '— 옥션·G마켓에는 제조사 칸이 없습니다. 롯데온은 등록 문서를 '
                       '아직 못 열어 확인하지 못했습니다.'),
    # [2026-08-13 3단계] 반쪽만 먹는다 — 정확히 그렇게 말한다(images 와 같은 부류).
    '_auto_pricing': (STORED_ONLY, '「최저가 직접 입력」은 쿠팡으로 나갑니다. '
                                   '「최저가를 마진율로 계산」은 아직 안 나갑니다 — '
                                   '최저가를 마진율로 내는 계산을 아직 잇지 않았습니다. '
                                   '쿠팡에만 있는 항목입니다.'),
}
#: 🔴🔴 [2026-08-13 실측 정정] 카테고리가 6마켓 전부 「저장만」으로 보이고 있었다.
#:   판단을 한 적이 없어서다 — 정책엔 카테고리 **코드** 칸이 없고(자동 매핑·실패 처리
#:   두 스위치뿐) 코드는 등록 때 고르는 값이라 이 표에 없었다. 그래서 `wiring_of` 의
#:   **기본값**(저장만)으로 떨어져, 판정한 적 없는 것을 단정하고 있었다.
#:   실제로는 `require_category` 가 값이 없으면 등록을 **막는다** — 안 나갈 수가 없다.
#:   사장님이 「어차피 안 나가는구나」로 읽으시면 가장 중요한 칸을 비워 두시게 된다.
#: 🔴 「미성년자 구매」 배선은 **다른 세션이 먼저 했다**(main `0d0ddc03`·`3f64acfb`).
#:   나도 같은 것을 만들었는데, 그쪽은 사본(`as_draft._POLICY_FIELDS`)을 거쳐 옮기고
#:   나는 규칙을 직접 읽었다 — 같은 값을 두 곳에서 만들면 반드시 갈린다.
#:   **먼저 들어온 쪽을 따르고 내 것을 버렸다.** `WIRING['listing']` 도 위 표에
#:   main 이 적어 둔 것을 그대로 쓴다(무엇이 나가고 무엇이 안 나가는지 더 정확하다).

#: 🔴 **정책 항목 `category` 와 마켓 칸 「카테고리」는 다른 것이다.**
#:   정책이 들고 있는 건 스위치 둘(자동 매핑·실패했을 때)뿐이고, 그건 초안이
#:   옮겨 담지 않는다 → 정책 항목으로서는 여전히 「저장만」이 맞다.
#:   반면 **마켓에 나가는 카테고리 값**은 등록할 때 반드시 실린다 —
#:   그건 아래 `category_field` 가 말한다. 체크리스트 열이 그쪽을 가리킨다.
WIRING['category'] = (
    STORED_ONLY,
    '정책의 카테고리 설정(자동 매핑·실패했을 때)은 마켓 초안이 아직 옮겨 담지 '
    '않습니다. 🔴 다만 **카테고리 값 자체는 등록할 때 반드시 나갑니다** — '
    '비어 있으면 등록이 막힙니다(같은 표의 「카테고리」 열을 보세요).')

WIRING['category_field'] = (
    WIRED,
    '카테고리는 등록할 때 반드시 나갑니다 — 비어 있으면 등록 자체가 막힙니다'
    '(require_category). 마켓별로 담기는 칸이 다릅니다: '
    '스마트스토어 leafCategoryId · 쿠팡 displayCategoryCode · 11번가 dispCtgrNo · '
    '옥션/G마켓 cat_code+site_cat_code. '
    '🔴 롯데온만 다릅니다 — 카테고리 번호가 아니라 **본보기 기존 상품번호**'
    '(LO 로 시작)를 넣으면 그 상품의 카테고리·고시·배송을 그대로 물려받습니다. '
    '정책의 「자동 매핑」·「실패했을 때」 두 스위치도 실제로 판정에 쓰입니다.')
#: 할인은 **항목(item)이 아니라 별도 배선**이다 — 판매가와 같은 `price` 항목에 얹혀 있어
#:   체크리스트가 판매가의 초록불을 빌려 쓰고 있었다(2026-08-13 실측). 여기서 갈라 둔다.
#:   🔴 근거: `policy/discount.py::discount_of` 를 부르는 **운영 코드가 0곳**이다(시험만 부른다).
#:     신규 등록(`compile_smartstore.py`)에도 `customerBenefit` 이 없고, 가격 갱신 어댑터
#:     (`uploader/adapters/smartstore.py`)에도 할인 인자가 없다.
#: 🔴 [2026-08-13 정정] 「보내는 코드가 0곳」이라 적어 뒀는데 그 사이 **쿠팡이 뚫렸다**
#:   (main #1018 — `policy/coupon_service`·`coupon_apply`, 화면·라우트에서 실제로 부른다).
#:   배선이 이어지면 그걸 말하는 표도 같이 낡는다 — 이 저장소가 반복해서 당한 형태다.
#:   상태는 **저장만**을 유지한다: 여섯 마켓 중 쿠팡 하나만 나가는데 「나감」으로 적으면
#:   나머지 다섯이 조용히 묻힌다.
WIRING['discount'] = (
    STORED_ONLY,
    '즉시할인은 **쿠팡에만** 실제로 나갑니다 — 즉시할인쿠폰을 만들어 옵션에 붙입니다'
    '(⏰ 쿠팡은 다음날 0시부터 적용). '
    '🔴 스마트스토어·11번가·옥션·G마켓·롯데온은 아직 보낼 자리를 못 찾았습니다 — '
    '그쪽 할인은 마켓 관리자 화면에서 직접 거셔야 합니다. '
    '다만 여기 적으신 값은 **여섯 마켓 모두 판매가 계산에 들어갑니다** — 판매자가 '
    '부담하는 할인만큼 판매가를 올려 잡아, 할인 뒤에도 목표 마진이 남게 합니다. '
    '그래서 이 칸을 비워 두면 마켓에 실제로 걸린 할인만큼 그대로 손해가 납니다.')

STORED_ONLY_NOTE = (
    '지금은 저장만 됩니다 — 이 값을 읽어 마켓으로 보내는 곳이 아직 없습니다. '
    '마켓에 실제로 나가는 값은 대량등록(데이터 가공)의 가공 규칙이 만듭니다.'
)


def wiring_of(item_key: str) -> tuple[str, str]:
    """그 항목이 실제 전송에 쓰이는지. `(상태, 설명)`."""
    return WIRING.get(item_key, (STORED_ONLY, STORED_ONLY_NOTE))


def status_of(market: str, item_key: str) -> tuple[str, str, str]:
    """(상태, 근거 원문, 덧붙일 말). 표에 없는 조합은 「확인 불가」.

    ★ 표에 없다고 「필수 아님」으로 돌려주지 않는다 — 그게 이 파일이 존재하는 이유다.
    """
    row = TABLE.get(str(market or '').strip())
    if row is None:
        return _u(f'「{market}」 는 상품등록 API 근거를 아직 정리하지 않은 마켓입니다.')
    got = row.get(item_key)
    if got is None:
        return _u(f'이 항목({item_key})에 해당하는 칸을 {market} 상품등록 API 스펙에서 '
                  f'찾지 못했습니다.')
    return got


def summary_for(market: str, item_keys, values: dict | None = None) -> dict:
    """그 마켓 한 벌 요약 — 화면 위쪽 띠에 쓴다.

    Args:
        item_keys: 그 마켓에 뜨는 항목 키들 (`fields.items_for` 순서).
        values: 저장된 값 (`service.values_for`). 주면 「필수인데 안 정함」을 센다.

    Returns:
        {required: n, unknown: n, missing: [item_key…], stored_only: n}
    """
    values = values or {}
    req, unk, missing = [], [], []
    for k in item_keys:
        st, _, _ = status_of(market, k)
        if st == REQUIRED:
            req.append(k)
            if not values.get(k):
                missing.append(k)
        elif st == UNKNOWN:
            unk.append(k)
    stored = sum(1 for k in item_keys if wiring_of(k)[0] == STORED_ONLY)
    return {'required': len(req), 'unknown': len(unk),
            'missing': missing, 'stored_only': stored}
