# -*- coding: utf-8 -*-
"""롯데온 출고/회수지시(주문정보) 조회 — Mock 단위테스트.

스펙: API 센터 실측 2026-07-07(apiNo=209). POST SellerDeliveryOrdersSearch,
srchStrtDt/srchEndDt(1일 이내), data.deliveryOrderList[]. 라이브 미검증(키 서버에만).
"""
import datetime as dt

from shared.platforms.lotteon import orders as lo

KST = dt.timezone(dt.timedelta(hours=9))


class FakeClient:
    def __init__(self, pages):
        self._pages = list(pages)
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append({"method": method, "path": path, "body": body})
        return self._pages.pop(0) if self._pages else {"data": {"deliveryOrderList": []}}


def _resp(order_ids):
    return {"returnCode": "0000",
            "data": {"deliveryOrderList": [{"odNo": o, "spdNm": "코트"} for o in order_ids]}}


def test_fetch_uses_delivery_endpoint_and_body():
    fc = FakeClient([_resp([])])
    lo.fetch_delivery_orders("20260701000000", "20260701235959",
                             if_cpl_yn="", tr_no="TR9", client=fc)
    call = fc.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/v1/openapi/delivery/v1/SellerDeliveryOrdersSearch"
    b = call["body"]
    assert b["srchStrtDt"] == "20260701000000" and b["srchEndDt"] == "20260701235959"
    assert b["trGrpCd"] == "SR"            # 일반셀러 상수 기본
    assert b["trNo"] == "TR9"
    assert "ifCplYN" in b                  # 연동완료여부 파라미터 존재


def test_iter_windows_one_day_each():
    # 3일 범위 → 하루 윈도우 3회 (조회기간 1일 초과 불가 제약)
    fc = FakeClient([_resp(["A"]), _resp(["B"]), _resp(["C"])])
    since = dt.datetime(2026, 7, 1, tzinfo=KST)
    until = dt.datetime(2026, 7, 4, tzinfo=KST)
    got = [o["odNo"] for o in lo.iter_delivery_orders(since, until, client=fc)]
    assert got == ["A", "B", "C"]
    assert len(fc.calls) == 3
    # 각 구간 종료가 시작+1일 미만(1일 초과 방지)
    for c in fc.calls:
        assert c["body"]["srchStrtDt"][:8] != "" and c["body"]["srchEndDt"][:8] != ""


def test_iter_handles_empty_and_missing_data():
    fc = FakeClient([{"returnCode": "0000", "data": {}}, {"returnCode": "0000"}])
    since = dt.datetime(2026, 7, 1, tzinfo=KST)
    until = dt.datetime(2026, 7, 3, tzinfo=KST)
    assert list(lo.iter_delivery_orders(since, until, client=fc)) == []   # 빈 응답 안전


def test_order_rows_merges_claims():
    """취소/반품/교환(claimservice)이 출고/회수지시 활성주문과 병합되는지 (MCP 실측 스펙)."""
    from lemouton.markets import order_export as oe

    def _claim(odno, item):
        return {"returnCode": "0000",
                "data": [{"odNo": odno, "clmNo": "C1", "itemList": [item]}]}

    class RouteClient:
        def request(self, method, path, body=None):
            if "/delivery/" in path:
                return {"data": {"deliveryOrderList": [
                    {"odNo": "OD_ACTIVE", "spdNm": "활성상품", "odQty": "1",
                     "slPrc": "10000", "odPrgsStepCd": "11", "odCmptDttm": "20260705100000"}]}}
            if "cancellationOpenApi" in path:
                return _claim("OD_CANCEL", {"odSeq": 1, "procSeq": 1, "spdNm": "취소상품",
                              "sitmNm": "옵A", "odQty": "1", "itmSlPrc": "5000",
                              "cnclQty": "1", "clmRsnCnts": "변심", "odAccpDttm": "20260705120000"})
            if "returningOpenApi" in path:
                return _claim("OD_RETURN", {"odSeq": 1, "procSeq": 1, "spdNm": "반품상품",
                              "sitmNm": "옵B", "rtngQty": "2", "itmSlPrc": "7000",
                              "odAccpDttm": "20260705120000"})
            if "exchangeOpenApi" in path:
                return _claim("OD_EXCHANGE", {"odSeq": 1, "procSeq": 1, "spdNm": "교환상품",
                              "xchgQty": "1", "odAccpDttm": "20260705120000"})
            return {"data": {}}

    since = dt.datetime(2026, 7, 5, tzinfo=KST)
    until = dt.datetime(2026, 7, 6, tzinfo=KST)
    rows = oe.lotteon_order_rows(since, until, client=RouteClient())
    st = {r["주문상태"] for r in rows}
    # 주문상태 통일(2026-07-10): 클레임 접수는 '취소요청·반품요청·교환요청'(완료와 구분).
    assert {"취소요청", "반품요청", "교환요청"} <= st
    cx = [r for r in rows if r["주문상태"] == "취소요청"][0]
    assert cx["오픈마켓주문번호"] == "OD_CANCEL" and cx["상품명"] == "취소상품" and cx["수량"] == "1"
    rx = [r for r in rows if r["주문상태"] == "반품요청"][0]
    assert rx["상품명"] == "반품상품" and rx["수량"] == "2"
