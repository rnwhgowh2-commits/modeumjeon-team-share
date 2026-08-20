# -*- coding: utf-8 -*-
"""마켓별 목록 가져오기 — 마켓 차이를 여기서 다 흡수한다.

실측 근거(2026-07-23, GitHub Actions 「상품관리 실측(수동)」 script=1/2/3):
  · 스마트스토어 totalElements / 롯데온 dataCount / ESM totalItems 는 총건수를 준다
  · 쿠팡·11번가는 총건수 필드가 없다 → 끝까지 넘겨야 센다
  · ESM 조건은 `query` 객체 안에 넣어야 한다(밖에 두면 조용히 무시)
  · 롯데온 상품명은 &lt;매장정품&gt; 처럼 HTML 이스케이프로 온다
"""
import pytest

from lemouton.catalog.fetchers import CatalogRow, fetch_page, PAGE_SIZE


class _Fake:
    """request(...) 를 기록하고 정해진 응답을 돌려주는 가짜 클라이언트."""

    def __init__(self, responses):
        self._r = list(responses)
        self.calls = []

    def request(self, *a, **kw):
        self.calls.append(kw or (a and {'args': a}) or {})
        if not self._r:
            raise AssertionError('예상 못 한 추가 호출')
        return self._r.pop(0)


def test_공통행은_필요한_것만_담는다():
    r = CatalogRow(market_product_id='LO1', name='가', status='sale',
                   raw_status='SALE', sale_price=31900)
    assert r.market_product_id == 'LO1'
    assert r.site_product_id is None
    assert r.brand is None


def test_롯데온_상품명의_HTML_이스케이프를_풀어_담는다():
    """★ 안 풀면 「매장정품」으로 검색해도 안 걸린다."""
    fake = _Fake([{
        'returnCode': '0000', 'dataCount': 10581,
        'data': [{'spdNo': 'LO2727575855',
                  'spdNm': '&lt;매장정품&gt; 아디다스골프 썬 햇 모자',
                  'slStatCd': 'SALE'}],
    }])
    page = fetch_page('lotteon', fake, page_index=1)
    assert page.rows[0].name == '<매장정품> 아디다스골프 썬 햇 모자'
    assert page.total == 10581
    assert page.rows[0].status == 'sale'
    assert page.rows[0].raw_status == 'SALE'


def test_롯데온은_페이지_번호가_필수다():
    """★ pageNo·rowsPerPage 를 빼면 returnCode 9000('처리 중 오류')이 난다."""
    fake = _Fake([{'returnCode': '0000', 'dataCount': 0, 'data': []}])
    fetch_page('lotteon', fake, page_index=3)
    body = fake.calls[0]['body']
    assert body['pageNo'] == 3
    assert body['rowsPerPage'] == PAGE_SIZE['lotteon']


def test_ESM_조건은_query_객체_안에_들어간다():
    """★ 최상위에 두면 ESM 이 에러 없이 조건을 버리고 전체를 돌려준다."""
    fake = _Fake([{'totalItems': 1605, 'items': []}])
    fetch_page('auction', fake, page_index=1)
    body = fake.calls[0]['body']
    assert body['query']['siteId'] == [1]
    assert 'siteId' not in body


def test_ESM_은_사이트별_상품번호를_따로_담는다():
    """옥션·G마켓은 마스터번호가 공용이라 사이트 번호가 따로 필요하다."""
    payload = {'totalItems': 1, 'items': [{
        'goodsNo': 2414582618, 'goodsName': '필라 페이토 샌들',
        'sellStatus': '11', 'siteGoodsNo': {'iac': 'A1234', 'gmkt': 'G9999'},
    }]}
    page = fetch_page('auction', _Fake([payload]), page_index=1)
    assert page.rows[0].market_product_id == '2414582618'
    assert page.rows[0].site_product_id == 'A1234'

    page2 = fetch_page('gmarket', _Fake([payload]), page_index=1)
    assert page2.rows[0].site_product_id == 'G9999'


def test_총건수를_안_주는_마켓은_total_이_None():
    """★ 쿠팡·11번가 — 0 으로 만들면 '상품 없음'으로 보인다."""
    fake = _Fake([{'code': 'SUCCESS', 'data': [], 'nextToken': None}])
    page = fetch_page('coupang', fake, page_index=1, vendor_id='A01472651')
    assert page.total is None


def test_쿠팡은_다음_페이지_열쇠를_돌려준다():
    fake = _Fake([{'code': 'SUCCESS', 'nextToken': 'TK2', 'data': [{
        'sellerProductId': 123, 'sellerProductName': '조던 팬츠',
        'statusName': 'APPROVED', 'brand': '나이키',
    }]}])
    page = fetch_page('coupang', fake, page_index=1, vendor_id='A01472651')
    assert page.next_token == 'TK2'
    assert page.rows[0].market_product_id == '123'
    assert page.rows[0].brand == '나이키'


