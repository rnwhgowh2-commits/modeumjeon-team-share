# -*- coding: utf-8 -*-
"""[TEST] 11번가 주문조회(발주확인·기간별 결제완료 목록) — XML 파싱·행 매핑.

키 없이 검증(Fake client). 실 계정 라이브 검증은 키 입력 후 서버에서(그 전 SUPPORTED 미포함).
근거 스펙: 공개문서 openapi.11st.co.kr(GET /rest/ordservices/complete/{start}/{end}, XML).
"""
import datetime as _dt

import pytest

KST = _dt.timezone(_dt.timedelta(hours=9))

_XML = """<?xml version="1.0" encoding="euc-kr" standalone="yes"?>
<ns2:orders xmlns:ns2="http://www.11st.co.kr/Order">
  <ns2:order>
    <ns2:ordNo>201001108318120</ns2:ordNo>
    <ns2:ordDt>2010-01-10 04:07:11</ns2:ordDt>
    <ns2:prdNm>보이넥 니트 티셔츠</ns2:prdNm>
    <ns2:prdNo>29370295</ns2:prdNo>
    <ns2:ordPrdSeq>1</ns2:ordPrdSeq>
    <ns2:slctPrdOptNm>사이즈/색상:S(66)/아이보리</ns2:slctPrdOptNm>
    <ns2:ordQty>2</ns2:ordQty>
    <ns2:selPrc>19000</ns2:selPrc>
    <ns2:dlvCst>0</ns2:dlvCst>
    <ns2:bmDlvCst>4500</ns2:bmDlvCst>
    <ns2:bndlDlvSeq>4506571</ns2:bndlDlvSeq>
    <ns2:bndlDlvYN>Y</ns2:bndlDlvYN>
    <ns2:rcvrNm>홍길동</ns2:rcvrNm>
    <ns2:rcvrPrtblNo>010-9999-9999</ns2:rcvrPrtblNo>
    <ns2:rcvrBaseAddr>충북 청주시 상당구 용암동</ns2:rcvrBaseAddr>
    <ns2:rcvrDtlsAddr>00번지 8809호</ns2:rcvrDtlsAddr>
    <ns2:rcvrMailNo>360100</ns2:rcvrMailNo>
    <ns2:ordNm>김구매</ns2:ordNm>
    <ns2:memID>test11st</ns2:memID>
    <ns2:ordPrtblTel>010-1111-2222</ns2:ordPrtblTel>
    <ns2:ordDlvReqCont>null</ns2:ordDlvReqCont>
    <ns2:stlPlnAmt>34200</ns2:stlPlnAmt>
  </ns2:order>
  <ns2:order>
    <ns2:ordNo>201001108318120</ns2:ordNo>
    <ns2:ordPrdSeq>2</ns2:ordPrdSeq>
    <ns2:prdNm>양말 세트</ns2:prdNm>
    <ns2:prdNo>29370777</ns2:prdNo>
    <ns2:ordQty>1</ns2:ordQty>
    <ns2:selPrc>5000</ns2:selPrc>
    <ns2:bndlDlvSeq>4506571</ns2:bndlDlvSeq>
    <ns2:bndlDlvYN>Y</ns2:bndlDlvYN>
    <ns2:rcvrNm>홍길동</ns2:rcvrNm>
  </ns2:order>
</ns2:orders>"""


class _FakeClient:
    def __init__(self, xml):
        self.xml = xml
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        return self.xml


