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
    """가장 중요한 것 — 취소 주문이 목록에 뜬다는 사실 자체."""
    rows = _rows(normal=[_detail(1)],
                 cancels=[{"OrderNo": 2, "CancelStatus": 3}],
                 details={2: _detail(2, "취소된상품", "20000")})
    got = {r["오픈마켓주문번호"]: r for r in rows}
    assert 2 in got, "취소 주문이 빠졌다"
    assert got[2]["주문상태"] == "취소완료"
    assert 1 in got and got[1]["상품명"] == "정상상품"   # 일반 주문은 그대로


def test_주문번호조회를_켜면_상세로_단가까지_채운다(monkeypatch):
    """마켓이 훗날 클레임 주문 상세를 돌려주기 시작하면 이 경로가 살아난다.
    지금은 세 모양 모두 0건이라 꺼둔 상태."""
    from lemouton.markets import order_export as _oe
    monkeypatch.setattr(_oe, "_ESM_CLAIM_ORDER_LOOKUP", True)
    rows = _rows(cancels=[{"OrderNo": 2, "CancelStatus": 3}],
                 details={2: _detail(2, "취소된상품", "20000")})
    c = [r for r in rows if r["오픈마켓주문번호"] == 2][0]
    assert c["상품명"] == "취소된상품" and c["단가"] == "20000"


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


def test_클레임이_많으면_보강은_생략해도_주문은_유지된다(monkeypatch):
    """보강 호출이 폭증하면 응답이 30초를 넘어 게이트웨이가 502 로 끊는다.
    상한을 넘어도 **주문 자체는 반드시 나와야 한다** — 상품명이 비는 것보다
    주문이 사라지는 게 훨씬 위험하다."""
    from lemouton.markets import order_export as _oe
    monkeypatch.setattr(_oe, "_ESM_DETAIL_BUDGET", 2)
    many = [{"OrderNo": 100 + i, "CancelStatus": 3} for i in range(6)]
    rows = _rows(cancels=many, details={100 + i: _detail(100 + i) for i in range(6)})
    got = [r for r in rows if str(r["오픈마켓주문번호"]).startswith("10")]
    assert len(got) == 6                       # 6건 모두 살아 있다
    skipped = [r for r in rows if "상한 초과" in str(r.get("_detail_missing") or "")]
    assert len(skipped) == 4                   # 예산 2건만 보강, 나머지는 생략 표시


def test_같은_상품은_상품API를_한_번만_부른다(monkeypatch):
    """호출 절약 — 클레임이 같은 상품이면 상품명을 재조회할 이유가 없다."""
    from lemouton.markets import order_export as _oe
    calls = []

    def _fill(market, sgn, *, client, goods_no=None):
        calls.append(sgn)
        return "상품X", None

    monkeypatch.setattr("shared.platforms.esm.orders.fill_from_product", _fill)
    cancels = [{"OrderNo": 200 + i, "CancelStatus": 3, "SiteGoodsNo": "SAME"}
               for i in range(3)]
    _rows(cancels=cancels, details={})          # 주문번호 조회는 전부 실패 → 상품API 경로
    assert calls == ["SAME"]                    # 3건인데 1회만


# ── 클레임 사유 표시 ──────────────────────────────────────────────────────
#  마켓 취소관리 화면엔 「구매자 귀책 / 재고부족(품절)」처럼 사유가 보이는데
#  우리 주문내역엔 없었다. CS 대응에 바로 쓰이는 정보다.

def test_취소사유가_배송메시지에_사람말로_들어간다():
    rows = _rows(cancels=[{"OrderNo": 2, "CancelStatus": 3, "Reason": 0, "ReasonCode": 6}],
                 details={2: _detail(2)})
    c = [r for r in rows if r["오픈마켓주문번호"] == 2][0]
    assert c["배송메시지"] == "판매자 귀책 · 재고없음(판매자요청)"


def test_상세사유_문구가_있으면_뒤에_붙는다():
    rows = _rows(cancels=[{"OrderNo": 2, "CancelStatus": 3, "Reason": 1,
                           "ReasonCode": 1, "ReasonDetail": "색상이 달라요"}],
                 details={2: _detail(2)})
    c = [r for r in rows if r["오픈마켓주문번호"] == 2][0]
    assert c["배송메시지"] == "구매자 귀책 · 단순변심 · 색상이 달라요"


def test_반품은_취소와_다른_사유표를_쓴다():
    """코드 6 이 취소는 '재고없음(판매자요청)', 반품은 '판매자 요청' 이다.
    표를 섞으면 엉뚱한 사유가 찍힌다."""
    rows = _rows(returns=[{"OrderNo": 3, "ReturnStatus": 4, "Reason": 0, "ReasonCode": 6}],
                 details={3: _detail(3)})
    r = [x for x in rows if x["오픈마켓주문번호"] == 3][0]
    assert r["배송메시지"] == "판매자 귀책 · 판매자 요청"


def test_모르는_사유코드는_숫자를_남긴다():
    """임의로 해석하면 틀린 사유가 찍힌다 — 모르면 모른다고 둔다."""
    rows = _rows(cancels=[{"OrderNo": 4, "CancelStatus": 3, "Reason": 9, "ReasonCode": 99}],
                 details={4: _detail(4)})
    c = [r for r in rows if r["오픈마켓주문번호"] == 4][0]
    assert c["배송메시지"] == "귀책코드9 · 사유코드99"


def test_일반주문의_배송메시지는_그대로다():
    """클레임 사유가 일반 주문의 배송 요청사항을 덮으면 안 된다."""
    normal = {**_detail(1), "DelMemo": "부재시 경비실"}
    rows = _rows(normal=[normal])
    assert [r for r in rows if r["오픈마켓주문번호"] == 1][0]["배송메시지"] == "부재시 경비실"


