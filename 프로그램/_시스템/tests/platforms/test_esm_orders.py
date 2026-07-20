# -*- coding: utf-8 -*-
"""[TEST] 옥션·G마켓(ESM 2.0) 주문조회 — JWT 인증·조회 페이징/중복제거·행 매핑.

키 없이 검증(Mock). 실 계정 라이브 검증은 키 입력 후 서버에서(그 전엔 SUPPORTED 미포함).
근거 스펙: docs/markets/auction.yaml · gmarket.yaml (etapi.gmarket.com 공개문서).
"""
import base64
import datetime as _dt
import hashlib
import hmac
import json

import pytest

KST = _dt.timezone(_dt.timedelta(hours=9))


def _b64d(seg):
    return json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))


# ── JWT 인증(HmacSHA256) ──
class TestJwt:
    def test_structure_and_signature(self):
        from shared.platforms.esm.auth import build_jwt
        tok = build_jwt("MASTER1", "secretkey", "A", "seller9",
                        issuer="www.esmplus.com", iat=1000)
        h, p, s = tok.split(".")
        assert _b64d(h) == {"alg": "HS256", "typ": "JWT", "kid": "MASTER1"}
        pl = _b64d(p)
        assert pl["ssi"] == "A:seller9" and pl["sub"] == "sell"
        assert pl["aud"] == "sa.esmplus.com" and pl["iss"] == "www.esmplus.com"
        assert pl["iat"] == 1000
        expect = hmac.new(b"secretkey", (h + "." + p).encode(), hashlib.sha256).digest()
        got = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        assert got == expect                      # 서명 일치

    def test_site_g_for_gmarket(self):
        from shared.platforms.esm.auth import build_jwt
        pl = _b64d(build_jwt("M", "k", "G", "sel").split(".")[1])
        assert pl["ssi"] == "G:sel"

    def test_missing_raises(self):
        from shared.platforms.esm.auth import build_jwt
        with pytest.raises(ValueError):
            build_jwt("", "k", "A", "x")

    def test_headers_bearer(self):
        from shared.platforms.esm.auth import build_headers
        h = build_headers("M", "k", "G", "sel")
        assert h["Authorization"].startswith("Bearer ")
        assert "json" in h["Content-Type"]


class _FakeEsm:
    def __init__(self, pages):
        self.pages = list(pages)
        self.bodies = []

    def request_orders(self, body):
        self.bodies.append(body)
        return self.pages.pop(0)


# ── 주문조회 파라미터·페이징·중복제거 ──
class TestIterOrders:
    def test_params_and_date_format(self):
        from shared.platforms.esm.orders import iter_orders
        since = _dt.datetime(2026, 7, 1, 0, 0, tzinfo=KST)
        until = _dt.datetime(2026, 7, 5, 0, 0, tzinfo=KST)
        resp = {"ResultCode": 0, "Data": {"TotalCount": 2,
                "RequestOrders": [{"OrderNo": 1}, {"OrderNo": 2}]}}
        fake = _FakeEsm([resp])
        out = list(iter_orders("auction", since, until, client=fake,
                               statuses=(1,), page_size=100))
        assert [o["OrderNo"] for o in out] == [1, 2]
        b = fake.bodies[0]
        assert b["siteType"] == 1 and b["orderStatus"] == 1 and b["requestDateType"] == 1
        assert b["requestDateFrom"] == "2026-07-01 00:00"
        assert b["requestDateTo"] == "2026-07-05 00:00"

    def test_dedup_across_status_and_site(self):
        from shared.platforms.esm.orders import iter_orders
        since = _dt.datetime(2026, 7, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 3, tzinfo=KST)
        resp = {"ResultCode": 0, "Data": {"TotalCount": 1, "RequestOrders": [{"OrderNo": 7}]}}
        fake = _FakeEsm([resp, resp])           # status1 → 7, status2 → 7(중복)
        out = list(iter_orders("gmarket", since, until, client=fake,
                               statuses=(1, 2), page_size=100))
        assert [o["OrderNo"] for o in out] == [7]      # 중복 제거
        assert fake.bodies[0]["siteType"] == 2          # gmarket

    def test_error_code_raises(self):
        from shared.platforms.esm.orders import iter_orders
        since = _dt.datetime(2026, 7, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 2, tzinfo=KST)
        fake = _FakeEsm([{"ResultCode": 9, "Message": "인증 실패"}])
        with pytest.raises(RuntimeError):
            list(iter_orders("auction", since, until, client=fake, statuses=(1,)))

    def test_windows_split_over_31_days(self):
        from shared.platforms.esm.orders import _windows
        s = _dt.datetime(2026, 1, 1)
        u = _dt.datetime(2026, 3, 1)            # 59일
        ws = list(_windows(s, u))
        assert len(ws) == 2
        assert all((b - a).days <= 31 for a, b in ws)
        assert ws[0][0] == s and ws[-1][1] == u


