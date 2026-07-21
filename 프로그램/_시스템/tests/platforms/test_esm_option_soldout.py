# -*- coding: utf-8 -*-
"""ESM 옵션 재고/품절 — 공개문서 /26 규격 고정.

🔴 이 경로는 **실제로 배선돼 있다**(uploader/adapters/esm.py → update_stock).
문서 제약을 어기면 마켓이 거부하는데, 우리는 성공으로 알고 계속 판다 = 오버셀.

문서 /26 확정 사실:
  · qty 는 **1~99,999**. **0 불가** (에러 1000 "Gmkt/Iac 필드는 1에서 99999 사이")
  · 품절은 qty 가 아니라 **isSoldOut: true**
  · **모든 옵션이 품절인 상태는 불가** (에러 3000) → 그 경우는 상품 판매중지로 가야 함
"""
from __future__ import annotations

import pytest

from shared.platforms.esm import inventory as INV


class _FakeClient:
    def __init__(self, get_details, put_resp=None):
        self._get_details = get_details
        self._put_resp = put_resp or {"resultCode": 0}
        self.calls = []
        self._cfg = {"paths": {"options": "/item/v1/goods/{goodsNo}/recommended-options"}}

    def request(self, *, method, path, body=None, **kw):
        self.calls.append({"method": method, "path": path, "body": body})
        if method == "GET":
            # 실제 recommended-options GET 봉투 구조.
            return {"type": 1, "isStockManage": True,
                    "independent": {"details": self._get_details, "recommendedOptNo": 976}}
        return self._put_resp


def _details():
    """옵션 3개 — 전부 판매중, 재고 있음."""
    return [
        {"manageCode": "OPT-S", "isSoldOut": False, "isDisplay": True, "qty": {"iac": 10, "gmkt": 10}},
        {"manageCode": "OPT-M", "isSoldOut": False, "isDisplay": True, "qty": {"iac": 20, "gmkt": 20}},
        {"manageCode": "OPT-L", "isSoldOut": False, "isDisplay": True, "qty": {"iac": 30, "gmkt": 30}},
    ]


def _put_body(cli):
    # PUT 은 GET 봉투 통째로 되돌린다 → details 를 품은 independent 를 돌려준다.
    return [c for c in cli.calls if c["method"] == "PUT"][0]["body"]["independent"]


def _by_code(details, code):
    return next(d for d in details if d.get("manageCode") == code)


class TestOptionSoldOut:
    """재고 0 = 품절 의도. qty 0 으로 보내면 마켓이 거부한다."""

    def test_zero_stock_sets_sold_out_flag_not_qty_zero(self):
        cli = _FakeClient(_details())
        assert INV.update_stock("2035313538", "auction", "OPT-M", 0, client=cli) is True

        sent = _by_code(_put_body(cli)["details"], "OPT-M")
        assert sent["isSoldOut"] is True, "품절은 isSoldOut 으로 표현해야 한다"
        assert sent["qty"]["iac"] != 0, "qty 0 은 문서상 무효(에러 1000)"

    def test_zero_stock_never_sends_zero_qty_anywhere(self):
        cli = _FakeClient(_details())
        INV.update_stock("2035313538", "auction", "OPT-M", 0, client=cli)
        for d in _put_body(cli)["details"]:
            for v in (d.get("qty") or {}).values():
                assert v != 0

    def test_restock_clears_sold_out_flag(self):
        """재입고면 품절 해제까지 같이 돼야 한다. 안 그러면 재고만 차고 계속 품절로 보인다."""
        det = _details()
        _by_code(det, "OPT-M").update({"isSoldOut": True, "qty": {"iac": 1, "gmkt": 20}})
        cli = _FakeClient(det)
        INV.update_stock("2035313538", "auction", "OPT-M", 15, client=cli)

        sent = _by_code(_put_body(cli)["details"], "OPT-M")
        assert sent["isSoldOut"] is False
        assert sent["qty"]["iac"] == 15


class TestAllSoldOutRefused:
    """문서 에러 3000 — 모든 옵션 품절은 등록 불가. 보내기 전에 막고 사유를 말한다."""

    def test_last_sellable_option_going_soldout_is_refused(self):
        det = _details()
        _by_code(det, "OPT-S")["isSoldOut"] = True
        _by_code(det, "OPT-L")["isSoldOut"] = True
        cli = _FakeClient(det)

        with pytest.raises(ValueError) as e:
            INV.update_stock("2035313538", "auction", "OPT-M", 0, client=cli)
        msg = str(e.value)
        assert "판매중지" in msg, "대안(상품 판매중지)을 사유에 담아야 한다"
        assert not [c for c in cli.calls if c["method"] == "PUT"], "거부될 요청이 나갔다"

    def test_not_refused_when_another_option_still_sellable(self):
        det = _details()
        _by_code(det, "OPT-S")["isSoldOut"] = True
        cli = _FakeClient(det)
        assert INV.update_stock("2035313538", "auction", "OPT-M", 0, client=cli) is True


class TestQtyRangeValidated:
    def test_over_max_is_refused(self):
        cli = _FakeClient(_details())
        with pytest.raises(ValueError):
            INV.update_stock("2035313538", "auction", "OPT-M", 100000, client=cli)
        assert not [c for c in cli.calls if c["method"] == "PUT"]

    def test_existing_invalid_qty_on_other_option_is_surfaced(self):
        """다른 옵션이 이미 잘못된 재고를 갖고 있으면 full-replace 전체가 거부된다.

        조용히 고치지 않는다(폴백 금지) — 어느 옵션인지 짚어서 실패시킨다.
        """
        det = _details()
        _by_code(det, "OPT-L")["qty"] = {"iac": 0, "gmkt": 30}
        cli = _FakeClient(det)
        with pytest.raises(ValueError) as e:
            INV.update_stock("2035313538", "auction", "OPT-M", 5, client=cli)
        assert "OPT-L" in str(e.value)

    def test_normal_update_still_works(self):
        cli = _FakeClient(_details())
        assert INV.update_stock("2035313538", "auction", "OPT-M", 7, client=cli) is True
        sent = _by_code(_put_body(cli)["details"], "OPT-M")
        assert sent["qty"]["iac"] == 7 and sent["qty"]["gmkt"] == 20
        assert sent["isSoldOut"] is False
