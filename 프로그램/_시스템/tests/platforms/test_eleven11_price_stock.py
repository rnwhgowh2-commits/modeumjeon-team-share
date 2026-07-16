# -*- coding: utf-8 -*-
"""[TEST] 11번가 가격·재고 실전송 — prices.update_price / inventory.update_option_stocks.

★ 확보된 셀러 API 실스펙(콘솔 추출, 정본):
  · 기본 판매가 수정: GET /rest/prodservices/product/price/{prdNo}/{selPrc}
      응답 <ClientMessage><resultCode>..<message>..<preSelPrc>..<selPrc>..<prdNo>..
  · 옵션 수정(가격+재고, full-replace 추정):
      POST /rest/prodservices/updateProductOption/{prdNo}
      본문 <Product><ProductOption>colValue0·colOptPrice·colCount·useYn·
                    colSellerStockCd·optionMappingKey</ProductOption>...</Product>

안전 규칙(거짓 성공 금지):
  · 성공 판정 = resultCode ∈ {200,210} (상품등록 선례). 그 외/누락 = 실패(message 표면화).
  · **HTTP 200 이어도 resultCode 가 성공코드가 아니면 실패** — 거짓 성공 회귀 방지.
  · 재고는 옵션 full-replace → 단건 update_stock 은 다른 옵션을 날릴 수 있어 막는다.
"""
import pytest


# ── 응답 XML 헬퍼 ───────────────────────────────────────────────
def _price_xml(code, msg="정상처리", pre="10000", sel="12000"):
    return ('<?xml version="1.0" encoding="euc-kr"?>'
            f"<ClientMessage><resultCode>{code}</resultCode><message>{msg}</message>"
            f"<productNo>1234567890</productNo><preSelPrc>{pre}</preSelPrc>"
            f"<selPrc>{sel}</selPrc><prdNo>1234567890</prdNo></ClientMessage>")


def _opt_xml(code, msg="정상처리"):
    return ('<?xml version="1.0" encoding="euc-kr"?>'
            f"<ClientMessage><resultCode>{code}</resultCode>"
            f"<message>{msg}</message><prdNo>1234567890</prdNo></ClientMessage>")


class FakeClient:
    """client.request 호출을 (method, path, body) 로 기록하고 고정 XML 을 돌려준다."""
    def __init__(self, xml):
        self._xml = xml
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self._xml


# ═══════════════════════ 가격 (prices.py) ═══════════════════════
class TestUpdatePricePath:
    def test_get_path_has_prdno_and_selprc(self):
        """GET /rest/prodservices/product/price/{prdNo}/{selPrc} — 경로에 값 삽입."""
        from shared.platforms.eleven11 import prices
        c = FakeClient(_price_xml("200"))
        prices.update_price("1234567890", 12000, client=c)
        method, path, body = c.calls[0]
        assert method == "GET"
        assert path == "/rest/prodservices/product/price/1234567890/12000"
        assert body is None  # 경로 파라미터 방식 — 본문 없음

    def test_price_must_be_positive_int(self):
        from shared.platforms.eleven11 import prices
        with pytest.raises(ValueError):
            prices.update_price("1234567890", 0, client=FakeClient(_price_xml("200")))

    def test_empty_product_id_raises(self):
        from shared.platforms.eleven11 import prices
        with pytest.raises(ValueError):
            prices.update_price("", 12000, client=FakeClient(_price_xml("200")))


class TestUpdatePriceResult:
    @pytest.mark.parametrize("code", ["200", "210"])
    def test_success_codes(self, code):
        from shared.platforms.eleven11 import prices
        r = prices.update_price("1234567890", 12000, client=FakeClient(_price_xml(code)))
        assert r.success is True
        assert r.result_code == code
        assert r.error_message is None

    def test_unapproved_300_is_failure_with_message(self):
        """resultCode 300(SellerAPI 미승인) → 실패 + message 표면화."""
        from shared.platforms.eleven11 import prices
        r = prices.update_price(
            "1234567890", 12000,
            client=FakeClient(_price_xml("300", msg="인증되지 않은 API")))
        assert r.success is False
        assert r.result_code == "300"
        assert "인증" in (r.error_message or "")

    def test_http200_but_non_success_code_is_failure(self):
        """★거짓 성공 회귀 방지 — HTTP 200(FakeClient 는 이미 2xx 가정)이라도
        resultCode 가 성공코드가 아니면 반드시 실패."""
        from shared.platforms.eleven11 import prices
        r = prices.update_price("1234567890", 12000,
                                client=FakeClient(_price_xml("500", msg="시스템오류")))
        assert r.success is False

    def test_missing_result_code_is_failure(self):
        """resultCode 누락 → 성공으로 오판하지 않는다."""
        from shared.platforms.eleven11 import prices
        xml = ('<?xml version="1.0" encoding="euc-kr"?>'
               "<ClientMessage><message>결과코드 없음</message></ClientMessage>")
        r = prices.update_price("1234567890", 12000, client=FakeClient(xml))
        assert r.success is False

    def test_unparseable_body_is_failure_not_success(self):
        from shared.platforms.eleven11 import prices
        r = prices.update_price("1234567890", 12000, client=FakeClient("<<not xml"))
        assert r.success is False


class TestUpdatePricesBatch:
    def test_batch_calls_each(self):
        from shared.platforms.eleven11 import prices
        c = FakeClient(_price_xml("200"))
        results = prices.update_prices(
            [{"product_id": "A1", "price": 10000},
             {"product_id": "B2", "price": 20000}], client=c)
        assert len(results) == 2
        assert all(r.success for r in results)
        assert c.calls[0][1].endswith("/A1/10000")
        assert c.calls[1][1].endswith("/B2/20000")


