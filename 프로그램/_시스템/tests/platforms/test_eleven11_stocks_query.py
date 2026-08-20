# -*- coding: utf-8 -*-
"""[TEST] 11번가 재고조회(stocks_query) + echo-back full-replace(inventory).

★ 확보 스펙(콘솔, 2026-07-16):
  · 재고조회: POST /rest/prodmarketservice/prodmarket/stocks (prdNo XML 본문)
      응답 ns2: <ProductStocks><ProductStock> 반복 — mixOptNo·mixOptNm·mixDtlOptNm·
      stckQty·prdStckStatCd·sellerStockCd·addPrc·selQty·prdStckNo.
  · echo-back full-replace: 현재 옵션을 하나도 잃지 않고 되보내되 대상 옵션만 재고 교체.

안전(money-critical):
  · 옵션 소실 0 — 옵션 수·값 보존을 테스트로 못 박는다.
  · 파싱 실패/빈 응답은 예외(조용한 0/빈 리스트 붕괴 금지).
  · 배치는 재고 실패 시 가격 미전송(partial 방지), resultCode 판정(거짓 성공 금지).
  · 네트워크 실호출 0 — 전부 mock.
"""
import pytest


# ── 응답 XML 헬퍼 (ns2 네임스페이스 포함) ─────────────────────────
def _stock_el(opt_no, opt_nm, dtl, qty, stat="1", scd="", addprc="0"):
    return (
        "<ns2:ProductStock>"
        f"<ns2:mixOptNo>{opt_no}</ns2:mixOptNo>"
        f"<ns2:mixOptNm>{opt_nm}</ns2:mixOptNm>"
        f"<ns2:mixDtlOptNm>{dtl}</ns2:mixDtlOptNm>"
        f"<ns2:stckQty>{qty}</ns2:stckQty>"
        f"<ns2:prdStckStatCd>{stat}</ns2:prdStckStatCd>"
        f"<ns2:sellerStockCd>{scd}</ns2:sellerStockCd>"
        f"<ns2:addPrc>{addprc}</ns2:addPrc>"
        f"<ns2:selQty>0</ns2:selQty>"
        f"<ns2:prdStckNo>P{opt_no}</ns2:prdStckNo>"
        "</ns2:ProductStock>"
    )


def _stocks_xml(*els):
    inner = "".join(els)
    return ('<?xml version="1.0" encoding="euc-kr"?>'
            '<ns2:ProductStocks xmlns:ns2="http://www.11st.co.kr/output">'
            f"{inner}</ns2:ProductStocks>")


_TWO = _stocks_xml(
    _stock_el("111", "색상", "블랙//250", 7, scd="SC1", addprc="0"),
    _stock_el("222", "색상", "블랙//255", 0, stat="3", scd="SC2", addprc="1000"),
)


class FakeClient:
    """client.request 호출을 (method, path, body) 로 기록하고 고정 XML 을 돌려준다."""
    def __init__(self, xml):
        self._xml = xml
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self._xml


# ═══════════════════════ get_stocks (stocks_query.py) ═══════════════════════
class TestGetStocksRequest:
    def test_post_path_and_prdno_in_body(self):
        from shared.platforms.eleven11 import stocks_query
        c = FakeClient(_TWO)
        stocks_query.get_stocks("1234567890", client=c)
        method, path, body = c.calls[0]
        assert method == "POST"
        assert path == "/rest/prodmarketservice/prodmarket/stocks"
        assert "<prdNo>1234567890</prdNo>" in body

    def test_empty_product_id_raises(self):
        from shared.platforms.eleven11 import stocks_query
        with pytest.raises(ValueError):
            stocks_query.get_stocks("", client=FakeClient(_TWO))


class TestGetStocksParse:
    def test_parses_multiple_options_ns2(self):
        from shared.platforms.eleven11 import stocks_query
        opts = stocks_query.get_stocks("P", client=FakeClient(_TWO))
        assert len(opts) == 2

    def test_field_mapping(self):
        from shared.platforms.eleven11 import stocks_query
        opts = stocks_query.get_stocks("P", client=FakeClient(_TWO))
        a, b = opts
        assert a["opt_no"] == "111"
        assert a["opt_nm"] == "색상"
        assert a["dtl_opt_nm"] == "블랙//250"
        assert a["stock"] == 7 and isinstance(a["stock"], int)
        assert a["stat"] == "1"
        assert a["seller_stock_cd"] == "SC1"
        assert a["add_prc"] == 0
        assert b["opt_no"] == "222"
        assert b["stock"] == 0          # 품절도 0 으로 정확 파싱(센티넬 붕괴 금지)
        assert b["add_prc"] == 1000

    def test_empty_response_raises(self):
        from shared.platforms.eleven11 import stocks_query
        with pytest.raises(ValueError):
            stocks_query.get_stocks("P", client=FakeClient(""))

    def test_unparseable_response_raises(self):
        from shared.platforms.eleven11 import stocks_query
        with pytest.raises(ValueError):
            stocks_query.get_stocks("P", client=FakeClient("<<not xml"))

    def test_blank_stock_qty_is_none_not_zero(self):
        """재고수량 공란은 None(미상) — 0 으로 날조하지 않는다."""
        from shared.platforms.eleven11 import stocks_query
        xml = _stocks_xml(_stock_el("111", "색상", "블랙", "", scd="SC1"))
        opts = stocks_query.get_stocks("P", client=FakeClient(xml))
        assert opts[0]["stock"] is None


