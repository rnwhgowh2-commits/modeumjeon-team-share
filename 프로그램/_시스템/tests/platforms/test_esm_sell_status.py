# -*- coding: utf-8 -*-
"""ESM 가격/재고/판매상태(sell-status) — 공개문서 /21·/194 규격 고정.

이 테스트가 지키는 것은 전부 **문서에 적힌 제약**이고, 어기면 마켓이 거부하거나
(더 나쁘게는) 엉뚱한 값이 올라간다. 특히 재고 0 은 품절 의도인데 마켓 규격상 무효라
조용히 실패하면 품절이 안 올라가고 그대로 팔린다 = 오버셀.
"""
from __future__ import annotations

import pytest

from shared.platforms.esm import inventory as INV


class _FakeClient:
    """request(method, path, body) 를 기록하고 정해진 응답을 돌려주는 가짜 클라이언트."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, *, method, path, body=None, **kw):
        self.calls.append({"method": method, "path": path, "body": body})
        if not self._responses:
            raise AssertionError(f"예상 못 한 추가 호출: {method} {path}")
        return self._responses.pop(0)


_CFG = {
    "paths": {
        "sell_status": "/item/v1/goods/{goodsNo}/sell-status",
        "stock_change": "/item/v1/goods/{goodsNo}/stock",
    }
}


def _client(responses):
    c = _FakeClient(responses)
    c._cfg = _CFG
    return c


# GET 응답 — ★문서 그대로 대문자 키(IsSell/Price/Stock/SellingPeriod)이고
#   SellingPeriod 는 기간이 아니라 **종료일 YYYYMMDD** 다.
_GET_OK = {
    "IsSell": {"gmkt": True, "iac": True},
    "itemBasicInfo": {
        "Price": {"gmkt": 10000.0, "iac": 10000.0},
        "Stock": {"gmkt": 99999, "iac": 120},
        "SellingPeriod": {"gmkt": 20190328, "iac": 20190328},
    },
}
_PUT_OK = {"goodsNo": 2035313538, "resultCode": 0, "message": None}


class TestStockRangeGuard:
    """재고 유효범위 1~99,999 (문서 /194·/21). 범위를 벗어나면 **보내기 전에** 막는다."""

    def test_zero_stock_is_rejected_not_sent(self):
        """0 은 마켓 규격상 무효 — 품절은 isSell=false 로 가야 한다.

        여기서 안 막으면 마켓이 400/1000 으로 거부하고, 우리는 '품절 올렸다'고
        착각한 채 계속 판다(오버셀).
        """
        cli = _client([])
        with pytest.raises(ValueError) as e:
            INV.update_base_stock("2035313538", "auction", 0, client=cli)
        assert "품절" in str(e.value) or "1~99999" in str(e.value).replace(",", "")
        assert cli.calls == [], "막아야 할 요청이 마켓으로 나갔다"

    def test_over_max_stock_is_rejected(self):
        cli = _client([])
        with pytest.raises(ValueError):
            INV.update_base_stock("2035313538", "auction", 100000, client=cli)
        assert cli.calls == []

    def test_negative_stock_is_rejected(self):
        cli = _client([])
        with pytest.raises(ValueError):
            INV.update_base_stock("2035313538", "auction", -1, client=cli)
        assert cli.calls == []

    def test_valid_stock_is_sent(self):
        cli = _client([_PUT_OK])
        assert INV.update_base_stock("2035313538", "auction", 60, client=cli) is True
        assert cli.calls[0]["method"] == "PUT"
        assert cli.calls[0]["path"] == "/item/v1/goods/2035313538/stock"
        assert cli.calls[0]["body"] == {"stock": {"iac": 60}}


class TestSellStatusEchoBack:
    """sell-status 는 전 필드가 필수라 **읽고 그대로 되돌려 보내되** 목표만 바꾼다."""

    def test_reads_then_writes_only_target_site(self):
        cli = _client([_GET_OK, _PUT_OK])
        assert INV.set_stock_via_sell_status("2035313538", "auction", 55, client=cli) is True

        get_call, put_call = cli.calls
        assert get_call["method"] == "GET"
        assert put_call["method"] == "PUT"
        b = put_call["body"]
        # 목표(옥션)만 바뀌고 G마켓은 읽은 값 그대로
        assert b["itemBasicInfo"]["stock"] == {"gmkt": 99999, "iac": 55}
        assert b["itemBasicInfo"]["price"] == {"gmkt": 10000.0, "iac": 10000.0}
        assert b["isSell"] == {"gmkt": True, "iac": True}

    def test_put_uses_lowercase_keys_not_get_casing(self):
        """GET 은 IsSell/Price/Stock 대문자, PUT 은 isSell/price/stock 소문자.

        읽은 걸 그대로 되돌리면 대문자로 나가서 마켓이 못 알아듣는다.
        """
        cli = _client([_GET_OK, _PUT_OK])
        INV.set_stock_via_sell_status("2035313538", "auction", 55, client=cli)
        b = cli.calls[1]["body"]
        assert "isSell" in b and "IsSell" not in b
        info = b["itemBasicInfo"]
        assert {"price", "stock", "sellingPeriod"} <= set(info)
        assert not {"Price", "Stock", "SellingPeriod"} & set(info)

    def test_selling_period_is_maintain_not_echoed_date(self):
        """★ 최대 함정 — GET 의 SellingPeriod 는 **종료일(20190328)**,
        PUT 은 **기간(-1/0/15/30/60/90/365)**. 되돌려 보내면 2천만일짜리 기간이 된다.
        유지 = 0 으로 보낸다.
        """
        cli = _client([_GET_OK, _PUT_OK])
        INV.set_stock_via_sell_status("2035313538", "auction", 55, client=cli)
        assert cli.calls[1]["body"]["itemBasicInfo"]["sellingPeriod"] == {"gmkt": 0, "iac": 0}

    def test_sell_status_also_guards_stock_range(self):
        cli = _client([])
        with pytest.raises(ValueError):
            INV.set_stock_via_sell_status("2035313538", "auction", 0, client=cli)
        assert cli.calls == []


class TestSoldOut:
    """품절 = 재고 0 이 아니라 **판매중지(isSell=false)**."""

    def test_sold_out_stops_only_target_site(self):
        cli = _client([_GET_OK, _PUT_OK])
        assert INV.set_sold_out("2035313538", "auction", client=cli) is True
        b = cli.calls[1]["body"]
        assert b["isSell"] == {"gmkt": True, "iac": False}
        # 재고는 건드리지 않는다(0 으로 보내면 규격 위반)
        assert b["itemBasicInfo"]["stock"]["iac"] == 120

    def test_sold_out_never_sends_zero_stock(self):
        cli = _client([_GET_OK, _PUT_OK])
        INV.set_sold_out("2035313538", "gmarket", client=cli)
        stock = cli.calls[1]["body"]["itemBasicInfo"]["stock"]
        assert 0 not in stock.values()