# ── order_export 행 매핑 ──
class TestEsmOrderRows:
    SAMPLE = [{
        "OrderNo": "A1", "OrderDate": "2026-07-03T10:00:00", "OrderStatus": 2,
        "GoodsName": "코트", "ItemOptionSelectList": [{"n": "블랙", "s": "95"}],
        "ContrAmount": 2, "SalePrice": 50000, "ShippingFee": 3000,
        "ReceiverName": "수령", "HpNo": "01011112222", "ZipCode": "12345",
        "DelFrontAddress": "서울시", "DelBackAddress": "101호",
        "BuyerName": "구매", "BuyerId": "b***", "DelMemo": "문앞",
    }]

    def test_auction_maps(self, monkeypatch):
        from lemouton.markets import order_export as oe
        monkeypatch.setattr("shared.platforms.esm.orders.iter_orders",
                            lambda *a, **k: iter(self.SAMPLE))
        r = oe.esm_order_rows("auction", None, None, client=object())[0]
        assert r["판매처"] == "옥션" and r["주문상태"] == "배송준비중"
        assert r["상품명"] == "코트" and "블랙" in r["옵션"] and "95" in r["옵션"]
        assert r["단가"] == 50000 and r["배송비"] == 3000 and r["수량"] == 2
        assert r["주소"] == "서울시 101호" and r["우편번호"] == "12345"
        assert r["수령자"] == "수령" and r["수령자전화번호"] == "01011112222"
        assert r["정산예정금액"] == ""              # 정산 조인 없음(client 무자격) → 공란(폴백 금지)
        assert r["_shipkey"] == ("auction", "A1")
        assert "_ono" not in r                      # 조인용 임시키 제거됨

    def test_gmarket_label(self, monkeypatch):
        from lemouton.markets import order_export as oe
        monkeypatch.setattr("shared.platforms.esm.orders.iter_orders",
                            lambda *a, **k: iter(self.SAMPLE))
        r = oe.gmarket_order_rows(None, None, client=object())[0]
        assert r["판매처"] == "G마켓"

    def test_registered_but_not_supported_yet(self):
        from lemouton.markets import order_export as oe
        assert "auction" in oe._BUILDERS and "gmarket" in oe._BUILDERS
        assert oe._ENV_PREFIX["auction"] == "AUCTION_MAIN"
        # 라이브 검증 전 — 주문 엑셀 노출 마켓에는 미포함(거짓주문 방지)
        assert "auction" not in oe.SUPPORTED and "gmarket" not in oe.SUPPORTED
        # 라이브 검증 전에는 실효 게이트에도 없어야 한다(검증 기록 없음).
        assert "auction" not in oe.supported_markets()
        assert "gmarket" not in oe.supported_markets()


class _FakeSettle:
    def __init__(self, pages, cfg=None):
        self.pages = list(pages)
        self.bodies = []
        self._cfg = cfg or {}

    def request_settlement(self, body):
        self.bodies.append(body)
        return self.pages.pop(0)


# ── 정산조회(getsettleorder) + 조인 ──
class TestSettlement:
    def test_settle_price_map_sums_and_params(self):
        from shared.platforms.esm.settlements import settle_price_map
        since = _dt.datetime(2026, 7, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 10, tzinfo=KST)
        resp = {"ResultCode": 0, "TotalCount": 2, "Data": [
            {"ContrNo": "A1", "SettlementPrice": 45000},
            {"ContrNo": "A1", "SettlementPrice": -5000},   # 환불(부호반전) → 합산
        ]}
        fake = _FakeSettle([resp])
        m = settle_price_map("auction", since, until, client=fake, srch_type="D1", page_rows=500)
        assert m["A1"] == 40000
        b = fake.bodies[0]
        assert b["SiteType"] == "A" and b["SrchType"] == "D1"
        assert b["SrchStartDate"] == "2026-07-01" and b["SrchEndDate"] == "2026-07-10"

    def test_settle_error_raises(self):
        from shared.platforms.esm.settlements import settle_price_map
        since = _dt.datetime(2026, 7, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 3, tzinfo=KST)
        fake = _FakeSettle([{"ResultCode": 9, "Message": "권한없음"}])
        with pytest.raises(RuntimeError):
            settle_price_map("gmarket", since, until, client=fake)

    def test_order_rows_join_settlement(self, monkeypatch):
        from lemouton.markets import order_export as oe
        monkeypatch.setattr("shared.platforms.esm.orders.iter_orders",
                            lambda *a, **k: iter(TestEsmOrderRows.SAMPLE))   # OrderNo="A1"
        settle_resp = {"ResultCode": 0, "TotalCount": 1,
                       "Data": [{"ContrNo": "A1", "SettlementPrice": 47000}]}
        client = _FakeSettle([settle_resp], cfg={"settle_srch_type": "D2"})
        since = _dt.datetime(2026, 7, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 10, tzinfo=KST)
        rows = oe.esm_order_rows("auction", since, until, client=client)
        assert rows[0]["정산예정금액"] == 47000       # ContrNo(=OrderNo) 조인
        assert client.bodies[0]["SrchType"] == "D2"   # config srch_type 사용

    def test_order_rows_settlement_failure_blank(self, monkeypatch):
        # 정산 조회가 실패해도 주문은 살리고 정산액만 공란(폴백 금지).
        from lemouton.markets import order_export as oe
        monkeypatch.setattr("shared.platforms.esm.orders.iter_orders",
                            lambda *a, **k: iter(TestEsmOrderRows.SAMPLE))
        class Boom:
            _cfg = {}
            def request_settlement(self, body):
                raise RuntimeError("정산 API 다운")
        since = _dt.datetime(2026, 7, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 3, tzinfo=KST)
        rows = oe.esm_order_rows("gmarket", since, until, client=Boom())
        assert rows[0]["정산예정금액"] == ""
        assert rows[0]["상품명"] == "코트"             # 주문 데이터는 유지