# ═══════════ build_full_replace_from_current (inventory.py 순수함수) ═══════════
def _current():
    return [
        {"opt_no": "111", "opt_nm": "색상", "dtl_opt_nm": "블랙//250",
         "stock": 7, "stat": "1", "seller_stock_cd": "SC1", "add_prc": 0},
        {"opt_no": "222", "opt_nm": "색상", "dtl_opt_nm": "블랙//255",
         "stock": 3, "stat": "1", "seller_stock_cd": "SC2", "add_prc": 1000},
    ]


class TestBuildFullReplaceEchoBack:
    def test_option_count_preserved(self):
        """옵션 소실 0 — 입력 옵션 수 = 출력 옵션 수."""
        from shared.platforms.eleven11 import inventory
        built = inventory.build_full_replace_from_current(_current(), {"111": 5})
        assert len(built) == 2

    def test_only_target_stock_changed(self):
        from shared.platforms.eleven11 import inventory
        built = inventory.build_full_replace_from_current(_current(), {"111": 5})
        by_no = {b["opt_no"]: b for b in built}
        assert by_no["111"]["col_count"] == 5     # 대상만 교체
        assert by_no["222"]["col_count"] == 3     # 나머지는 현재값 보존

    def test_non_target_values_preserved(self):
        from shared.platforms.eleven11 import inventory
        built = inventory.build_full_replace_from_current(_current(), {"111": 5})
        by_no = {b["opt_no"]: b for b in built}
        # colValue0 ← dtl_opt_nm, colOptPrice ← add_prc, colSellerStockCd ← seller_stock_cd
        assert by_no["222"]["col_value0"] == "블랙//255"
        assert by_no["222"]["col_opt_price"] == 1000
        assert by_no["222"]["col_seller_stock_cd"] == "SC2"
        assert by_no["111"]["col_value0"] == "블랙//250"

    def test_use_yn_preserved_as_Y_even_for_zero_stock(self):
        """품절(재고 0)로 바꿔도 useYn 은 임의 N 전환하지 않는다(옵션 비활성화 방지)."""
        from shared.platforms.eleven11 import inventory
        built = inventory.build_full_replace_from_current(_current(), {"111": 0})
        by_no = {b["opt_no"]: b for b in built}
        assert by_no["111"]["col_count"] == 0
        assert by_no["111"]["use_yn"] == "Y"

    def test_empty_changes_is_pure_echo_back(self):
        from shared.platforms.eleven11 import inventory
        built = inventory.build_full_replace_from_current(_current(), None)
        by_no = {b["opt_no"]: b for b in built}
        assert by_no["111"]["col_count"] == 7
        assert by_no["222"]["col_count"] == 3

    def test_col_value0_falls_back_to_opt_nm(self):
        from shared.platforms.eleven11 import inventory
        cur = [{"opt_no": "1", "opt_nm": "단일옵션", "dtl_opt_nm": None,
                "stock": 4, "stat": "1", "seller_stock_cd": "", "add_prc": None}]
        built = inventory.build_full_replace_from_current(cur, None)
        assert built[0]["col_value0"] == "단일옵션"
        assert built[0]["col_opt_price"] == 0

    def test_missing_current_stock_for_non_target_raises(self):
        """대상 아닌 옵션의 현재 재고가 미상이면 0 으로 날조하지 않고 예외."""
        from shared.platforms.eleven11 import inventory
        cur = [{"opt_no": "1", "opt_nm": "X", "dtl_opt_nm": "X",
                "stock": None, "stat": "1", "seller_stock_cd": "", "add_prc": 0}]
        with pytest.raises(ValueError):
            inventory.build_full_replace_from_current(cur, {"2": 5})

    def test_built_feeds_update_option_stocks_xml(self):
        """echo-back 결과가 실제 full-replace XML 로 조립되며 opt_no 패스스루는 무해."""
        from shared.platforms.eleven11 import inventory
        built = inventory.build_full_replace_from_current(_current(), {"111": 5})
        c = FakeClient('<?xml version="1.0" encoding="euc-kr"?>'
                       "<ClientMessage><resultCode>200</resultCode></ClientMessage>")
        r = inventory.update_option_stocks("P", built, client=c)
        assert r.success is True
        body = c.calls[0][2]
        assert body.count("<ProductOption>") == 2      # 2옵션 모두 전송
        assert "<colCount>5</colCount>" in body
        assert "<colCount>3</colCount>" in body        # 보존된 옵션도 함께
        assert "opt_no" not in body                    # 패스스루 키는 XML 에 안 샘


