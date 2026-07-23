# -*- coding: utf-8 -*-
"""M3 Task 6 Step 1 — 마켓 상품조회 응답에서 '그때 고른 카테고리 코드'를 꺼낸다.

이미 받아오면서 버리던 값만 **추가 키**로 노출한다(기존 반환 계약 불변).
근거 = 데이터 코드 지도(consult-market-map 전수정독, 2026-07-23):
  · 스마트스토어  originProduct.leafCategoryId      (GET /external/v2/products/origin-products/{no})
  · 쿠팡          displayCategoryCode                (GET .../seller-products/{sellerProductId})
  · 옥션·G마켓    itemBasicInfo.category.site[].catCode(siteType 1=옥션·2=G마켓) + category.esm.catCode
  · 11번가        dispCtgrNo                         (상품조회 <Product> / 다중 상품 조회 ns2:product)
  · 롯데온        제외 — 등록이 본보기 spdNo 방식이라 카테고리 코드 개념이 없다.
라이브 호출 없음 — 전부 fixture 응답.
"""
from __future__ import annotations


# ── 스마트스토어 ────────────────────────────────────────────────────────
def test_스마트스토어_상품조회가_리프카테고리ID를_같이_돌려준다():
    from shared.platforms.smartstore.get_options import fetch_product_options

    class _C:
        def request(self, method, path, **kw):
            return {'originProduct': {'name': '테스트', 'salePrice': 39000,
                                      'leafCategoryId': '50000167',
                                      'detailAttribute': {'optionInfo': {'optionCombinations': []}}}}

    r = fetch_product_options(123, client=_C())
    assert r.success is True
    assert r.leaf_category_id == '50000167'
    # 기존 계약 불변 — 이름·가격·옵션은 그대로
    assert (r.product_name, r.sale_price, r.options) == ('테스트', 39000, [])


def test_스마트스토어_카테고리가_없으면_None이지_빈문자열_날조가_아니다():
    from shared.platforms.smartstore.get_options import fetch_product_options

    class _C:
        def request(self, method, path, **kw):
            return {'originProduct': {'name': 'x', 'detailAttribute': {}}}

    assert fetch_product_options(1, client=_C()).leaf_category_id is None


# ── 쿠팡 ────────────────────────────────────────────────────────────────
def test_쿠팡_상품상세에서_전시카테고리코드를_뽑는다():
    from shared.platforms.coupang.products import extract_display_category_code

    detail = {'sellerProductId': 111, 'displayCategoryCode': 63955, 'items': []}
    assert extract_display_category_code(detail) == '63955'


def test_쿠팡_카테고리코드가_없거나_0이면_None():
    from shared.platforms.coupang.products import extract_display_category_code

    assert extract_display_category_code({'items': []}) is None
    assert extract_display_category_code({'displayCategoryCode': 0}) is None
    assert extract_display_category_code(None) is None


# ── 옥션·G마켓(ESM) ─────────────────────────────────────────────────────
_ESM_DETAIL = {
    'goodsNo': '6478176871',
    'itemBasicInfo': {
        'goodsName': {'kor': '테스트'},
        'category': {
            'esm': {'catCode': 'SD12345'},
            'site': [
                {'siteType': 1, 'catCode': '200001234'},   # 옥션
                {'siteType': 2, 'catCode': '300005678'},   # G마켓
            ],
        },
    },
}


def test_ESM_상세에서_사이트별_카테고리코드를_고른다():
    from shared.platforms.esm.products import extract_category_codes

    a = extract_category_codes(_ESM_DETAIL, 'auction')
    g = extract_category_codes(_ESM_DETAIL, 'gmarket')
    assert a['site_cat_code'] == '200001234'
    assert g['site_cat_code'] == '300005678'
    # ESM 표준(sd) 코드는 짝으로 함께 돌려준다 — 등록 payload 가 둘 다 요구한다.
    assert a['esm_cat_code'] == 'SD12345' == g['esm_cat_code']


def test_ESM_사이트가_배열이_아니어도_dict_하나면_읽는다():
    from shared.platforms.esm.products import extract_category_codes

    d = {'itemBasicInfo': {'category': {'site': {'siteType': 2, 'catCode': '9'}}}}
    assert extract_category_codes(d, 'gmarket')['site_cat_code'] == '9'
    # 다른 사이트를 물으면 없는 것 — 반대편 코드를 돌려주면 엉뚱한 카테고리로 등록된다
    assert extract_category_codes(d, 'auction')['site_cat_code'] is None


def test_ESM_대소문자_혼용_필드명도_읽는다():
    """ESM 은 Gmkt/gmkt·CatCode/catCode 를 혼용한다(지도 과거이력)."""
    from shared.platforms.esm.products import extract_category_codes

    d = {'ItemBasicInfo': {'Category': {'Site': [{'SiteType': '1', 'CatCode': 'A1'}]}}}
    assert extract_category_codes(d, 'auction')['site_cat_code'] == 'A1'