def test_스마트스토어는_채널상품번호를_쓴다():
    """사장님이 셀러센터에서 보는 번호 = channelProductNo."""
    fake = _Fake([{'totalElements': 6520, 'contents': [{
        'originProductNo': 111,
        'channelProducts': [{'channelProductNo': 999, 'name': '썬 햇',
                             'statusType': 'SALE', 'salePrice': 31900,
                             'channelServiceType': 'STOREFARM'}],
    }]}])
    page = fetch_page('smartstore', fake, page_index=1)
    assert page.rows[0].market_product_id == '999'
    assert page.rows[0].sale_price == 31900
    assert page.total == 6520


def test_11번가_상품명과_판매상태를_담는다(monkeypatch):
    """search_products 는 XML 을 파싱하므로 그 결과를 직접 흉내낸다."""
    import lemouton.catalog.fetchers as F
    monkeypatch.setattr(
        'shared.platforms.eleven11.products.search_products',
        lambda **kw: [{'prdNo': '4821003942', 'prdNm': '아디다스골프 썬햇',
                       'selStatCd': '103', 'selPrc': '32900'}])
    page = F.fetch_page('eleven11', object(), page_index=1)
    assert page.rows[0].market_product_id == '4821003942'
    assert page.rows[0].status == 'sale'
    assert page.rows[0].sale_price == 32900
    assert page.total is None


def test_모르는_마켓은_바로_알려준다():
    with pytest.raises(ValueError, match='모르는 마켓'):
        fetch_page('없는마켓', _Fake([]), page_index=1)


# ── [2026-07-24 라이브 실측 정정] ESM 은 값을 사이트별 묶음으로 준다 ────────
#   실제 응답: sellStatus={'gmkt':None,'iac':'22'} · price={'gmkt':0.0,'iac':70600.0}
#             stock={'gmkt':0,'iac':60} · brand={'id':0,'name':None}
#   통째로 문자열화했더니 라이브 1,605건이 전부 상태 unknown 으로 저장됐다.
_ESM_REAL = {'totalItems': 2, 'items': [{
    'goodsNo': 5806568636,
    'siteGoodsNo': {'gmkt': None, 'iac': 'F292819719'},
    'goodsName': '매장정품 필라 휠라 FILA 페이토 샌들',
    'sellStatus': {'gmkt': None, 'iac': '22'},
    'price': {'gmkt': 0.0, 'iac': 70600.0},
    'stock': {'gmkt': 0, 'iac': 60},
    'brand': {'id': 0, 'name': '휠라'},
}]}


def test_ESM_상태는_사이트별_묶음에서_꺼낸다():
    """★ 통째로 쓰면 unknown 이 된다 — 옥션이면 iac, 지마켓이면 gmkt."""
    page = fetch_page('auction', _Fake([_ESM_REAL]), page_index=1)
    assert page.rows[0].raw_status == '22'
    assert page.rows[0].status == 'stopped'      # 22 = 직권중지


def test_ESM_판매가도_사이트별_묶음에서_꺼낸다():
    """70600.0 처럼 소수점으로 온다 — 숫자로 바꿔 담는다."""
    page = fetch_page('auction', _Fake([_ESM_REAL]), page_index=1)
    assert page.rows[0].sale_price == 70600


def test_ESM_브랜드는_묶음_안_이름이다():
    page = fetch_page('auction', _Fake([_ESM_REAL]), page_index=1)
    assert page.rows[0].brand == '휠라'


def test_ESM_그_사이트에_없는_상품은_건너뛴다():
    """★ 옥션에만 있는 상품을 지마켓 목록에 넣으면 지마켓 건수가 부푼다."""
    page = fetch_page('gmarket', _Fake([_ESM_REAL]), page_index=1)
    assert page.rows == []
    assert page.total == 2      # 총건수는 마켓이 준 값 그대로 남긴다


def test_ESM_값이_묶음이_아니어도_읽는다():
    """마켓이 나중에 평평한 값으로 바꿔도 안 깨지게."""
    flat = {'totalItems': 1, 'items': [{
        'goodsNo': 1, 'goodsName': '가', 'sellStatus': '11',
        'siteGoodsNo': 'A1', 'price': 1000, 'brand': '나이키'}]}
    page = fetch_page('auction', _Fake([flat]), page_index=1)
    assert page.rows[0].status == 'sale'
    assert page.rows[0].sale_price == 1000
    assert page.rows[0].brand == '나이키'
    assert page.rows[0].site_product_id == 'A1'