# ═══════════ update_product_price_stock (배치 도구, inventory.py) ═══════════
class _SeqClient:
    """POST(재고조회)·POST(옵션수정)·GET(가격) 순서로 응답을 순차 반환하며 호출을 기록."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self._responses.pop(0)


_STOCKS_RESP = _TWO
_OPT_OK = ('<?xml version="1.0" encoding="euc-kr"?>'
           "<ClientMessage><resultCode>200</resultCode></ClientMessage>")
_OPT_FAIL = ('<?xml version="1.0" encoding="euc-kr"?>'
             "<ClientMessage><resultCode>300</resultCode><message>미승인</message></ClientMessage>")
_PRICE_OK = ('<?xml version="1.0" encoding="euc-kr"?>'
             "<ClientMessage><resultCode>200</resultCode><preSelPrc>10000</preSelPrc>"
             "<selPrc>12000</selPrc><prdNo>P</prdNo></ClientMessage>")
_PRICE_FAIL = ('<?xml version="1.0" encoding="euc-kr"?>'
               "<ClientMessage><resultCode>500</resultCode><message>시스템오류</message></ClientMessage>")


class TestBatchOrderAndSuccess:
    def test_get_then_build_then_update_then_price(self):
        from shared.platforms.eleven11 import inventory
        c = _SeqClient([_STOCKS_RESP, _OPT_OK, _PRICE_OK])
        r = inventory.update_product_price_stock("P", 12000, {"111": 5}, client=c)
        assert r.success is True
        # 호출 순서: 재고조회(POST stocks) → 옵션수정(POST updateProductOption) → 가격(GET)
        assert c.calls[0][0] == "POST" and c.calls[0][1].endswith("/prodmarket/stocks")
        assert c.calls[1][0] == "POST" and "updateProductOption" in c.calls[1][1]
        assert c.calls[2][0] == "GET" and "/product/price/" in c.calls[2][1]
        # 재고 XML 에 echo-back 2옵션 + 대상 교체
        opt_body = c.calls[1][2]
        assert opt_body.count("<ProductOption>") == 2
        assert "<colCount>5</colCount>" in opt_body

    def test_stock_only_when_price_none(self):
        from shared.platforms.eleven11 import inventory
        c = _SeqClient([_STOCKS_RESP, _OPT_OK])
        r = inventory.update_product_price_stock("P", None, {"111": 5}, client=c)
        assert r.success is True
        assert r.price_result is None
        assert len(c.calls) == 2   # 가격 GET 없음


class TestBatchFailureSurfacing:
    def test_stock_failure_skips_price_partial_prevention(self):
        """재고 full-replace 실패 → 가격 미전송(partial 방지)."""
        from shared.platforms.eleven11 import inventory
        c = _SeqClient([_STOCKS_RESP, _OPT_FAIL])
        r = inventory.update_product_price_stock("P", 12000, {"111": 5}, client=c)
        assert r.success is False
        assert r.stock_result is not None and r.stock_result.success is False
        assert r.price_result is None
        assert len(c.calls) == 2       # 가격 GET 안 감
        assert "미승인" in (r.error_message or "")

    def test_price_failure_after_stock_success_surfaced(self):
        from shared.platforms.eleven11 import inventory
        c = _SeqClient([_STOCKS_RESP, _OPT_OK, _PRICE_FAIL])
        r = inventory.update_product_price_stock("P", 12000, {"111": 5}, client=c)
        assert r.success is False
        assert r.stock_result.success is True
        assert r.price_result is not None and r.price_result.success is False

    def test_empty_stock_query_blocks_send(self):
        """재고조회가 옵션 0개면 full-replace 대상 없음 → 전송 보류(옵션 소실 방지)."""
        from shared.platforms.eleven11 import inventory
        empty = _stocks_xml()   # ProductStock 없음
        c = _SeqClient([empty])
        r = inventory.update_product_price_stock("P", 12000, {"111": 5}, client=c)
        assert r.success is False
        assert len(c.calls) == 1       # 옵션수정·가격 미전송
