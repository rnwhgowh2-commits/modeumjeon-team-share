# -*- coding: utf-8 -*-
"""가격 표시 결함 2건 회귀 방지 테스트.

결함 A: 스마트스토어 '현재가'가 옵션가(delta)만 써서 추가금 0원 옵션이 0원으로 둔갑.
        → 실판매가 = 기본가(salePrice) + 옵션가(add_price) 여야 함.
결함 B: 사입-판정 옵션의 '매입가'가 원시평균(purchase_avg_cost=0)을 써서 0원 둔갑.
        → 실제 해석 원가(purchase_resolved_avg)를 써야 함(엔진이 쓰는 단일 진실 원천).
"""
import pytest

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models", "lemouton.sets.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass


# ── 결함 A ────────────────────────────────────────────────────────────────
def test_smartstore_current_price_is_base_plus_option(monkeypatch):
    """스스 현재가 = 기본 판매가 + 옵션 추가금(delta), 추가금 0이어도 0원 아님."""
    from lemouton.uploader import market_fetch as mf
    from shared.platforms.smartstore import get_options as go
    from shared.platforms.smartstore import get_channel_no as gcn

    rows = [
        go.OptionRow(option_id=1, name1="블랙", name2="230", stock=5,
                     add_price=0, usable=True),
        go.OptionRow(option_id=2, name1="블랙", name2="240", stock=3,
                     add_price=2300, usable=True),
    ]
    fake = go.FetchOptionsResult(
        success=True, origin_product_no=111, product_name="P",
        sale_price=123900, options=rows)
    monkeypatch.setattr(go, "fetch_product_options",
                        lambda pid, client=None: fake)
    monkeypatch.setattr(gcn, "resolve_product_ids",
                        lambda pid, client=None: {"origin_product_no": pid})

    res = mf._fetch_smartstore("111", env_prefix=None)
    assert res.success
    prices = {o.option_id: o.price for o in res.options}
    # 추가금 0 옵션 → 0원이 아니라 기본 판매가 그대로여야 함(결함 A 방지)
    assert prices["1"] == 123900
    # 추가금 있는 옵션 → 기본가 + delta
    assert prices["2"] == 126200


def test_smartstore_price_survives_null_base(monkeypatch):
    """기본가가 None 이어도 예외 없이 옵션가로 폴백(폴백가 아님 — 값 부재 방어)."""
    from lemouton.uploader import market_fetch as mf
    from shared.platforms.smartstore import get_options as go
    from shared.platforms.smartstore import get_channel_no as gcn

    rows = [go.OptionRow(option_id=9, name1="블랙", name2="250", stock=1,
                         add_price=5000, usable=True)]
    fake = go.FetchOptionsResult(
        success=True, origin_product_no=1, product_name="P",
        sale_price=None, options=rows)
    monkeypatch.setattr(go, "fetch_product_options",
                        lambda pid, client=None: fake)
    monkeypatch.setattr(gcn, "resolve_product_ids",
                        lambda pid, client=None: {"origin_product_no": pid})

    res = mf._fetch_smartstore("1", env_prefix=None)
    assert res.success
    assert res.options[0].price == 5000


# ── 결함 B ────────────────────────────────────────────────────────────────
def test_card_purchase_cost_uses_resolved_avg(monkeypatch):
    """사입-판정 옵션의 매입가(final) = purchase_resolved_avg(엔진 원가), 원시평균(0) 아님."""
    from webapp.routes import api_pricing
    from webapp.routes import sets_api

    opt = {
        "sku": "SKU-1",
        "purchase_priority_resolved": "purchase",
        "purchase_stock": 5,
        "purchase_avg_cost": 0,        # 매입 이력 없음 → 원시평균 0
        "purchase_resolved_avg": 95000,  # 템플릿 폴백된 실제 해석 원가
        "src_stock": 5, "src_cost": 111510, "sources": [],
        "ss_price": 123900, "cp_price": 133900,
    }
    monkeypatch.setattr(api_pricing, "_option_matrix_data",
                        lambda mc: {"ok": True, "options": [opt]})

    out = sets_api._card_src_provider(["MODEL-1"], {"SKU-1"}, session=None)
    assert out["SKU-1"]["final"] == 95000       # 0원 아님(결함 B 방지)
    assert out["SKU-1"]["source_name"] == "사입"
    assert out["SKU-1"]["surface"] is None
