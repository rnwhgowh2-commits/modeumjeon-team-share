# -*- coding: utf-8 -*-
"""스마트스토어 건별 정산 내역 조회 모듈 — Mock 단위테스트.

라이브 미검증(서버 IP 등록 필요). 여기선 요청 파라미터 구성 + 응답 파싱 + 페이징 +
정산예정금액(settleExpectAmount) 집계를 Mock client 로 검증.
스펙 근거: API 센터 실측 2026-07-06 (find-settle-by-case-pay-settle).
"""
from shared.platforms.smartstore import settlements as st


class FakeClient:
    """SmartStoreClient 대역 — request() 호출 기록 + 미리 준비한 페이지 반환."""

    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    def request(self, method, path, query="", body=None):
        self.calls.append({"method": method, "path": path, "query": query})
        # pageNumber 파라미터로 해당 페이지 반환 (없으면 첫 페이지)
        idx = 0
        for part in query.split("&"):
            if part.startswith("pageNumber="):
                idx = int(part.split("=", 1)[1]) - 1
        return self._pages[idx]


def _page(elements, page, total_pages):
    return {"elements": elements, "pagination": {
        "page": page, "size": 1000, "totalPages": total_pages, "totalElements": 99}}


def test_fetch_page_builds_required_query():
    fc = FakeClient([_page([], 1, 1)])
    st.fetch_settle_by_case_page(page_number=1, page_size=500,
                                 search_date="2026-07-01", client=fc)
    call = fc.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/external/v1/pay-settle/settle/case"
    # 필수 파라미터 pageNumber·pageSize + searchDate 포함
    assert "pageNumber=1" in call["query"]
    assert "pageSize=500" in call["query"]
    assert "searchDate=2026-07-01" in call["query"]
    # 기본 periodType 은 fetch_page 에선 안 붙음(None) — iter 가 채움
    assert "periodType=" not in call["query"]


def test_none_params_omitted():
    fc = FakeClient([_page([], 1, 1)])
    st.fetch_settle_by_case_page(page_number=1, client=fc)
    q = fc.calls[0]["query"]
    assert "orderId=" not in q and "settleType=" not in q  # None 은 빠짐


def test_iter_paginates_all_pages():
    p1 = _page([{"productOrderId": "A", "settleExpectAmount": 100}], 1, 2)
    p2 = _page([{"productOrderId": "B", "settleExpectAmount": 200}], 2, 2)
    fc = FakeClient([p1, p2])
    rows = list(st.iter_settle_by_case(search_date="2026-07-01", client=fc))
    assert [r["productOrderId"] for r in rows] == ["A", "B"]
    assert len(fc.calls) == 2                      # 2페이지 모두 조회
    assert "periodType=SETTLE_CASEBYCASE_SETTLE_SCHEDULE_DATE" in fc.calls[0]["query"]


def test_iter_stops_on_last_page():
    fc = FakeClient([_page([{"productOrderId": "A", "settleExpectAmount": 1}], 1, 1)])
    rows = list(st.iter_settle_by_case(client=fc))
    assert len(rows) == 1 and len(fc.calls) == 1   # totalPages=1 → 1회만


def test_settle_expect_sums_by_product_order():
    # 같은 상품주문 A 에 상품행(1000)+배송비행(300) → 합산 1300
    p1 = _page([
        {"productOrderId": "A", "settleExpectAmount": 1000, "productOrderType": "PROD_ORDER"},
        {"productOrderId": "A", "settleExpectAmount": 300,  "productOrderType": "DELIVERY"},
        {"productOrderId": "B", "settleExpectAmount": 500,  "productOrderType": "PROD_ORDER"},
    ], 1, 1)
    fc = FakeClient([p1])
    m = st.settle_expect_by_product_order(search_date="2026-07-01", client=fc)
    assert m == {"A": 1300, "B": 500}


def test_settle_expect_skips_missing_amount():
    # settleExpectAmount 없는 행은 폴백 0 대입 없이 건너뜀(추측 금지)
    p1 = _page([
        {"productOrderId": "A", "settleExpectAmount": 700},
        {"productOrderId": "C"},                       # 금액 없음 → 무시
        {"settleExpectAmount": 900},                   # productOrderId 없음 → 무시
    ], 1, 1)
    fc = FakeClient([p1])
    m = st.settle_expect_by_product_order(client=fc)
    assert m == {"A": 700}                             # C 는 키 자체가 없음
