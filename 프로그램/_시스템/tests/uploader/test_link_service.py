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


def test_fetch_smartstore_maps_options(monkeypatch):
    # 실제 _fetch_smartstore 본체를 검증: 소스 모듈의 fetch_product_options 를
    # 가짜로 교체하면 _fetch_smartstore 의 지역 import 가 가짜를 집어든다.
    from shared.platforms.smartstore import get_options as go
    from lemouton.uploader import market_fetch
    from lemouton.uploader.linker import MarketOption

    def fake_fetch(origin_product_no, client=None):
        return go.FetchOptionsResult(
            success=True, origin_product_no=origin_product_no,
            product_name="에어포스 1", sale_price=115900,
            options=[
                go.OptionRow(option_id=111, name1="블랙", name2="260", stock=4, add_price=0),
                go.OptionRow(option_id=222, name1="블루", name2="270", stock=0, add_price=0, usable=False),
            ])

    monkeypatch.setattr(go, "fetch_product_options", fake_fetch)

    fr = market_fetch.fetch_market_options("smartstore", "999")
    assert fr.success is True
    assert fr.product_name == "에어포스 1"
    assert len(fr.options) == 2
    assert fr.options[0] == MarketOption(option_id="111", color="블랙", size="260", stock=4, price=0)
    assert fr.options[1].option_id == "222"
    assert fr.options[0].usable is True
    assert fr.options[1].usable is False


def test_fetch_smartstore_bad_product_id():
    from lemouton.uploader import market_fetch
    fr = market_fetch.fetch_market_options("smartstore", "abc")
    assert fr.success is False
    assert "abc" in (fr.error or "")


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


def test_link_duplicate_canonical_sku_writes_none(db):
    # 두 마켓옵션이 같은 SKU(블랙/260)로 정규화 → 어느 쪽이 옳은 바인딩인지 알 수 없음
    # → 둘 다 쓰지 않고 duplicate 로 표면화. linked 는 정직하게 0.
    def _dup_fetch(market, product_id):
        from lemouton.uploader.market_fetch import FetchResult
        from lemouton.uploader.linker import MarketOption
        return FetchResult(
            success=True, product_name="에어포스 상품", error=None,
            options=[
                MarketOption(option_id="AA", color="블랙", size="260", stock=1),
                MarketOption(option_id="BB", color="black", size="260mm", stock=2),
            ])
    result = link_bundle_market(
        db, model_code="AF", market="smartstore",
        market_product_id="777", fetcher=_dup_fetch)
    assert result["ok"] is True
    assert result["linked"] == 0
    assert result["duplicate"] == 2
    # 충돌 SKU 는 한 행도 쓰이지 않아야 함
    from lemouton.uploader.models import MarketRegistration
    assert db.query(MarketRegistration).filter_by(canonical_sku="AF-블랙-260").count() == 0


def test_fetch_coupang_maps_options(monkeypatch):
    # 실제 _fetch_coupang 본체 검증: 소스 모듈의 get_product 를 가짜로 교체.
    from shared.platforms.coupang import products as cp
    from lemouton.uploader import market_fetch
    from lemouton.uploader.linker import MarketOption

    fake_detail = {
        "sellerProductName": "에어포스 쿠팡",
        "items": [
            {"itemName": "블랙/260",
             "marketplaceItemData": {"vendorItemId": 111, "priceData": {"salePrice": 128900}},
             "attributes": [{"attributeTypeName": "색상", "attributeValueName": "블랙"},
                            {"attributeTypeName": "사이즈", "attributeValueName": "260"}]},
            {"itemName": "블루/270",
             "marketplaceItemData": {"vendorItemId": 222, "priceData": {"salePrice": 129900}},
             "attributes": [{"attributeTypeName": "색상", "attributeValueName": "블루"},
                            {"attributeTypeName": "사이즈", "attributeValueName": "270"}]},
        ],
    }
    monkeypatch.setattr(cp, "get_product", lambda spid, client=None: fake_detail)
    fr = market_fetch.fetch_market_options("coupang", "999")
    assert fr.success is True
    assert fr.product_name == "에어포스 쿠팡"
    assert len(fr.options) == 2
    assert fr.options[0] == MarketOption(option_id="111", color="블랙", size="260", stock=0, price=128900)
    assert fr.options[1].option_id == "222"


def test_fetch_coupang_bad_product_id():
    from lemouton.uploader import market_fetch
    fr = market_fetch.fetch_market_options("coupang", "abc")
    assert fr.success is False
    assert "abc" in (fr.error or "")
