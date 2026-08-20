# -*- coding: utf-8 -*-
"""마켓에 등록된 카테고리 — 목록 API 가 이미 주는데 버리던 값을 저장·표시.

PR#810 이 「마켓 캐시에 카테고리 컬럼이 없어 표시 안 함(날조 금지)」으로 남긴 칸.
지도(consult-market-map 게이트) 전수정독 결과 **5마켓은 지금 부르는 그 목록 응답에
카테고리가 실려 온다**. 롯데온만 응답에 필드 자체가 없다.

| 마켓 | 지도 API | 응답 필드 |
|---|---|---|
| 스마트스토어 | smartstore.search-product | categoryId · wholeCategoryName |
| 쿠팡 | coupang.products.product-list-paging-query | displayCategoryCode (이름 없음) |
| 옥션·G마켓 | auction/gmarket.esm.160 | category.site.{iac|gmkt}.{catCode,catName} |
| 11번가 | eleven11.39 | dispCtgrNo (이름 없음) |
| 롯데온 | lotteon.product.list | **없음** (spdNo·spdNm·slStatCd·승인상태뿐) |

🔴 새 API 호출 0 — 이미 부르는 응답에서 읽기만 한다.
"""
import json
import pathlib

import pytest

from lemouton.catalog import fetchers as F


# ── 지도가 진짜 그렇게 말하는지부터. 코드 주석이 아니라 SOT 를 본다 ──────────
_MAP = pathlib.Path(__file__).resolve().parents[2] / 'webapp' / 'data' / 'marketplace_api_map.json'


def _api(api_id):
    data = json.loads(_MAP.read_text(encoding='utf-8'))
    for a in data['apis']:
        if a.get('id') == api_id:
            return a
    raise AssertionError(f'지도에 {api_id} 가 없습니다')


@pytest.mark.parametrize('api_id,needle', [
    ('smartstore.search-product', 'wholeCategoryName'),
    ('coupang.products.product-list-paging-query', 'displayCategoryCode'),
    ('auction.esm.160', 'catCode'),
    ('gmarket.esm.160', 'catCode'),
    ('eleven11.39', 'dispCtgrNo'),
])
def test_지도가_그_마켓_응답에_카테고리가_있다고_말한다(api_id, needle):
    assert needle in json.dumps(_api(api_id), ensure_ascii=False)


def test_롯데온은_목록_응답에_카테고리가_없다고_지도에_적혀_있다():
    """🔴 이 근거가 사라지면 「마켓이 안 준다」는 화면 문구가 근거 없는 말이 된다."""
    traps = json.dumps(_api('lotteon.product.list').get('idTraps') or [],
                       ensure_ascii=False)
    assert '카테고리 필드가 응답에 없다' in traps


# ── 마켓별 파서 ────────────────────────────────────────────────────────
class _Fake:
    def __init__(self, resp):
        self.resp = resp

    def request(self, *a, **k):
        return self.resp


def test_스스는_카테고리_코드와_전체_경로명을_읽는다():
    page = F._smartstore(_Fake({'totalElements': 1, 'contents': [{'channelProducts': [{
        'channelProductNo': 111, 'name': '검사', 'statusType': 'SALE',
        'salePrice': 100, 'categoryId': '50002322',
        'wholeCategoryName': '패션의류>여성의류>티셔츠'}]}]}), 1)
    assert page.rows[0].category_code == '50002322'
    assert page.rows[0].category_name == '패션의류>여성의류>티셔츠'


def test_쿠팡은_코드만_읽고_이름은_지어내지_않는다():
    page = F._coupang(_Fake({'data': [{
        'sellerProductId': 222, 'sellerProductName': '검사',
        'statusName': '승인완료', 'displayCategoryCode': 77413}]}), 1,
        vendor_id='A0001')
    assert page.rows[0].category_code == '77413'
    assert page.rows[0].category_name is None, '쿠팡은 카테고리 이름을 안 준다'


def test_11번가는_그_행의_dispCtgrNo_만_쓴다(monkeypatch):
    monkeypatch.setattr(
        'shared.platforms.eleven11.products.search_products',
        lambda **k: [{'prdNo': '333', 'prdNm': '검사', 'selStatCd': '103',
                      'selPrc': '10000', 'dispCtgrNo': '19021',
                      'rootCtgrNo': '0'}])
    page = F._eleven11(_Fake({}), 1)
    assert page.rows[0].category_code == '19021'
    assert page.rows[0].category_name is None


