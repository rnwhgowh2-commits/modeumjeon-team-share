# -*- coding: utf-8 -*-
"""[TEST] 11번가 판매처 연동 배선 — 어댑터·인증·시크릿·오케스트레이터 라우팅.

라이브 미검증(키 없음) + 셀러 REST 엔드포인트 스펙 미확보 상태에서, 지금 **구현된 배선**을
Mock/Fake 로 검증한다. (products/prices/inventory 실호출은 스펙 확보 후이므로 여기서 검증 안 함 —
대신 '스펙 미확보'가 어댑터/조회에서 안전하게 실패로 표면화되는지 검증.)
근거 스펙: docs/markets/eleven11.yaml.
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
#  auth 헤더 — openapikey (구현됨)
# ──────────────────────────────────────────────────────────

class TestAuthHeaders:
    def test_openapikey_header(self):
        from shared.platforms.eleven11.auth import build_headers
        h = build_headers("KEY123")
        assert h["openapikey"] == "KEY123"
        assert "xml" in h["Accept"]
        # Bearer/OAuth 아님 — Authorization 헤더 없어야 함
        assert "Authorization" not in h

    def test_empty_key_raises(self):
        from shared.platforms.eleven11.auth import build_headers
        with pytest.raises(ValueError):
            build_headers("")

    def test_dispatcher_client_header(self):
        from lemouton.auth.api_eleven11 import build_headers
        from lemouton.auth.secrets import Eleven11Credentials
        h = build_headers(Eleven11Credentials(openapi_key="ABC"))
        assert h["openapikey"] == "ABC"


# ──────────────────────────────────────────────────────────
#  secrets 스키마 (구현됨)
# ──────────────────────────────────────────────────────────

class TestSecrets:
    def test_eleven11_registered(self):
        from lemouton.auth import secrets as S
        assert "eleven11" in S.supported_markets()
        assert S.MARKET_SCHEMAS["eleven11"] is S.Eleven11Credentials

    def test_load_credentials_ok(self, monkeypatch):
        from lemouton.auth import secrets as S
        monkeypatch.setenv("ELEVEN11_TEST_OPENAPI_KEY", "abcdefgh12345678")
        creds = S.load_credentials(market="eleven11", env_prefix="ELEVEN11_TEST")
        assert isinstance(creds, S.Eleven11Credentials)
        assert creds.openapi_key == "abcdefgh12345678"
        # 마스킹 __repr__ — 평문 노출 0
        assert "abcdefgh12345678" not in repr(creds)

    def test_missing_key_raises(self, monkeypatch):
        from lemouton.auth import secrets as S
        monkeypatch.delenv("ELEVEN11_NOPE_OPENAPI_KEY", raising=False)
        with pytest.raises(S.SecretsMissingError):
            S.load_credentials(market="eleven11", env_prefix="ELEVEN11_NOPE")


# ──────────────────────────────────────────────────────────
#  어댑터 (구현됨) — Mock 기록 + 실어댑터의 '스펙 미확보' 안전 실패
# ──────────────────────────────────────────────────────────

class TestEleven11Adapter:
    def test_mock_adapter_records(self):
        from lemouton.uploader.adapters.eleven11 import MockEleven11Adapter
        m = MockEleven11Adapter()
        r = m.update_price_and_stock(canonical_sku="SKU-E", market_product_id="P100",
                                     market_option_id="P100_1", new_price=1000, new_stock=2)
        assert r.success is True
        assert r.market == "eleven11"
        assert m.calls[0]["market_option_id"] == "P100_1"

    def test_mock_adapter_fail_on(self):
        from lemouton.uploader.adapters.eleven11 import MockEleven11Adapter
        m = MockEleven11Adapter(fail_on={"SKU-E"})
        r = m.update_price_and_stock(canonical_sku="SKU-E", market_product_id="P100",
                                     market_option_id="P100_1", new_price=1000, new_stock=2)
        assert r.success is False

    def test_real_adapter_spec_missing_fails_safely(self):
        # 실 어댑터: 가격은 상품(prdNo) GET 로 배선됐으나 client=object() 라 request 없음 →
        #   AttributeError 를 'price:' 실패로 표면화(가격 실패 시 재고까지 가지 않음).
        #   추측 전송 없이 안전 실패. (재고는 옵션 full-replace 라 단건 update_stock 이 막혀 있음.)
        from lemouton.uploader.adapters.eleven11 import Eleven11Adapter
        ad = Eleven11Adapter(client=object())  # client 는 실호출 전에 예외라 무관
        r = ad.update_price_and_stock(canonical_sku="SKU-E", market_product_id="P100",
                                      market_option_id="P100_1", new_price=1000, new_stock=2)
        assert r.success is False
        assert "price" in (r.error or "")


# ──────────────────────────────────────────────────────────
#  market_fetch — 스펙 미확보 → '옵션 조회 실패'로 안전 표면화(크래시 아님)
# ──────────────────────────────────────────────────────────

class TestFetchEleven11:
    def test_spec_missing_surfaces_as_failure(self):
        from lemouton.uploader import market_fetch as MF
        r = MF.fetch_market_options("eleven11", "P100")
        assert r.success is False
        assert "실패" in (r.error or "")

    def test_empty_product_id(self):
        from lemouton.uploader import market_fetch as MF
        r = MF.fetch_market_options("eleven11", "")
        assert r.success is False


# ──────────────────────────────────────────────────────────
#  runtime.select_adapters — 드라이런/실전송 레지스트리에 eleven11 포함
# ──────────────────────────────────────────────────────────

class TestSelectAdapters:
    def test_dryrun_registry_has_eleven11(self):
        from lemouton.uploader.runtime import select_adapters
        ads = select_adapters(live=False)
        assert "eleven11" in ads
        assert ads["eleven11"].market_name == "eleven11"

    def test_live_registry_has_eleven11(self):
        from lemouton.uploader.runtime import select_adapters
        ads = select_adapters(live=True)
        assert "eleven11" in ads
        from lemouton.uploader.adapters.eleven11 import Eleven11Adapter
        assert isinstance(ads["eleven11"], Eleven11Adapter)


# ──────────────────────────────────────────────────────────
#  오케스트레이터 라우팅 — dict 레지스트리 + 함정(오배송) 방지
# ──────────────────────────────────────────────────────────

@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _cout_eleven11():
    return {
        "smartstore": {}, "coupang": {}, "lotteon": {},
        "eleven11": {"M1": {
            "product_id": "P100",
            "options": [{"option_id": "P100_1", "price": 19000, "stock": 5}],
        }},
        "alerts": [],
    }


class TestOrchestratorRouting:
    def test_eleven11_row_goes_to_eleven11_adapter_not_coupang(self, db, tmp_path):
        from lemouton.uploader.orchestrator import run_uploader
        from lemouton.uploader.adapters.eleven11 import MockEleven11Adapter
        from lemouton.uploader.adapters.coupang import MockCoupangAdapter

        ele = MockEleven11Adapter()
        cp = MockCoupangAdapter()
        r = run_uploader(
            db, _cout_eleven11(),
            sku_by_option={("eleven11", "P100_1"): "SKU-E"},
            adapters={"eleven11": ele, "coupang": cp,
                      "smartstore": MockCoupangAdapter()},
            dlq_path=str(tmp_path / "dlq.jsonl"),
        )
        assert r["uploaded"] == 1
        assert len(ele.calls) == 1
        assert ele.calls[0]["market_option_id"] == "P100_1"
        assert cp.calls == []   # 쿠팡으로 절대 안 감

    def test_missing_adapter_fails_not_misroute(self, db, tmp_path):
        from lemouton.uploader.orchestrator import run_uploader
        from lemouton.uploader.adapters.coupang import MockCoupangAdapter

        cp = MockCoupangAdapter()
        r = run_uploader(
            db, _cout_eleven11(),
            sku_by_option={("eleven11", "P100_1"): "SKU-E"},
            adapters={"coupang": cp},   # eleven11 없음
            dlq_path=str(tmp_path / "dlq.jsonl"),
        )
        assert r["uploaded"] == 0
        assert r["failed"] == 1
        assert cp.calls == []   # 쿠팡으로 오배송 안 함