# ═══════════════════ 옵션 재고 (inventory.py) ═══════════════════
_OPTS = [
    {"col_value0": "블랙//250", "col_count": 7, "option_mapping_key": "K1"},
    {"col_value0": "블랙//255", "col_count": 0, "use_yn": "N", "option_mapping_key": "K2"},
]


class TestUpdateOptionStocksPath:
    def test_post_updateproductoption_path(self):
        from shared.platforms.eleven11 import inventory
        c = FakeClient(_opt_xml("200"))
        inventory.update_option_stocks("1234567890", _OPTS, client=c)
        method, path, body = c.calls[0]
        assert method == "POST"
        assert path == "/rest/prodservices/updateProductOption/1234567890"
        assert body is not None

    def test_body_has_product_and_option_fields(self):
        from shared.platforms.eleven11 import inventory
        c = FakeClient(_opt_xml("200"))
        inventory.update_option_stocks("1234567890", _OPTS, client=c)
        body = c.calls[0][2]
        assert "<Product>" in body and "</Product>" in body
        assert body.count("<ProductOption>") == 2
        # 재고(colCount)·옵션값(colValue0)·상태(useYn)·매핑키 조립
        assert "<colValue0>블랙//250</colValue0>" in body
        assert "<colCount>7</colCount>" in body
        assert "<colCount>0</colCount>" in body   # 0=품절도 명시 전송(센티넬 붕괴 금지)
        assert "<useYn>N</useYn>" in body
        assert "<optionMappingKey>K2</optionMappingKey>" in body

    def test_body_escapes_xml_special_chars(self):
        from shared.platforms.eleven11 import inventory
        c = FakeClient(_opt_xml("200"))
        inventory.update_option_stocks(
            "P", [{"col_value0": "A&B<C>", "col_count": 3}], client=c)
        body = c.calls[0][2]
        assert "&amp;" in body and "&lt;" in body and "&gt;" in body
        assert "A&B" not in body  # 원문 그대로 새어나가지 않음

    def test_empty_options_raises(self):
        """옵션 목록이 비면 full-replace 대상이 없음 → 조용히 넘기지 않고 막는다."""
        from shared.platforms.eleven11 import inventory
        with pytest.raises(ValueError):
            inventory.update_option_stocks("P", [], client=FakeClient(_opt_xml("200")))

    def test_option_missing_required_fields_raises(self):
        from shared.platforms.eleven11 import inventory
        with pytest.raises((ValueError, KeyError)):
            inventory.update_option_stocks(
                "P", [{"col_value0": "블랙//250"}], client=FakeClient(_opt_xml("200")))


class TestUpdateOptionStocksResult:
    @pytest.mark.parametrize("code", ["200", "210"])
    def test_success_codes(self, code):
        from shared.platforms.eleven11 import inventory
        r = inventory.update_option_stocks("P", _OPTS, client=FakeClient(_opt_xml(code)))
        assert r.success is True
        assert r.result_code == code

    def test_unapproved_300_is_failure(self):
        from shared.platforms.eleven11 import inventory
        r = inventory.update_option_stocks(
            "P", _OPTS, client=FakeClient(_opt_xml("300", msg="미승인")))
        assert r.success is False
        assert "미승인" in (r.error_message or "")

    def test_http200_but_non_success_code_is_failure(self):
        """★거짓 성공 회귀 방지."""
        from shared.platforms.eleven11 import inventory
        r = inventory.update_option_stocks("P", _OPTS, client=FakeClient(_opt_xml("999")))
        assert r.success is False


class TestSingleStockGuarded:
    def test_update_stock_single_refuses_destructive_send(self):
        """단건 재고 전송은 full-replace 로 다른 옵션을 날릴 수 있어 막는다(네트워크 호출 0)."""
        from shared.platforms.eleven11 import inventory
        c = FakeClient(_opt_xml("200"))
        with pytest.raises(NotImplementedError):
            inventory.update_stock("P", "opt1", 5, client=c)
        assert c.calls == []  # 아무 것도 전송하지 않음


# ═══════════════ 실제 헤더·URL (Eleven11Client 라운드트립) ═══════════════
class TestRealClientHeaderAndUrl:
    def test_openapikey_header_and_full_url(self, monkeypatch):
        """update_price 가 실 클라이언트로 openapikey 헤더 + 완전 URL 을 GET 하는지."""
        import shared.platforms.eleven11.client as client_mod
        from shared.platforms.eleven11.client import Eleven11Client
        from shared.platforms.eleven11 import prices

        captured = {}

        class _Resp:
            status_code = 200
            encoding = "euc-kr"
            text = _price_xml("200")
            headers = {}

        def fake_request(method, url, headers=None, data=None, timeout=None):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            return _Resp()

        monkeypatch.setattr(client_mod.requests, "request", fake_request)
        client = Eleven11Client({"base_url": "http://api.11st.co.kr",
                                 "openapi_key": "TESTKEY123", "rate_limit_per_sec": 100})
        r = prices.update_price("777", 15000, client=client)
        assert r.success is True
        assert captured["method"] == "GET"
        assert captured["url"] == "http://api.11st.co.kr/rest/prodservices/product/price/777/15000"
        assert captured["headers"]["openapikey"] == "TESTKEY123"
