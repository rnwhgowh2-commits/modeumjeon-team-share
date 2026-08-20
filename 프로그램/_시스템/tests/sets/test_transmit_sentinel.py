# -*- coding: utf-8 -*-
"""전송/미리보기 '보낼 재고'에 센티넬(999/6993)이 새지 않는지 (#10)."""
import webapp.routes.api_pricing as ap
import webapp.routes.sets_api as sa


def _fake_matrix(_mc):
    return {"ok": True, "options": [
        # 소싱 옵션: raw 재고는 센티넬 999(수량미상), 실수량(src_stock_qty)은 None
        {"sku": "S1", "purchase_priority_resolved": "source",
         "src_stock": 999, "src_stock_qty": None,
         "ss_price": 140000, "cp_price": 140000, "is_active": True},
        # 실수량이 있는 옵션은 그 값 그대로
        {"sku": "S2", "purchase_priority_resolved": "source",
         "src_stock": 7, "src_stock_qty": 7,
         "ss_price": 140000, "cp_price": 140000, "is_active": True},
    ]}


def test_transmit_stock_excludes_sentinel(monkeypatch):
    monkeypatch.setattr(ap, "_option_matrix_data", _fake_matrix)
    out = sa._new_values_for_options(["MC"], {"S1", "S2"}, "smartstore")
    # 센티넬 999 는 전송값으로 새지 않고 '미상'(None) 으로
    assert out["S1"]["stock"] is None
    # 실수량은 그대로 유지
    assert out["S2"]["stock"] == 7
