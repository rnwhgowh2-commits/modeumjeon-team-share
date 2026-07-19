# -*- coding: utf-8 -*-
"""[TEST] 옵션 매트릭스의 소싱 판매가는 **최종매입가**(혜택 차감 후) 기준이다.

배경 (2026-07-19 사장님 확정):
  "원가는 이전에도 최종매입가였어. 원가로부터 마진을 붙이는 거야."

버그였던 상태:
  화면 셀은 최종매입가(compute_breakdown.final_price)를 보여주는데, 마켓 업로드가
  (ss_price/cp_price)는 표면노출가(crawled_price)에 마진을 붙여 계산했다.
  → 원가를 실제보다 높게 잡아 판매가가 필요 이상으로 높았다(표시≠업로드).

이 테스트는 매트릭스 엔드포인트를 실제로 태워서, 혜택이 있는 소싱처의 판매가가
표면가 기준이 아니라 최종매입가 기준으로 나오는지 end-to-end 로 고정한다.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault("ENVIRONMENT", "test")

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import lemouton.sourcing.models as M
from shared.db import Base

SURFACE = 100_000
BENEFIT_RATE = 0.10          # 10% 혜택 → 최종매입가 90,000
EXPECTED_FINAL = 90_000
SKU = "LT-블랙-260"


def _make_db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    from sqlalchemy import text
    s.execute(text("PRAGMA foreign_keys=ON"))
    return s


def _seed(s, *, with_benefit: bool):
    """모델·옵션 + 크롤된 소싱처(표면가 SURFACE). with_benefit 면 10% 혜택 템플릿 부착."""
    from lemouton.sourcing.models_pricing import OptionSourceUrl, SourceRegistry
    from lemouton.sources.models import SourceProduct, SourceOption

    s.add(M.Model(model_code="LT", model_name_raw="테스트"))
    s.add(M.Option(canonical_sku=SKU, model_code="LT",
                   color_code="블랙", size_code="260", is_active=True))

    URL = "https://lotteon.com/p/product/LT_BLACK"
    sr = SourceRegistry(name="롯데온", main_url="https://lotteon.com", sort_order=0)
    s.add(sr)
    s.flush()

    # 혜택 템플릿 조회는 OptionSourceUrl(sku, source_id) 링크를 타고 이뤄진다.
    s.add(OptionSourceUrl(canonical_sku=SKU, source_id=sr.id, product_url=URL))

    bsu = M.BundleSourceUrl(model_code="LT", source_key="lotteon", url=URL,
                            sort_order=0, url_type="단품")
    s.add(bsu)
    s.flush()
    s.add(M.OptionSourceUrlLink(option_canonical_sku=SKU,
                                bundle_source_url_id=bsu.id))

    sp = SourceProduct(site="lotteon", url=URL, last_price=SURFACE,
                       last_stock=5, last_status="ok")
    s.add(sp)
    s.flush()
    s.add(SourceOption(source_product_id=sp.id, color_text="블랙", size_text="260",
                       current_stock=5, current_price=SURFACE))

    if with_benefit:
        s.add(M.SourceBenefitTemplate(
            source_id=sr.id, benefit_name="테스트 정률할인", benefit_type="rate",
            value=BENEFIT_RATE, enabled=True, sort_order=0))
    s.commit()
    return sr.id


def _matrix(s):
    from webapp.routes.api_pricing import _option_matrix_data
    import webapp.routes.api_pricing as _mod
    from unittest.mock import patch
    with patch.object(_mod, "SessionLocal", return_value=s):
        return _option_matrix_data("LT")


def _entry(result):
    return next((o for o in result.get("options", []) if o.get("sku") == SKU), None)


def test_src_cost_is_final_purchase_price_not_surface():
    """원가(src_cost) = 최종매입가 90,000. 표면가 100,000 은 src_surface 로 따로."""
    s = _make_db()
    _seed(s, with_benefit=True)
    o = _entry(_matrix(s))
    assert o is not None

    assert o["src_surface"] == SURFACE, "표면노출가는 그대로 노출되어야 한다"
    assert o["src_cost"] == EXPECTED_FINAL, (
        f"원가는 최종매입가({EXPECTED_FINAL:,})여야 하는데 {o['src_cost']} "
        f"— 표면가({SURFACE:,})면 원가 과대계상 버그"
    )


def test_cell_final_purchase_price_injected():
    """셀(sources[])에도 최종매입가가 주입된다 — 화면·업로드 공통 원천."""
    s = _make_db()
    _seed(s, with_benefit=True)
    o = _entry(_matrix(s))
    cell = next(c for c in o["sources"] if c.get("source_key") == "lotteon")
    assert cell["crawled_price"] == SURFACE
    assert cell["final_purchase_price"] == EXPECTED_FINAL


def test_market_price_lower_than_surface_based():
    """판매가가 '표면가로 계산했을 때'보다 낮아야 한다 (= 혜택이 판매가에 반영)."""
    from lemouton.pricing.unified import compute_market_price

    s = _make_db()
    _seed(s, with_benefit=True)
    o = _entry(_matrix(s))

    surface_based_ss = compute_market_price(None, "ss", "sourcing", SURFACE).final_price
    final_based_ss = compute_market_price(None, "ss", "sourcing", EXPECTED_FINAL).final_price

    assert o["ss_price"] == final_based_ss, (
        f"ss_price 는 최종매입가 기준({final_based_ss:,})이어야 하는데 {o['ss_price']}"
    )
    assert o["ss_price"] < surface_based_ss, (
        f"혜택이 판매가에 반영 안 됨 — 표면가 기준 {surface_based_ss:,} 그대로"
    )


def test_no_benefit_means_final_equals_surface():
    """혜택이 없으면 최종매입가 = 표면가 → 기존 판매가와 동일(무혜택 상품 회귀 없음)."""
    s = _make_db()
    _seed(s, with_benefit=False)
    o = _entry(_matrix(s))

    from lemouton.pricing.unified import compute_market_price
    assert o["src_cost"] == SURFACE
    assert o["ss_price"] == compute_market_price(
        None, "ss", "sourcing", SURFACE).final_price
