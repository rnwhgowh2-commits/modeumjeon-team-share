# -*- coding: utf-8 -*-
"""ESM 상품 목록 조회 — 검색·상태 조건은 반드시 `query` 객체 안에 넣는다.

왜 이 테스트가 있나 (2026-07-23 라이브 실측):
    ESM(옥션·G마켓)의 POST /item/v1/goods/search 는 조건을 **최상위에 두면 에러 없이
    통째로 무시**하고 전체를 돌려준다. 조용한 실패라 호출한 쪽은 「걸러졌다」고 믿는다.

    같은 계정에서 실측한 값:
        · 최상위 sellStatus=11  → totalItems 3260 (= 조건없음과 동일, 무시됨)
        · query.sellStatus=[11] → totalItems 3150  ← 제대로 걸러짐
        · query.sellStatus=[21] → 109 / [31] → 0
        · query.keyword="니트"  → 46 / 없는 낱말 → 0
        · query.siteId=[1] 옥션 → 1605 / [2] 지마켓 → 1655 (합 3260)

    이 무시가 실제로 낸 손해:
        · registration/send_more.py 는 「판매중(11) 기존 상품」에서 출하지·발송정책 등
          선행자원을 베껴 온다. 필터가 무시되면 **판매중지 상품을 본보기로 집을 수 있다**.
        · live_send_test.py 는 「ESM keyword 는 무시된다」고 결론짓고 5,000건을 10페이지
          훑어 이름을 거르는 우회로를 넣었다(22초). 원인은 우리 요청 모양이었다.

    지도 근거: 판매처 > 데이터 코드 지도 > 옥션/G마켓 「상품 목록 조회 API」 example —
        {"query": {"sellStatus": [11]}, "pageIndex": 1, "pageSize": 10}
    sellStatus·siteId·goodsNo 등은 **배열**이고, keyword 만 문자열이다.
"""
from __future__ import annotations

import pytest

from shared.platforms.esm.products import search_goods


class _FakeClient:
    """request(method, path, body) 를 기록하고 정해진 응답을 돌려주는 가짜 클라이언트."""

    def __init__(self, response=None):
        self.calls = []
        self._response = response if response is not None else {
            "resultCode": "0000", "totalItems": 7, "pageIndex": 1, "pageSize": 100,
            "items": [],
        }

    def request(self, *, method, path, body=None, **kw):
        self.calls.append({"method": method, "path": path, "body": body})
        return self._response


def _call(**kw):
    c = _FakeClient()
    search_goods(client=c, **kw)
    return c.calls[0]["body"]


def test_판매상태는_query_안에_배열로_들어간다():
    body = _call(sell_status="11", page_size=100)
    assert "sellStatus" not in body, "최상위에 두면 ESM 이 조용히 무시한다"
    assert body["query"]["sellStatus"] == [11], "배열이어야 하고 숫자여야 한다"


def test_검색어는_query_안에_문자열로_들어간다():
    body = _call(keyword="니트")
    assert "keyword" not in body
    assert body["query"]["keyword"] == "니트"


@pytest.mark.parametrize("market,site_id", [("auction", 1), ("gmarket", 2)])
def test_사이트구분도_query_안에_배열로(market, site_id):
    body = _call(market=market)
    assert "siteId" not in body
    assert body["query"]["siteId"] == [site_id]


def test_페이지_정보는_최상위에_남는다():
    """pageIndex·pageSize 는 query 밖이다 — 지도 example 그대로."""
    body = _call(page_index=3, page_size=500)
    assert body["pageIndex"] == 3
    assert body["pageSize"] == 500
    assert "pageIndex" not in body.get("query", {})


def test_조건이_하나도_없으면_query_를_보내지_않는다():
    """빈 query 를 보내 ESM 이 어떻게 해석할지 모험하지 않는다."""
    body = _call()
    assert "query" not in body


def test_조건_여러개는_한_query_에_모인다():
    body = _call(market="auction", sell_status="11", keyword="니트")
    assert body["query"] == {"siteId": [1], "sellStatus": [11], "keyword": "니트"}


def test_숫자가_아닌_판매상태는_문자열_그대로_배열에():
    """ESM 이 나중에 문자 코드를 쓰더라도 깨지지 않게 — 숫자면 숫자, 아니면 그대로."""
    body = _call(sell_status="A1")
    assert body["query"]["sellStatus"] == ["A1"]


def test_pageSize_상한_500_은_그대로_지킨다():
    body = _call(page_size=9999)
    assert body["pageSize"] == 500