def test_클레임은_주문번호조회를_건너뛰고_상품API로_간다(monkeypatch):
    """세 모양 모두 0건임을 라이브로 확인했다. 계속 두드리면 응답이 30초를 넘어
    게이트웨이가 502 로 끊어 사장님이 검증을 아예 못 한다."""
    from lemouton.markets import order_export as _oe
    called = []
    monkeypatch.setattr("shared.platforms.esm.orders.fetch_by_order_no",
                        lambda *a, **k: called.append(1) or (None, "x"))
    monkeypatch.setattr("shared.platforms.esm.orders.fill_from_product",
                        lambda m, s, *, client, goods_no=None: ("상품Z", None))
    rows = _rows(cancels=[{"OrderNo": 9, "CancelStatus": 3, "SiteGoodsNo": "S9"}])
    assert called == []                              # 주문번호 조회 안 함
    got = [r for r in rows if r["오픈마켓주문번호"] == 9][0]
    assert got["상품명"] == "상품Z"                    # 상품 API 로는 채운다


def test_기타코드는_상세문구가_있으면_생략한다():
    """라이브 실측: ReasonCode=0(기타) + ReasonDetail='재고부족(품절)' 로 온다.
    둘 다 쓰면 "기타 · 재고부족(품절)" 처럼 겹친다 — 실제 사유는 상세 문구다."""
    rows = _rows(cancels=[{"OrderNo": 5, "CancelStatus": 3, "Reason": 0,
                           "ReasonCode": 0, "ReasonDetail": "재고부족(품절)"}],
                 details={})
    c = [r for r in rows if r["오픈마켓주문번호"] == 5][0]
    assert c["배송메시지"] == "판매자 귀책 · 재고부족(품절)"


def test_상세문구가_없으면_기타를_남긴다():
    rows = _rows(cancels=[{"OrderNo": 6, "CancelStatus": 3, "Reason": 1, "ReasonCode": 0}],
                 details={})
    c = [r for r in rows if r["오픈마켓주문번호"] == 6][0]
    assert c["배송메시지"] == "구매자 귀책 · 기타"


# ── 클레임 빈칸을 정산 실값(주문 시점 단가·수량·실결제)으로 채운다 ──────────────
#  옥션·G마켓 클레임 응답은 주문번호+상태뿐이라 단가·수량·판매가가 통째로 빈다.
#  그런데 그 값들은 이미 부르고 있는 '판매대금 정산조회' 응답 안에 들어 있다
#  (그래서 빈 행에도 정산예상금은 찍힌다). 주문 시점 실값이라 '지금 판매가' 폴백과 다르다.

class _SettleClient(Client):
    """클레임 조회 + 정산조회(단가·수량·실결제 포함)를 함께 흉내낸다."""

    def __init__(self, settle=(), **kw):
        super().__init__(**kw)
        self._settle_pages = [{"ResultCode": 0, "TotalCount": len(settle),
                               "Data": list(settle)}]

    def request_settlement(self, body):
        return self._settle_pages.pop(0) if self._settle_pages else {
            "ResultCode": 0, "Data": []}


def _rows_settled(settle=(), **kw):
    cli = _SettleClient(settle=settle, **kw)
    return oe.esm_order_rows("auction", SINCE, UNTIL, client=cli,
                             include_settlement=True)


def test_취소행_단가_수량을_정산_실값으로_채운다(monkeypatch):
    """단가·수량이 채워지면 _finalize 가 상품금액·주문금액까지 자동 계산한다."""
    monkeypatch.setattr("shared.platforms.esm.orders.fill_from_product",
                        lambda m, s, *, client, goods_no=None: ("취소된상품", None))
    rows = _rows_settled(
        cancels=[{"OrderNo": 2, "CancelStatus": 3, "SiteGoodsNo": "S2"}],
        settle=[{"ContrNo": 2, "Kind": 1, "SettlementPrice": 18000,
                 "OrderUnitPrice": 20000, "OrderQty": 2, "BuyerPayAmt": 41000}])
    c = [r for r in rows if r["오픈마켓주문번호"] == 2][0]
    assert c["단가"] == 20000            # 정산 실값(주문 시점)
    assert c["수량"] == 2
    assert c["실결제금액"] == 41000
    assert c["정산예정금액"] == 18000
    assert c["상품명"] == "취소된상품"      # 상품명은 상품API로(정산은 이름 없음)


def test_정산에_없는_클레임은_단가를_지어내지_않는다():
    """미정산이면 정산 맵에 없다 → 단가는 빈칸으로 둔다(폴백 금지·거짓값 금지)."""
    rows = _rows_settled(
        cancels=[{"OrderNo": 7, "CancelStatus": 3}],
        settle=[])                       # 이 주문은 아직 미정산
    c = [r for r in rows if r["오픈마켓주문번호"] == 7][0]
    assert c["단가"] in ("", None)        # 지어내지 않음
    assert c["주문상태"] == "취소완료"       # 그래도 행은 남는다


def test_정상주문의_기존_단가는_정산이_덮지_않는다():
    """정상 주문은 주문조회가 준 단가가 있다 — 정산값으로 덮으면 안 된다(빈칸만 채움)."""
    rows = _rows_settled(
        normal=[_detail(5, "정상상품", "10000")],
        settle=[{"ContrNo": 5, "Kind": 1, "SettlementPrice": 9000,
                 "OrderUnitPrice": 99999, "OrderQty": 7}])
    r = [x for x in rows if x["오픈마켓주문번호"] == 5][0]
    assert r["단가"] == "10000"           # 주문조회 원본 유지(99999 로 안 덮음)
    assert r["정산예정금액"] == 9000        # 정산액은 채운다
