# -*- coding: utf-8 -*-
"""스마트스토어 주문 목록(변경 상품주문 내역) 조회 — Mock 단위테스트.

실측 스펙(2026-07-07 실계정 검증): GET .../product-orders/last-changed-statuses,
lastChangedFrom 필수, data.lastChangeStatuses[].productOrderId, 300개 초과 시 data.more.
2026-07-07 이전 코드는 잘못된 엔드포인트(startDate/searchType)를 호출해 HTTP 400 [4000] 발생 → 정정.
"""
import datetime as dt

from shared.platforms.smartstore import orders as om

KST = dt.timezone(dt.timedelta(hours=9))


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, path, query="", body=None):
        self.calls.append({"method": method, "path": path, "query": query, "body": body})
        return self._responses.pop(0) if self._responses else {"data": {}}


def _page(ids, more_from=None, more_seq=None):
    data = {"lastChangeStatuses": [{"productOrderId": i} for i in ids]}
    if more_from:
        data["more"] = {"moreFrom": more_from, "moreSequence": more_seq}
    return {"data": data}


def test_fetch_orders_uses_last_changed_endpoint():
    fc = FakeClient([_page([])])
    since = dt.datetime(2026, 7, 1, 0, 0, tzinfo=KST)
    om.fetch_orders(since, client=fc)
    call = fc.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/external/v1/pay-order/seller/product-orders/last-changed-statuses"
    # lastChangedFrom 필수 파라미터 포함, 옛 파라미터는 없어야 함
    assert "lastChangedFrom=2026-07-01" in call["query"]
    assert "startDate=" not in call["query"] and "searchType=" not in call["query"]


def test_fetch_orders_omits_none_to_and_defaults_limit():
    fc = FakeClient([_page([])])
    om.fetch_orders(dt.datetime(2026, 7, 1, tzinfo=KST), client=fc)
    q = fc.calls[0]["query"]
    assert "lastChangedTo=" not in q          # 생략 시 안 붙음(+24h 자동)
    assert "limitCount=300" in q


def test_iter_collects_ids_across_more_pagination():
    # 한 24h 윈도우 안에서 more 로 2페이지 이어받기
    pages = [
        _page(["A", "B"], more_from="2026-07-01T12:00:00.000+09:00", more_seq="s1"),
        _page(["C"]),                          # more 없음 → 윈도우 종료
    ]
    fc = FakeClient(pages)
    since = dt.datetime(2026, 7, 1, 0, 0, tzinfo=KST)
    until = dt.datetime(2026, 7, 1, 20, 0, tzinfo=KST)   # 20h → 윈도우 1개
    ids = om.iter_changed_product_order_ids(since, until, client=fc)
    assert ids == ["A", "B", "C"]
    # 2번째 호출은 more 로 이어받아 moreSequence 전달
    assert "moreSequence=s1" in fc.calls[1]["query"]
    # more.moreFrom 을 다음 요청 lastChangedFrom 으로 전달(콜론은 URL 인코딩됨)
    assert "lastChangedFrom=2026-07-01T12" in fc.calls[1]["query"]


def test_iter_dedupes_across_windows():
    # 7일 범위 → 24h 윈도우 여러 개. 중복 productOrderId 는 한 번만.
    fc = FakeClient([_page(["A"]), _page(["A", "B"]), _page([]),
                     _page([]), _page([]), _page([]), _page([])])
    since = dt.datetime(2026, 7, 1, tzinfo=KST)
    until = dt.datetime(2026, 7, 8, tzinfo=KST)          # 7일 → 7 윈도우
    ids = om.iter_changed_product_order_ids(since, until, client=fc)
    assert ids == ["A", "B"]                              # 중복 제거
    assert len(fc.calls) == 7                             # 윈도우당 1회(more 없음)


def test_order_detail_endpoint_unchanged():
    fc = FakeClient([{"data": []}])
    om.fetch_order_detail(["X", "Y"], client=fc)
    call = fc.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/external/v1/pay-order/seller/product-orders/query"
    assert call["body"] == {"productOrderIds": ["X", "Y"]}