def test_11번가_rootCtgrNo_는_카테고리로_쓰지_않는다(monkeypatch):
    """rootCtgrNo 는 「무시해도 되는 11번가 시스템 코드」(지도 원문)."""
    monkeypatch.setattr(
        'shared.platforms.eleven11.products.search_products',
        lambda **k: [{'prdNo': '334', 'prdNm': '검사', 'selStatCd': '103',
                      'rootCtgrNo': '77'}])
    page = F._eleven11(_Fake({}), 1)
    assert page.rows[0].category_code is None


def _esm_resp(cat):
    return {'data': {'totalItems': 1, 'items': [{
        'goodsNo': 'G1', 'goodsName': '검사',
        'siteGoodsNo': {'iac': 'F1', 'gmkt': 'M1'},
        'sellStatus': {'iac': '11', 'gmkt': '11'},
        'price': {'iac': 10000.0, 'gmkt': 10000.0},
        'category': cat}]}}


def test_ESM_은_사이트별_카테고리를_먼저_쓴다():
    cat = {'site': {'iac': {'catCode': 'A100', 'catName': '옥션 티셔츠'},
                    'gmkt': {'catCode': 'G200', 'catName': '지마켓 티셔츠'}},
           'esm': {'catCode': 'E999', 'catName': 'ESM 공용'}}
    a = F._esm('auction', _Fake(_esm_resp(cat)), 1)
    g = F._esm('gmarket', _Fake(_esm_resp(cat)), 1)
    assert (a.rows[0].category_code, a.rows[0].category_name) == ('A100', '옥션 티셔츠')
    assert (g.rows[0].category_code, g.rows[0].category_name) == ('G200', '지마켓 티셔츠')


def test_ESM_은_사이트별이_없으면_공용으로_떨어진다():
    cat = {'site': {'iac': {}, 'gmkt': {}},
           'esm': {'catCode': 'E999', 'catName': 'ESM 공용'}}
    a = F._esm('auction', _Fake(_esm_resp(cat)), 1)
    assert (a.rows[0].category_code, a.rows[0].category_name) == ('E999', 'ESM 공용')


def test_ESM_은_카테고리가_통째로_없어도_안_깨진다():
    a = F._esm('auction', _Fake(_esm_resp(None)), 1)
    assert a.rows[0].category_code is None and a.rows[0].category_name is None


def test_롯데온은_카테고리를_비워_둔다():
    """🔴 목록 응답에 필드가 없다 — 지어내면 안 된다."""
    page = F._lotteon(_Fake({'returnCode': '0000', 'dataCount': 1, 'data': [
        {'spdNo': 'LO1', 'spdNm': '검사', 'slStatCd': '11'}]}), 1)
    assert page.rows[0].category_code is None
    assert page.rows[0].category_name is None


@pytest.mark.parametrize('bad', [None, '', '0', 0, 'None', 'null', '  '])
def test_쓸모없는_코드는_None_이다(bad):
    """🔴 str(None) 이 'None' 이라는 **가짜 코드**가 되어 화면에 뜨면 안 된다."""
    assert F._code(bad) is None


# ── 저장 → 화면까지 ───────────────────────────────────────────────────
def test_저장하고_준_마켓만_덮는다(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    appmod.create_app()
    from shared.db import SessionLocal
    from lemouton.catalog.fetchers import CatalogRow
    from lemouton.catalog.repository import upsert_rows
    from lemouton.catalog.models import MarketProduct
    s = SessionLocal()
    try:
        upsert_rows(s, 'smartstore', '카테고리검사계정', [CatalogRow(
            market_product_id='CAT-1', name='카테고리 검사', status='sale',
            category_code='50002322', category_name='패션의류>티셔츠')])
        m = (s.query(MarketProduct)
             .filter_by(market='smartstore', account_key='카테고리검사계정').first())
        assert m.category_code == '50002322'
        assert m.category_name == '패션의류>티셔츠'
        # 🔴 카테고리를 안 주는 훑기가 뒤에 와도 이미 채운 값을 지우지 않는다
        upsert_rows(s, 'smartstore', '카테고리검사계정', [CatalogRow(
            market_product_id='CAT-1', name='카테고리 검사', status='sale')])
        s.refresh(m)
        assert m.category_code == '50002322', '안 준 훑기가 값을 도로 지우면 안 된다'
    finally:
        s.close()
