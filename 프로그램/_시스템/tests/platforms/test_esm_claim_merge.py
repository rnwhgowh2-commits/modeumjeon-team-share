# -*- coding: utf-8 -*-
"""옥션·G마켓 주문내역에 클레임(취소·반품·교환·미수령)·입금확인중이 합쳐지는지.

이게 없으면 옥션·G마켓만 취소·반품이 빠진 채 집계돼, 취소·반품이 잡히는
다른 4개 마켓과 숫자 기준이 어긋난다(실증: 마켓 화면 환불완료 1건 ↔ 우리 0건).
"""
import datetime as _dt

from lemouton.markets import order_export as oe
from shared.platforms.esm import claims as _clm

UNTIL = _dt.datetime(2026, 7, 20, 12, 0)
SINCE = UNTIL - _dt.timedelta(days=7)
ORDERS_PATH = "/shipping/v1/Order/RequestOrders"


def _detail(order_no, name="정상상품", price="10000"):
    return {"OrderNo": order_no, "OrderDate": "2026-07-15T10:00:00", "GoodsName": name,
            "SalePrice": price, "ContrAmount": 1, "ReceiverName": "홍길동",
            "BuyerName": "홍길동", "SiteGoodsNo": "G1"}


class Client:
    """주문조회·주문번호조회·클레임조회를 한 번에 흉내내는 가짜 클라이언트."""

    def __init__(self, normal=(), cancels=(), returns=(), exchanges=(),
                 uncollected=(), pre=(), details=None):
        self._cfg = {"paths": {"orders": ORDERS_PATH}, "settle_srch_type": "D1"}
        self._normal, self._details = list(normal), dict(details or {})
        self._by_path = {
            _clm.PATHS["cancels"]: list(cancels),
            _clm.PATHS["returns"]: list(returns),
            _clm.PATHS["exchanges"]: list(exchanges),
            _clm.PATHS["uncollected"]: list(uncollected),
            _clm.PATHS["pre_orders"]: list(pre),
        }
        self._served = set()

    def post(self, path, body=None, **kw):
        body = body or {}
        if path == ORDERS_PATH:
            if body.get("orderStatus") == 0:            # 주문번호 단건 조회
                d = self._details.get(body.get("orderNo"))
                return {"ResultCode": 0, "Data": {"RequestOrders": [d] if d else []}}
            key = ("orders", body.get("orderStatus"), body.get("requestDateFrom"))
            if key in self._served:
                return {"ResultCode": 0, "Data": {"RequestOrders": []}}
            self._served.add(key)
            rows = self._normal if body.get("orderStatus") == 1 else []
            return {"ResultCode": 0, "Data": {"RequestOrders": rows,
                                              "TotalCount": len(rows)}}
        rows = self._by_path.get(path, [])
        key = (path, body.get("StartDate"), body.get("CancelStatus"),
               body.get("ReturnStatus"), body.get("ExchangeStatus"),
               body.get("requestDateFrom"))
        if key in self._served:
            rows = []
        else:
            self._served.add(key)
        if path == _clm.PATHS["pre_orders"]:
            return {"ResultCode": 0, "Data": {"RequestOrders": rows,
                                              "TotalCount": len(rows)}}
        return {"ResultCode": 0, "Data": rows}

    def request_orders(self, body):
        return self.post(ORDERS_PATH, body)

    def request_settlement(self, body):
        return {"ResultCode": 0, "Data": []}


def _rows(**kw):
    cli = Client(**kw)
    return oe.esm_order_rows("auction", SINCE, UNTIL, client=cli,
                             include_settlement=False)


def test_취소주문이_주문내역에_나온다():
    rows = _rows(normal=[_detail(1)],
                 cancels=[{"OrderNo": 2, "CancelStatus": 3}],
                 details={2: _detail(2, "취소된상품", "20000")})
    got = {r["오픈마켓주문번호"]: r for r in rows}
    assert 2 in got, "취소 주문이 빠졌다"
    assert got[2]["주문상태"] == "취소완료"
    assert got[2]["상품명"] == "취소된상품"       # 주문번호 조회로 상세를 채웠다
    assert got[2]["단가"] == "20000"


def test_반품_교환_미수령_입금확인중도_들어온다():
    rows = _rows(returns=[{"OrderNo": 11, "ReturnStatus": 4}],
                 exchanges=[{"OrderNo": 12, "ExchangeStatus": 1}],
                 uncollected=[{"OrderNo": 13}],
                 pre=[_detail(14, "입금대기상품")],
                 details={11: _detail(11), 12: _detail(12), 13: _detail(13)})
    st = {r["오픈마켓주문번호"]: r["주문상태"] for r in rows}
    assert st[11] == "반품완료"
    assert st[12] == "교환요청"
    assert st[13] == "미수령신고"
    assert st[14] == "입금확인중"


def test_클레임행은_change_로_태그된다():
    """태그가 없으면 CS(반품·교환·취소) 탭에 0건으로 뜬다."""
    rows = _rows(cancels=[{"OrderNo": 2, "CancelStatus": 3}], details={2: _detail(2)})
    c = [r for r in rows if r["오픈마켓주문번호"] == 2][0]
    assert c["_kind"] == "change"


def test_주문조회에_이미_있는_주문은_두_번_안_나온다():
    """같은 주문이 두 줄이면 매출·발송이 2배로 계상된다."""
    rows = _rows(normal=[_detail(5)], cancels=[{"OrderNo": 5, "CancelStatus": 1}],
                 details={5: _detail(5)})
    assert [r["오픈마켓주문번호"] for r in rows].count(5) == 1


def test_상세를_못_받아도_클레임을_버리지_않는다():
    """상품명이 비더라도 '취소 주문이 있다'는 사실은 남겨야 한다(조용한 누락 금지)."""
    rows = _rows(cancels=[{"OrderNo": 9, "CancelStatus": 3}], details={})
    got = [r for r in rows if r["오픈마켓주문번호"] == 9]
    assert len(got) == 1
    assert got[0]["주문상태"] == "취소완료"


def test_클레임_조회가_실패해도_정상주문은_살아있다():
    class Boom(Client):
        def post(self, path, body=None, **kw):
            if path.startswith("/claim/"):
                return {"ResultCode": 9, "Message": "권한 없음"}
            return super().post(path, body, **kw)

    rows = oe.esm_order_rows("auction", SINCE, UNTIL,
                             client=Boom(normal=[_detail(1)]),
                             include_settlement=False)
    assert [r["오픈마켓주문번호"] for r in rows] == [1]
