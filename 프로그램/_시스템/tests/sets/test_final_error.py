# -*- coding: utf-8 -*-
"""최종매입가 '계산 실패'가 '정상 미확정(None)'과 구분되어 표면화되는지 (#14)."""
import webapp.routes.api_pricing as ap
import webapp.routes.api_benefits as ab
import webapp.routes.sets_api as sa


def _matrix_with_source(_mc):
    return {"ok": True, "options": [
        {"sku": "S1", "purchase_priority_resolved": "source",
         "src_stock_qty": 5, "ss_price": 140000, "cp_price": 140000,
         "sources": [{"source_id": 3, "source_name": "르무통",
                      "product_url": "http://x", "crawled_price": 119900,
                      "last_status": "ok", "source_product_id": 10}]},
    ]}


def test_breakdown_failure_sets_final_error(monkeypatch):
    monkeypatch.setattr(ap, "_option_matrix_data", _matrix_with_source)
    monkeypatch.setattr(ab, "_build_breakdown_cache", lambda s, items: {})

    def boom(*a, **k):
        raise RuntimeError("breakdown boom")

    monkeypatch.setattr(ab, "compute_breakdown", boom)
    out = sa._card_src_provider(["MC"], {"S1"}, session=object())
    # 계산 실패 → final 은 None 이되, 정상 미확정과 구분되게 final_error=True
    assert out["S1"]["final"] is None
    assert out["S1"]["final_error"] is True


def test_breakdown_ok_no_error(monkeypatch):
    monkeypatch.setattr(ap, "_option_matrix_data", _matrix_with_source)
    monkeypatch.setattr(ab, "_build_breakdown_cache", lambda s, items: {})
    monkeypatch.setattr(ab, "compute_breakdown",
                        lambda *a, **k: {"final_price": 100000, "sale_price": 119900, "steps": []})
    out = sa._card_src_provider(["MC"], {"S1"}, session=object())
    assert out["S1"]["final"] == 100000
    assert out["S1"]["final_error"] is False
