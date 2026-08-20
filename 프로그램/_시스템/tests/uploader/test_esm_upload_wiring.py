# -*- coding: utf-8 -*-
"""[TEST] 옥션·G마켓(ESM 2.0) 업로드/연동 배선 — 어댑터·플랫폼 래퍼·오케스트레이터 라우팅.

라이브 미검증(키 없음) 상태에서 코드 근거를 Fake/Mock 으로 검증한다.
근거 스펙: docs/markets/auction.yaml · gmarket.yaml (ESM Trading API 공개문서 실측 2026-07-09).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

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


# ──────────────────────────────────────────────────────────
#  Fake EsmClient — HTTP 없이 request(method, path, body) 가로채기
# ──────────────────────────────────────────────────────────

class FakeEsmClient:
    def __init__(self, config=None, responses=None):
        self._cfg = config or {"paths": {
            "detail": "/item/v1/goods/{goodsNo}",
            "options": "/item/v1/goods/{goodsNo}/recommended-options",
            "price_change": "/item/v1/goods/{goodsNo}/price",
            "stock_change": "/item/v1/goods/{goodsNo}/stock",
            "site_goods_map": "/item/v1/site-goods/{siteGoodsNo}/goods-no",
        }}
        self.calls = []
        self.responses = responses or {}

    def request(self, method, path, body=None):
        self.calls.append({"method": method, "path": path, "body": body})
        resp = self.responses.get((method, path))
        if resp is None:
            resp = self.responses.get(path)
        if callable(resp):
            return resp(body)
        return resp if resp is not None else {"resultCode": 0}


_G1 = "G1000001"
_OPT_PATH = f"/item/v1/goods/{_G1}/recommended-options"
_PRICE_PATH = f"/item/v1/goods/{_G1}/price"


# ──────────────────────────────────────────────────────────
#  products.extract_options — 옵션 파싱(사이트별 재고·추가금)
# ──────────────────────────────────────────────────────────

class TestExtractOptions:
    def _detail(self):
        return {
            "goodsNo": _G1,
            "itemBasicInfo": {"goodsName": {"kor": "테스트상품"}},
            "itemAddtionalInfo": {"recommendedOpts": {"independent": {"details": [
                {"manageCode": "OPT-BLK-260", "recommendedOptValue": "블랙,260",
                 "qty": {"gmkt": 7, "iac": 3}, "addAmnt": 0, "isSoldOut": False},
                {"manageCode": "OPT-WHT-270", "recommendedOptValue1": "화이트",
                 "recommendedOptValue2": "270", "qty": {"Gmkt": 0, "Iac": 0},
                 "addAmnt": 5000, "isSoldOut": True},
            ]}}},
        }

    def test_gmarket_reads_gmkt_stock(self):
        from shared.platforms.esm.products import extract_options
        opts = extract_options(self._detail(), "gmarket")
        assert len(opts) == 2
        assert opts[0]["option_id"] == "OPT-BLK-260"
        assert opts[0]["color"] == "블랙"
        assert opts[0]["size"] == "260"
        assert opts[0]["stock"] == 7           # gmkt
        assert opts[1]["stock"] == 0           # Gmkt (대소문자 무시)
        assert opts[1]["add_amount"] == 5000
        assert opts[1]["sold_out"] is True

    def test_auction_reads_iac_stock(self):
        from shared.platforms.esm.products import extract_options
        opts = extract_options(self._detail(), "auction")
        assert opts[0]["stock"] == 3           # iac

    def test_missing_option_id_skipped(self):
        from shared.platforms.esm.products import extract_options
        src = {"details": [{"recommendedOptValue": "블랙,260", "qty": {"gmkt": 1}}]}
        assert extract_options(src, "gmarket") == []


# ──────────────────────────────────────────────────────────
#  prices.update_price — 본품가(사이트키)
# ──────────────────────────────────────────────────────────

class TestPrices:
    def test_success_gmarket(self):
        from shared.platforms.esm.prices import update_price
        fake = FakeEsmClient(responses={_PRICE_PATH: {"resultCode": 0}})
        r = update_price(_G1, "gmarket", 119000, client=fake)
        assert r.success is True
        sent = fake.calls[0]
        assert sent["method"] == "PUT"
        assert sent["body"] == {"gmkt": 119000}

    def test_auction_uses_iac_key(self):
        from shared.platforms.esm.prices import update_price
        fake = FakeEsmClient(responses={_PRICE_PATH: {"resultCode": 0}})
        update_price(_G1, "auction", 50000, client=fake)
        assert fake.calls[0]["body"] == {"iac": 50000}

    def test_result_code_failure_surfaces(self):
        from shared.platforms.esm.prices import update_price
        fake = FakeEsmClient(responses={_PRICE_PATH: {"resultCode": 500, "message": "판매중 아님"}})
        r = update_price(_G1, "gmarket", 119000, client=fake)
        assert r.success is False
        assert "판매중" in (r.error_message or "")

    def test_non_ten_unit_raises(self):
        from shared.platforms.esm.prices import update_price
        with pytest.raises(ValueError):
            update_price(_G1, "gmarket", 11999, client=FakeEsmClient())

    def test_non_positive_raises(self):
        from shared.platforms.esm.prices import update_price
        with pytest.raises(ValueError):
            update_price(_G1, "gmarket", 0, client=FakeEsmClient())


# ──────────────────────────────────────────────────────────
#  inventory.update_stock — 옵션 full-replace(echo-back)
# ──────────────────────────────────────────────────────────

class TestInventory:
    def _options_resp(self):
        return {"details": [
            {"manageCode": "OPT-BLK-260", "recommendedOptValue": "블랙,260", "qty": {"gmkt": 7, "iac": 3}},
            {"manageCode": "OPT-WHT-270", "recommendedOptValue": "화이트,270", "qty": {"gmkt": 2, "iac": 1}},
        ]}

    def test_full_replace_sets_only_target_site_qty(self):
        from shared.platforms.esm.inventory import update_stock
        fake = FakeEsmClient(responses={
            ("GET", _OPT_PATH): self._options_resp(),
            ("PUT", _OPT_PATH): {"resultCode": 0},
        })
        assert update_stock(_G1, "gmarket", "OPT-BLK-260", 5, client=fake) is True
        put = [c for c in fake.calls if c["method"] == "PUT"][0]
        details = put["body"]["details"]
        # 대상 옵션 gmkt=5 로 변경, iac 및 다른 옵션은 보존(누락 금지)
        assert details[0]["qty"]["gmkt"] == 5
        assert details[0]["qty"]["iac"] == 3
        assert details[1]["qty"]["gmkt"] == 2

    def test_unknown_option_fails(self):
        from shared.platforms.esm.inventory import update_stock
        fake = FakeEsmClient(responses={("GET", _OPT_PATH): self._options_resp()})
        assert update_stock(_G1, "gmarket", "NOPE", 5, client=fake) is False

    def test_negative_raises(self):
        from shared.platforms.esm.inventory import update_stock
        with pytest.raises(ValueError):
            update_stock(_G1, "gmarket", "OPT-BLK-260", -1, client=FakeEsmClient())


# ──────────────────────────────────────────────────────────
#  어댑터
# ──────────────────────────────────────────────────────────

class TestEsmAdapter:
    def _ok_client(self):
        return FakeEsmClient(responses={
            _PRICE_PATH: {"resultCode": 0},
            ("GET", _OPT_PATH): {"details": [
                {"manageCode": "OPT-BLK-260", "qty": {"gmkt": 7, "iac": 3}}]},
            ("PUT", _OPT_PATH): {"resultCode": 0},
        })

    def test_price_then_stock_success(self):
        from lemouton.uploader.adapters.esm import EsmAdapter
        ad = EsmAdapter("gmarket", client=self._ok_client())
        r = ad.update_price_and_stock(canonical_sku="SKU-E", market_product_id=_G1,
                                      market_option_id="OPT-BLK-260", new_price=119000, new_stock=5)
        assert r.success is True
        assert r.market == "gmarket"

    def test_price_failure_stops_before_stock(self):
        from lemouton.uploader.adapters.esm import EsmAdapter
        fake = FakeEsmClient(responses={
            _PRICE_PATH: {"resultCode": 999, "message": "실패"},
            ("PUT", _OPT_PATH): {"resultCode": 0},
        })
        ad = EsmAdapter("gmarket", client=fake)
        r = ad.update_price_and_stock(canonical_sku="SKU-E", market_product_id=_G1,
                                      market_option_id="OPT-BLK-260", new_price=119000, new_stock=5)
        assert r.success is False
        assert all(c["path"] != _OPT_PATH for c in fake.calls)  # 재고까지 안 감

    def test_invalid_market_raises(self):
        from lemouton.uploader.adapters.esm import EsmAdapter
        with pytest.raises(ValueError):
            EsmAdapter("coupang")

    def test_mock_adapter_records(self):
        from lemouton.uploader.adapters.esm import MockEsmAdapter
        m = MockEsmAdapter("auction")
        m.update_price_and_stock(canonical_sku="SKU-E", market_product_id=_G1,
                                 market_option_id="OPT-1", new_price=1000, new_stock=2)
        assert m.calls[0]["market_option_id"] == "OPT-1"
        assert m.market_name == "auction"


# ──────────────────────────────────────────────────────────
#  market_fetch — 기존 상품 연동(옵션 조회)
# ──────────────────────────────────────────────────────────

class TestFetchEsm:
    def test_fetch_maps_options(self, monkeypatch):
        from lemouton.uploader import market_fetch as MF
        detail = {
            "itemBasicInfo": {"goodsName": {"kor": "상품"}},
            "itemAddtionalInfo": {"recommendedOpts": {"independent": {"details": [
                {"manageCode": "OPT-BLK-260", "recommendedOptValue": "블랙,260",
                 "qty": {"gmkt": 7, "iac": 3}},
            ]}}},
        }
        # 계정 키 없이 동작하도록 client 빌더·조회를 스텁
        monkeypatch.setattr(MF, "_esm_client", lambda market, env_prefix: object())
        monkeypatch.setattr(
            "shared.platforms.esm.products.resolve_goods_no",
            lambda site_goods_no, client=None: _G1)
        monkeypatch.setattr(
            "shared.platforms.esm.products.get_goods_detail",
            lambda goods_no, client=None: detail)
        r = MF.fetch_market_options("gmarket", "SITE123", env_prefix="GMARKET_MAIN")
        assert r.success is True
        assert r.product_name == "상품"
        assert len(r.options) == 1
        assert r.options[0].option_id == "OPT-BLK-260"
        assert r.options[0].color == "블랙"
        assert r.options[0].stock == 7


# ──────────────────────────────────────────────────────────
#  formatter — 자동전송 페이로드(미매핑 안전)
# ──────────────────────────────────────────────────────────

class TestBuildEsmPayload:
    def _dec(self, opt_id, displayed, price, market="gmarket"):
        return {"canonical_sku": "SKU-E", "color_display": "블랙", "size_display": "260",
                f"{market}_option_id": opt_id, market: {"displayed": displayed, "price": price}}

    def test_none_when_product_unmapped(self):
        from lemouton.formatter.esm import build_gmarket_payload
        model = {"model_name_display": "M", "gmarket_product_id": None}
        assert build_gmarket_payload([self._dec("OPT-1", True, 1000)], model, {}) is None

    def test_payload_when_mapped(self):
        from lemouton.formatter.esm import build_gmarket_payload
        model = {"model_name_display": "M", "gmarket_product_id": _G1}
        p = build_gmarket_payload([self._dec("OPT-BLK-260", True, 119000)], model, {"SKU-E": 5})
        assert p["market"] == "gmarket"
        assert p["product_id"] == _G1
        assert p["options"][0]["option_id"] == "OPT-BLK-260"
        assert p["options"][0]["price"] == 119000
        assert p["options"][0]["stock"] == 5

    def test_auction_independent_of_gmarket(self):
        from lemouton.formatter.esm import build_auction_payload
        model = {"model_name_display": "M", "auction_product_id": "A999", "gmarket_product_id": None}
        p = build_auction_payload([self._dec("OPT-1", True, 1000, market="auction")], model, {"SKU-E": 2})
        assert p["market"] == "auction"
        assert p["product_id"] == "A999"


# ──────────────────────────────────────────────────────────
#  오케스트레이터 라우팅 — dict 레지스트리 + 오배송 방지
# ──────────────────────────────────────────────────────────

@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _cout_esm(market):
    return {
        "smartstore": {}, "coupang": {}, "lotteon": {},
        market: {"M1": {"product_id": _G1,
                        "options": [{"option_id": "OPT-BLK-260", "price": 119000, "stock": 5}]}},
        "alerts": [],
    }


class TestOrchestratorRouting:
    def test_gmarket_row_goes_to_gmarket_adapter_not_coupang(self, db, tmp_path):
        from lemouton.uploader.orchestrator import run_uploader
        from lemouton.uploader.adapters.esm import MockEsmAdapter
        from lemouton.uploader.adapters.coupang import MockCoupangAdapter

        gm = MockEsmAdapter("gmarket")
        cp = MockCoupangAdapter()
        r = run_uploader(
            db, _cout_esm("gmarket"),
            sku_by_option={("gmarket", "OPT-BLK-260"): "SKU-E"},
            adapters={"gmarket": gm, "coupang": cp},
            dlq_path=str(tmp_path / "dlq.jsonl"),
        )
        assert r["uploaded"] == 1
        assert len(gm.calls) == 1
        assert gm.calls[0]["market_option_id"] == "OPT-BLK-260"
        assert cp.calls == []

    def test_missing_adapter_fails_not_misroute(self, db, tmp_path):
        from lemouton.uploader.orchestrator import run_uploader
        from lemouton.uploader.adapters.coupang import MockCoupangAdapter

        cp = MockCoupangAdapter()
        r = run_uploader(
            db, _cout_esm("auction"),
            sku_by_option={("auction", "OPT-BLK-260"): "SKU-E"},
            adapters={"coupang": cp},   # auction 없음
            dlq_path=str(tmp_path / "dlq.jsonl"),
        )
        assert r["uploaded"] == 0
        assert r["failed"] == 1
        assert cp.calls == []


class TestSelectAdapters:
    def test_dryrun_includes_esm(self):
        from lemouton.uploader.runtime import select_adapters
        ads = select_adapters(live=False)
        assert "auction" in ads and "gmarket" in ads
        assert ads["auction"].market_name == "auction"
