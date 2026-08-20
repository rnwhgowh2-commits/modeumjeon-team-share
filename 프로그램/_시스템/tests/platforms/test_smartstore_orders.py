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


# ── 주문조회 429 rate limit 재시도 (마진·주문내역 경로) ──────────────────────
# client.request 는 워커 requeue 를 위해 429 를 즉시 raise 한다. 주문조회 경로엔
# requeue 가 없으므로(=마켓 통째 markets_failed) fetch_orders 가 retry_after 만큼
# 쉬고 재시도해야 한다(2026-07-14 260714 실서버에서 스스 48건 누락으로 발각).
from shared.platforms.smartstore.client import SmartStoreRateLimitError


class FlakyClient:
    """앞의 n_429 번은 429, 그 뒤부터 정상 응답."""
    def __init__(self, n_429, ok_response, is_quota=False):
        self.n_429 = n_429
        self.ok = ok_response
        self.is_quota = is_quota
        self.calls = 0

    def request(self, method, path, query="", body=None):
        self.calls += 1
        if self.calls <= self.n_429:
            raise SmartStoreRateLimitError(retry_after_sec=5, is_quota=self.is_quota)
        return self.ok


def test_fetch_orders_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(om.time, "sleep", lambda *_: None)  # 실제 대기 제거
    fc = FlakyClient(n_429=2, ok_response=_page(["A", "B"]))
    since = dt.datetime(2026, 7, 1, 0, 0, tzinfo=KST)
    resp = om.fetch_orders(since, client=fc)
    assert fc.calls == 3  # 429×2 + 성공×1
    assert [r["productOrderId"] for r in resp["data"]["lastChangeStatuses"]] == ["A", "B"]


def test_fetch_orders_raises_after_retries_exhausted(monkeypatch):
    monkeypatch.setattr(om.time, "sleep", lambda *_: None)
    fc = FlakyClient(n_429=99, ok_response=_page([]))  # 항상 429
    since = dt.datetime(2026, 7, 1, 0, 0, tzinfo=KST)
    import pytest
    with pytest.raises(SmartStoreRateLimitError):
        om.fetch_orders(since, client=fc)
    assert fc.calls == om._ORDER_QUERY_429_RETRIES + 1  # 최초 + 재시도 상한


def test_fetch_orders_does_not_retry_quota_limit(monkeypatch):
    """일일 판매자 할당량 소진(GW.QUOTA_LIMIT)은 짧은 재시도로 안 풀린다 → 즉시 전파."""
    monkeypatch.setattr(om.time, "sleep", lambda *_: None)
    fc = FlakyClient(n_429=99, ok_response=_page([]), is_quota=True)
    since = dt.datetime(2026, 7, 1, 0, 0, tzinfo=KST)
    import pytest
    with pytest.raises(SmartStoreRateLimitError):
        om.fetch_orders(since, client=fc)
    assert fc.calls == 1  # 재시도 없이 즉시


def test_iter_changed_ids_retries_are_transparent(monkeypatch):
    """iter 경로도 429 재시도 후 정상 수집(윈도우·페이징과 무관하게 복원)."""
    monkeypatch.setattr(om.time, "sleep", lambda *_: None)
    fc = FlakyClient(n_429=1, ok_response=_page(["X", "Y"]))
    since = dt.datetime(2026, 7, 1, 0, 0, tzinfo=KST)
    until = dt.datetime(2026, 7, 1, 12, 0, tzinfo=KST)
    ids = om.iter_changed_product_order_ids(since, until, client=fc)
    assert ids == ["X", "Y"]
