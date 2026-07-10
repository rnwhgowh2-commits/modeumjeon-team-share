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

    def test_merges_all_statuses(self):
        # 발송대기(complete)+배송완료(dlvcompleted)+구매확정(completed) 3종 병합 → 전체 상태.
        from lemouton.markets import order_export as oe

        def _one(no, nm, opt, qty, extra=""):
            return ('<ns2:order><ns2:ordNo>' + no + '</ns2:ordNo><ns2:ordPrdSeq>1</ns2:ordPrdSeq>'
                    '<ns2:prdNm>' + nm + '</ns2:prdNm><ns2:slctPrdOptNm>' + opt + '</ns2:slctPrdOptNm>'
                    '<ns2:ordQty>' + qty + '</ns2:ordQty><ns2:dlvCst>0</ns2:dlvCst>' + extra + '</ns2:order>')

        def _doc(inner):
            return '<?xml version="1.0" encoding="euc-kr"?><ns2:orders xmlns:ns2="http://x">' + inner + '</ns2:orders>'

        delivered_xml = _doc(_one("77", "배송완료상품", "옵션D", "2",
                                  "<ns2:rcvrNm>수령인</ns2:rcvrNm><ns2:selPrc>12000</ns2:selPrc>"
                                  "<ns2:dlvEndDt>2026-07-03 10:00:00</ns2:dlvEndDt>"))
        completed_xml = _doc(_one("99", "구매확정상품", "옵션Z", "3",
                                  "<ns2:pocnfrmDt>2026-07-02 10:00:00</ns2:pocnfrmDt>"))

        class _PathClient:
            def request(self, method, path, body=None):
                if "/dlvcompleted/" in path:
                    return delivered_xml
                if "/completed/" in path:
                    return completed_xml
                return _XML                      # complete(발송대기)

        since = _dt.datetime(2026, 7, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 5, tzinfo=KST)
        rows = oe.eleven11_order_rows(since, until, client=_PathClient())
        statuses = {r["주문상태"] for r in rows}
        assert {"결제완료", "배송완료", "구매확정"} <= statuses      # 3상태 병합
        deliv = [r for r in rows if r["주문상태"] == "배송완료"][0]
        assert deliv["상품명"] == "배송완료상품" and deliv["단가"] == "12000" and deliv["수령자"] == "수령인"
        done = [r for r in rows if r["주문상태"] == "구매확정"][0]
        assert done["단가"] == "" and done["수령자"] == ""            # 구매확정 목록 미제공 → 공란

    def test_merges_preparing_shipping_claims(self):
        # 배송준비중(packaging 전체)·배송중(shipping)·취소/반품/교환(claimservice) 병합.
        from lemouton.markets import order_export as oe

        def _doc(inner):
            return ('<?xml version="1.0" encoding="euc-kr"?><ns2:orders xmlns:ns2="http://x">'
                    + inner + '</ns2:orders>')

        # 배송준비중 전체: packaging = 결제완료와 동일 필드. 2건(미래발송 포함).
        packaging_xml = _doc(
            '<ns2:order><ns2:ordNo>20260707082111111</ns2:ordNo>'
            '<ns2:ordPrdSeq>1</ns2:ordPrdSeq><ns2:prdNm>준비중상품</ns2:prdNm>'
            '<ns2:ordQty>1</ns2:ordQty><ns2:selPrc>5000</ns2:selPrc>'
            '<ns2:rcvrNm>홍길동</ns2:rcvrNm><ns2:ordDt>2026-07-07 09:00:00</ns2:ordDt></ns2:order>'
            '<ns2:order><ns2:ordNo>20260708082122222</ns2:ordNo>'
            '<ns2:ordPrdSeq>1</ns2:ordPrdSeq><ns2:prdNm>예약상품</ns2:prdNm>'
            '<ns2:ordQty>1</ns2:ordQty><ns2:selPrc>7000</ns2:selPrc>'
            '<ns2:rcvrNm>김철수</ns2:rcvrNm><ns2:ordDt>2026-07-08 09:00:00</ns2:ordDt></ns2:order>')
        shipping_xml = _doc('<ns2:order><ns2:ordNo>20260706082133333</ns2:ordNo>'
                            '<ns2:ordPrdSeq>1</ns2:ordPrdSeq><ns2:invcNo>1234567890</ns2:invcNo>'
                            '<ns2:sndEndDt>2026-07-06 16:00:00</ns2:sndEndDt></ns2:order>')
        # 취소: ordCnQty·slctPrdOptNm·사유(상품명 없음). 반품: clmReqQty·optName.
        cancel_xml = _doc('<ns2:order><ns2:ordNo>20260703082144444</ns2:ordNo>'
                          '<ns2:ordPrdSeq>1</ns2:ordPrdSeq><ns2:slctPrdOptNm>블랙/M</ns2:slctPrdOptNm>'
                          '<ns2:ordCnQty>1</ns2:ordCnQty><ns2:ordCnDtlsRsn>단순변심</ns2:ordCnDtlsRsn></ns2:order>')
        return_xml = _doc('<ns2:order><ns2:ordNo>20260704082155555</ns2:ordNo>'
                          '<ns2:ordPrdSeq>1</ns2:ordPrdSeq><ns2:optName>화이트/L</ns2:optName>'
                          '<ns2:clmReqQty>2</ns2:clmReqQty><ns2:clmReqRsn>불량</ns2:clmReqRsn></ns2:order>')

        class _PathClient:
            def request(self, method, path, body=None):
                if "/packaging/" in path:
                    return packaging_xml
                if "/shipping/" in path:
                    return shipping_xml
                if "/cancelorders/" in path:
                    return cancel_xml
                if "/returnorders/" in path:
                    return return_xml
                return _doc("")                  # 그 외 상태 없음

        since = _dt.datetime(2026, 7, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 8, tzinfo=KST)
        rows = oe.eleven11_order_rows(since, until, client=_PathClient())
        statuses = {r["주문상태"] for r in rows}
        # 주문상태 통일(2026-07-10): 클레임 접수는 '취소요청·반품요청'(완료와 구분).
        assert {"배송준비중", "배송중", "취소요청", "반품요청"} <= statuses
        prep = [r for r in rows if r["주문상태"] == "배송준비중"]
        assert {p["상품명"] for p in prep} == {"준비중상품", "예약상품"}   # packaging 전체
        # 배송중: 송장만 + 주문일 ordNo 보정
        ship = [r for r in rows if r["주문상태"] == "배송중"][0]
        assert ship["송장입력"] == "1234567890" and ship["주문일"] == "20260706"
        # 취소/반품: 주문번호·옵션·수량 채워지고 상품명은 공란(목록 미제공)
        cx = [r for r in rows if r["주문상태"] == "취소요청"][0]
        assert cx["오픈마켓주문번호"] == "20260703082144444" and cx["옵션"] == "블랙/M"
        assert cx["수량"] == "1" and cx["상품명"] == ""
        rx = [r for r in rows if r["주문상태"] == "반품요청"][0]
        assert rx["옵션"] == "화이트/L" and rx["수량"] == "2"
