# -*- coding: utf-8 -*-
"""[TEST] 매트릭스 정보창의 가격은 **표면가와 최종매입가를 나눠서** 준다.

버그였던 상태 (2026-07-31 이전):
  `_rows_for()` 가 `SourceOption.current_price`(= 표면노출가, 혜택 차감 **전**)를
  그대로 「매입가」라는 이름으로 화면에 내보냈다. 혜택이 큰 소싱처일수록 실제보다
  비싸 보였고, 「최저」 표시도 실제로 내는 돈이 아니라 표면가로 판정됐다.
  (memory: project_crawl_log_vs_final_price — 이 프로젝트에서 반복된 사고 지점)

지켜야 할 것:
  · surface(표면가)와 final(최종매입가)은 **다른 칸**이다
  · 혜택이 있으면 final < surface
  · 계산하지 못하면 final = None — **표면가로 메우지 않는다**
    (feedback_no_fallback_price_on_match_fail)
"""
import os

import pytest
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

import lemouton.sourcing.models as M           # noqa: E402
from shared.db import Base                     # noqa: E402
from webapp.routes.matrix import _rows_for     # noqa: E402

SURFACE = 100_000
BENEFIT_RATE = 0.10
SKU = "SKU-MX000001"
# source_ids._SITE_BY_PRICING_ID 의 '롯데온' 계산 번호. _rows_for 는 site 키로
#   pricing_source_id() 를 태우므로, 테스트도 실제 번호를 그대로 써야 한다.
LOTTEON_PRICING_ID = 5


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _seed(s, *, site="lotteon", with_benefit=True):
    """모델·옵션 1개 + 소싱처 상품/옵션(표면가 SURFACE) + 10% 혜택 템플릿."""
    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
    from lemouton.sourcing.models_pricing import OptionSourceUrl, SourceRegistry

    s.add(M.Model(model_code="MX", model_name_raw="테스트", article_no="ART-1"))
    s.add(M.Option(canonical_sku=SKU, model_code="MX",
                   color_code="블랙", size_code="260", is_active=True))
    url = f"https://{site}.example.com/p/1"

    if with_benefit:
        s.add(SourceRegistry(id=LOTTEON_PRICING_ID, name="롯데온",
                             main_url="https://lotteon.com", sort_order=0))
        s.flush()
        s.add(OptionSourceUrl(canonical_sku=SKU, source_id=LOTTEON_PRICING_ID,
                              product_url=url))
        s.add(M.SourceBenefitTemplate(
            source_id=LOTTEON_PRICING_ID, benefit_name="테스트 정률할인",
            benefit_type="rate", value=BENEFIT_RATE, enabled=True, sort_order=0))

    sp = SourceProduct(site=site, url=url, last_price=SURFACE, last_stock=5,
                       last_status="ok", display_no="LO20260731-100001")
    s.add(sp)
    s.flush()
    so = SourceOption(source_product_id=sp.id, color_text="블랙", size_text="260",
                      current_stock=5, current_price=SURFACE,
                      display_no="LO20260731-000001")
    s.add(so)
    s.flush()
    s.add(OptionSourceLink(canonical_sku=SKU, source_option_id=so.id))
    s.commit()


def _cell(s):
    rows, _colors, _sizes = _rows_for(s, [SKU])
    assert len(rows) == 1
    return rows[0]


def test_표면가와_최종매입가가_다른_칸으로_나온다(db):
    _seed(db)
    r = _cell(db)
    src = r["sources"][0]

    assert src["surface"] == SURFACE, "표면노출가는 그대로 나와야 한다"
    assert src["final"] is not None, "최종매입가가 계산되지 않았다"
    assert src["final"] < SURFACE, (
        f"혜택이 반영 안 됨 — 최종매입가 {src['final']} 가 표면가 {SURFACE} 그대로")


def test_옛_이름_price_는_더_이상_주지_않는다(db):
    """「매입가」라는 이름 하나로 표면가를 내보내던 칸이 사라졌는지 고정."""
    _seed(db)
    src = _cell(db)["sources"][0]
    assert "price" not in src, "표면가를 「price(매입가)」로 다시 내보내면 안 된다"
    # 계산용 내부 키가 화면으로 새지 않는다
    for leaked in ("crawled_price", "source_id", "source_product_id",
                   "final_purchase_price"):
        assert leaked not in src


def test_최저값도_두_가지로_나온다(db):
    _seed(db)
    r = _cell(db)
    assert r["min_surface"] == SURFACE
    assert r["min_final"] is not None and r["min_final"] < SURFACE
    assert "min_price" not in r


def test_계산할_수_없으면_표면가로_메우지_않는다(db):
    """혜택 계산이 불가능한 소싱처 → final=None(「확인 불가」). 표면가 폴백 금지."""
    _seed(db, site="unknown_site", with_benefit=False)
    r = _cell(db)
    src = r["sources"][0]
    assert src["surface"] == SURFACE
    assert src["final"] is None, "가짜 매입가(표면가)를 채워 넣었다"
    assert r["min_final"] is None