class TestIterOrders:
    def test_parse_and_path(self):
        from shared.platforms.eleven11.orders import iter_orders
        since = _dt.datetime(2026, 7, 1, 0, 0, tzinfo=KST)
        until = _dt.datetime(2026, 7, 5, 0, 0, tzinfo=KST)
        fake = _FakeClient(_XML)
        out = list(iter_orders(since, until, client=fake))
        assert len(out) == 2                       # 상품라인 2개(ordPrdSeq 1·2)
        assert out[0]["ordNo"] == "201001108318120"
        assert out[0]["slctPrdOptNm"] == "사이즈/색상:S(66)/아이보리"
        # GET /rest/ordservices/complete/{YYYYMMDDhhmm}/{YYYYMMDDhhmm}
        m, path = fake.calls[0]
        assert m == "GET"
        assert path == "/rest/ordservices/complete/202607010000/202607050000"

    def test_dedup_across_windows(self):
        from shared.platforms.eleven11.orders import iter_orders
        since = _dt.datetime(2026, 6, 1, tzinfo=KST)
        until = _dt.datetime(2026, 6, 20, tzinfo=KST)   # 19일 → 3개 윈도우, 같은 XML 반복
        fake = _FakeClient(_XML)
        out = list(iter_orders(since, until, client=fake))
        assert len(fake.calls) == 3                 # 7일 윈도우 분할
        assert len(out) == 2                        # (ordNo,ordPrdSeq) 중복 제거

    def test_windows_7day(self):
        from shared.platforms.eleven11.orders import _windows
        s = _dt.datetime(2026, 1, 1)
        u = _dt.datetime(2026, 1, 20)
        ws = list(_windows(s, u))
        assert all((b - a).days <= 7 for a, b in ws)
        assert ws[0][0] == s and ws[-1][1] == u


class TestOrderRows:
    def test_maps_fields(self):
        from lemouton.markets import order_export as oe
        since = _dt.datetime(2026, 7, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 5, tzinfo=KST)
        # iter_orders 는 client.request 를 쓰므로 Fake client 주입
        rows = oe.eleven11_order_rows(since, until, client=_FakeClient(_XML))
        r = rows[0]
        assert r["판매처"] == "11번가" and r["주문상태"] == "결제완료"
        assert r["상품명"] == "보이넥 니트 티셔츠"
        assert r["옵션"] == "사이즈/색상:S(66)/아이보리"
        assert r["수량"] == "2" and r["단가"] == "19000"
        assert r["배송비"] == "4500"                 # 묶음배송(bndlDlvYN=Y) → bmDlvCst
        assert r["주소"] == "충북 청주시 상당구 용암동 00번지 8809호"
        assert r["우편번호"] == "360100" and r["수령자"] == "홍길동"
        assert r["수령자전화번호"] == "010-9999-9999"
        assert r["구매자"] == "김구매"
        assert r["배송메시지"] == ""                  # "null" → 공란
        assert r["정산예정금액"] == "34200"           # stlPlnAmt(정산예정금액) — 실호출 확인
        assert r["_shipkey"] == ("eleven11", "4506571")

    def test_registered_and_supported(self):
        from lemouton.markets import order_export as oe
        assert "eleven11" in oe._BUILDERS
        assert oe._ENV_PREFIX["eleven11"] == "ELEVEN11_MAIN"
        assert "eleven11" in oe.SUPPORTED           # 서버 실호출 검증 완료(2026-07-08)

    def test_merges_completed_status(self):
        # 발송대기(complete) + 구매확정(completed) 두 목록을 합쳐 전체 상태 표시.
        from lemouton.markets import order_export as oe
        completed_xml = ('<?xml version="1.0" encoding="euc-kr"?>'
                         '<ns2:orders xmlns:ns2="http://x">'
                         '<ns2:order><ns2:ordNo>99</ns2:ordNo><ns2:ordPrdSeq>1</ns2:ordPrdSeq>'
                         '<ns2:prdNm>완료상품</ns2:prdNm><ns2:slctPrdOptNm>옵션Z</ns2:slctPrdOptNm>'
                         '<ns2:ordQty>3</ns2:ordQty><ns2:dlvCst>0</ns2:dlvCst>'
                         '<ns2:pocnfrmDt>2026-07-02 10:00:00</ns2:pocnfrmDt></ns2:order>'
                         '</ns2:orders>')

        class _PathClient:
            def request(self, method, path, body=None):
                return completed_xml if "/completed/" in path else _XML

        since = _dt.datetime(2026, 7, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 5, tzinfo=KST)
        rows = oe.eleven11_order_rows(since, until, client=_PathClient())
        statuses = {r["주문상태"] for r in rows}
        assert "결제완료" in statuses and "구매확정" in statuses      # 두 상태 병합
        done = [r for r in rows if r["주문상태"] == "구매확정"][0]
        assert done["상품명"] == "완료상품" and done["옵션"] == "옵션Z" and done["수량"] == "3"
        assert done["단가"] == "" and done["수령자"] == ""            # 구매확정 목록 미제공 → 공란
