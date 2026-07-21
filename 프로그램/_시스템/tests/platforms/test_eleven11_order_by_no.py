# -*- coding: utf-8 -*-
"""11번가 주문번호 단건 복구(eleven11.110) — 상태별 창 조회 9경로가 구조적으로
안 주는 주문(반품완료·구매확정 옛 건)의 정밀 통로. 2026-07-22 샵마인 대사 잔여 26건."""
import datetime as _dt

KST = _dt.timezone(_dt.timedelta(hours=9))
SINCE = _dt.datetime(2026, 7, 1, tzinfo=KST)
UNTIL = _dt.datetime(2026, 7, 8, tzinfo=KST)

_ONE = ('<?xml version="1.0" encoding="euc-kr"?><ns2:orders xmlns:ns2="http://x">'
        '<ns2:order><ns2:ordNo>20260519069451269</ns2:ordNo>'
        '<ns2:ordPrdSeq>1</ns2:ordPrdSeq><ns2:ordDt>2026-05-19 10:00:00</ns2:ordDt>'
        '<ns2:prdNm>복구상품</ns2:prdNm><ns2:slctPrdOptNm>블랙/M</ns2:slctPrdOptNm>'
        '<ns2:ordQty>1</ns2:ordQty><ns2:selPrc>25000</ns2:selPrc>'
        '<ns2:stlPlnAmt>23000</ns2:stlPlnAmt><ns2:rcvrNm>홍길동</ns2:rcvrNm>'
        '</ns2:order></ns2:orders>')
_STATUS = ('<?xml version="1.0" encoding="euc-kr"?><ns2:orders xmlns:ns2="http://x">'
           '<ns2:order><ns2:ordNo>20260519069451269</ns2:ordNo>'
           '<ns2:ordPrdStat>반품완료</ns2:ordPrdStat></ns2:order></ns2:orders>')
_EMPTY = '<?xml version="1.0" encoding="euc-kr"?><ns2:orders xmlns:ns2="http://x"></ns2:orders>'


class _Client:
    def __init__(self, one=_ONE, status=_STATUS):
        self.one, self.status, self.calls = one, status, []

    def request(self, method, path, body=None):
        self.calls.append(path)
        if "/claimservice/orderlistalladdr/" in path:
            return self.status
        if "/ordservices/complete/" in path:
            return self.one
        return _EMPTY


def test_단건조회가_행을_만든다():
    from shared.platforms.eleven11.orders import fetch_order
    ods = fetch_order("20260519069451269", client=_Client())
    assert len(ods) == 1 and ods[0]["prdNm"] == "복구상품"


def test_builder_order_nos_모드는_창조회_없이_단건만_부른다():
    from lemouton.markets import order_export as oe
    cli = _Client()
    rows = oe.eleven11_order_rows(SINCE, UNTIL, client=cli, include_settlement=False,
                                  order_nos=["20260519069451269"])
    assert len(rows) == 1
    r = rows[0]
    assert r["오픈마켓주문번호"] == "20260519069451269"
    assert r["상품명"] == "복구상품" and r["단가"] == "25000"
    assert r["주문상태"] == "반품완료"          # 배송정보 조회(115)의 원문
    assert r.get("_recovered_by_ordno") is True
    # 기간 창 조회 경로는 안 불렀다(단건 2경로만)
    assert all("/complete/20260519069451269" in p
               or "/orderlistalladdr/" in p for p in cli.calls), cli.calls


def test_상태를_못_얻으면_공란_보존():
    from lemouton.markets import order_export as oe
    cli = _Client(status=_EMPTY)
    rows = oe.eleven11_order_rows(SINCE, UNTIL, client=cli, include_settlement=False,
                                  order_nos=["20260519069451269"])
    assert rows and rows[0]["주문상태"] == ""   # 지어내지 않는다
