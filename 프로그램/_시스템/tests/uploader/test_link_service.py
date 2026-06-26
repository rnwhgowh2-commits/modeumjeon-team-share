"""link_service — in-memory SQLite 통합 테스트 (가짜 fetcher 주입, 네트워크 없음)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

# create_all 이 FK 타겟까지 찾도록 전체 모델 등록 (app.py 와 동일)
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
from lemouton.uploader.linker import MarketOption
from lemouton.uploader.link_service import link_bundle_market
from lemouton.uploader.models import MarketRegistration


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(M.Model(model_code="AF", model_name_raw="에어포스"))
    s.add(M.Option(canonical_sku="AF-블랙-260", model_code="AF",
                   color_code="블랙", color_display="블랙",
                   size_code="260", size_display="260"))
    s.add(M.Option(canonical_sku="AF-블루-270", model_code="AF",
                   color_code="블루", color_display="블루",
                   size_code="270", size_display="270"))
    s.commit()
    yield s
    s.close()


def _fake_fetcher_ok(market, product_id):
    from lemouton.uploader.market_fetch import FetchResult
    return FetchResult(
        success=True, product_name="에어포스 상품", error=None,
        options=[
            MarketOption(option_id="11", color="블랙", size="260", stock=5),
            MarketOption(option_id="22", color="navy", size="270mm", stock=0),
            MarketOption(option_id="33", color="레드", size="999", stock=3),  # 미매칭
        ])


def test_link_persists_matched_only(db):
    result = link_bundle_market(
        db, model_code="AF", market="smartstore",
        market_product_id="555", fetcher=_fake_fetcher_ok)
    assert result["ok"] is True
    assert result["linked"] == 2
    assert result["unmatched"] == 1
    regs = {r.canonical_sku: r for r in db.query(MarketRegistration).all()}
    assert set(regs) == {"AF-블랙-260", "AF-블루-270"}
    assert regs["AF-블랙-260"].market_option_id == "11"
    assert regs["AF-블랙-260"].market_product_id == "555"
    assert regs["AF-블랙-260"].status == "linked"
    assert regs["AF-블루-270"].market_option_id == "22"


def test_link_fetch_failure_returns_error(db):
    def _bad(market, product_id):
        from lemouton.uploader.market_fetch import FetchResult
        return FetchResult(success=False, product_name=None, options=[],
                           error="상품을 찾을 수 없어요")
    result = link_bundle_market(
        db, model_code="AF", market="smartstore",
        market_product_id="999", fetcher=_bad)
    assert result["ok"] is False
    assert result["linked"] == 0
    assert db.query(MarketRegistration).count() == 0