def test_ESM_미지원_마켓이면_아무_사이트_코드도_돌려주지_않는다():
    """[2026-07-23 리뷰 M4] ESM 이 아닌 마켓 슬러그가 들어오면 siteType 대조가 무력화돼
    첫 번째 사이트(옥션) 코드가 그대로 나가던 자리 — 미지원이면 None(추측 금지)."""
    from shared.platforms.esm.products import extract_category_codes

    detail = {'itemBasicInfo': {'category': {
        'site': [{'siteType': '1', 'catCode': 'A1'}, {'siteType': '2', 'catCode': 'G1'}],
        'esm': {'catCode': 'SD1'}}}}
    assert extract_category_codes(detail, 'coupang') == {
        'site_cat_code': None, 'esm_cat_code': None}
    # 지원 마켓은 그대로 동작(대조군)
    assert extract_category_codes(detail, 'gmarket')['site_cat_code'] == 'G1'


def test_ESM_카테고리가_없으면_전부_None():
    from shared.platforms.esm.products import extract_category_codes

    out = extract_category_codes({'itemBasicInfo': {}}, 'auction')
    assert out == {'site_cat_code': None, 'esm_cat_code': None}


# ── 11번가 ──────────────────────────────────────────────────────────────
def test_11번가_상품조회가_카테고리번호를_같이_돌려준다():
    from shared.platforms.eleven11 import products as P

    class _C:
        def request(self, method, path, **kw):
            return ('<?xml version="1.0" encoding="euc-kr"?>'
                    '<Product><prdNo>9508004984</prdNo><prdNm>테스트</prdNm>'
                    '<selPrc>39000</selPrc><dispCtgrNo>1122</dispCtgrNo></Product>')

    d = P.get_product_detail('9508004984', client=_C())
    assert d['disp_ctgr_no'] == '1122'
    # 기존 계약 불변
    assert (d['prd_no'], d['prd_nm'], d['sel_prc']) == ('9508004984', '테스트', 39000)


def test_11번가_단건조회에_카테고리가_없으면_None이고_다중조회로_되찾는다():
    """단건 GET 응답에 dispCtgrNo 가 실려오는지는 라이브 미확정(지도 근거는 다중 상품 조회).

    그래서 단건에 없으면 **문서로 확정된 원천**(POST prodmarket · prdNo 조건)으로 한 번 더
    묻는다. 그래도 없으면 None — 0/빈값 날조 금지.
    """
    from shared.platforms.eleven11 import products as P

    calls = []

    class _C:
        def request(self, method, path, body=None, **kw):
            calls.append((method, path, body))
            if method == 'GET':
                return '<Product><prdNo>1</prdNo><selPrc>1000</selPrc></Product>'
            return ('<ns2:products xmlns:ns2="http://www.11st.co.kr">'
                    '<ns2:product><prdNo>1</prdNo>'
                    '<dispCtgrNo>19021</dispCtgrNo></ns2:product></ns2:products>')

    c = _C()
    assert P.get_product_detail('1', client=c)['disp_ctgr_no'] is None
    assert P.get_display_category_no('1', client=c) == '19021'
    # 다중 상품 조회 요청 본문에 prdNo 조건이 실려야 한 상품만 돌아온다
    assert '<prdNo>1</prdNo>' in (calls[-1][2] or '')


def test_11번가_어디에도_카테고리가_없으면_None():
    from shared.platforms.eleven11 import products as P

    class _C:
        def request(self, method, path, body=None, **kw):
            if method == 'GET':
                return '<Product><prdNo>1</prdNo></Product>'
            return '<ns2:products xmlns:ns2="http://www.11st.co.kr"></ns2:products>'

    assert P.get_display_category_no('1', client=_C()) is None


# ── [2026-07-23 리뷰 C2] 다중조회 되찾기는 '정확일치'만 채택 ────────────────
#   limit=1 로 아무 상품이나 돌아와도 그 카테고리를 confidence 0.99 로 박으면
#   다음 등록이 남의 카테고리로 나간다(금전 손해). 조건이 안 먹은 응답은 버린다.
def test_11번가_다중조회_응답에_prdNo가_없으면_그_행을_쓰지_않는다():
    from shared.platforms.eleven11 import products as P

    class _C:
        def request(self, method, path, body=None, **kw):
            if method == 'GET':
                return '<Product><prdNo>1</prdNo></Product>'
            # prdNo 가 아예 안 실려 온 행 — 어느 상품인지 모른다 → 채택 금지
            return ('<ns2:products xmlns:ns2="http://www.11st.co.kr">'
                    '<ns2:product><dispCtgrNo>19021</dispCtgrNo></ns2:product>'
                    '</ns2:products>')

    assert P.get_display_category_no('1', client=_C()) is None


def test_11번가_다중조회에_다른_상품이_섞여오면_그_행을_쓰지_않는다():
    from shared.platforms.eleven11 import products as P

    class _C:
        def request(self, method, path, body=None, **kw):
            if method == 'GET':
                return '<Product><prdNo>1</prdNo></Product>'
            return ('<ns2:products xmlns:ns2="http://www.11st.co.kr">'
                    '<ns2:product><prdNo>999</prdNo>'
                    '<dispCtgrNo>19021</dispCtgrNo></ns2:product></ns2:products>')

    assert P.get_display_category_no('1', client=_C()) is None
