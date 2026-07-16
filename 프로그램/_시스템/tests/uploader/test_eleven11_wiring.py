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

    def _current(self):
        # stocks_query.get_stocks 반환형(옵션 2개)
        return [
            {"opt_no": "1001", "opt_nm": "블랙", "dtl_opt_nm": "블랙/265", "stock": 5,
             "stat": None, "seller_stock_cd": "", "add_prc": 0},
            {"opt_no": "1002", "opt_nm": "블랙", "dtl_opt_nm": "블랙/270", "stock": 7,
             "stat": None, "seller_stock_cd": "", "add_prc": 0},
        ]

    def test_real_adapter_batch_send_success(self, monkeypatch):
        # 개통(배치): 현재 옵션 전체 조회 → 대상 재고만 교체한 full-replace + 상품가.
        import shared.platforms.eleven11.stocks_query as SQ
        import shared.platforms.eleven11.inventory as INV
        import shared.platforms.eleven11.prices as PR
        from shared.platforms.eleven11.inventory import StockChangeResult
        from shared.platforms.eleven11.prices import PriceChangeResult
        from lemouton.uploader.adapters.eleven11 import Eleven11Adapter

        monkeypatch.setattr(SQ, "get_stocks", lambda prd, client=None: self._current())
        sent = {}
        monkeypatch.setattr(INV, "update_option_stocks",
                            lambda prd, options, client=None: (
                                sent.update(prd=prd, options=options)
                                or StockChangeResult(product_id=prd, success=True,
                                                     result_code="200", error_message=None)))
        monkeypatch.setattr(PR, "update_price",
                            lambda prd, price, client=None: (
                                sent.update(price=price)
                                or PriceChangeResult(product_id=prd, success=True,
                                                     result_code="200", error_message=None)))

        ad = Eleven11Adapter(client=object())
        r = ad.update_price_and_stock(canonical_sku="SKU-E", market_product_id="P100",
                                      market_option_id="1002", new_price=19000, new_stock=6)
        assert r.success is True
        # full-replace 는 전체 옵션(2개)을 담고, 대상 1002 만 재고 6, 나머지 보존
        assert len(sent["options"]) == 2
        by = {o["opt_no"]: o for o in sent["options"]}
        assert by["1002"]["col_count"] == 6
        assert by["1001"]["col_count"] == 5
        assert sent["price"] == 19000

    def test_real_adapter_aborts_when_option_missing(self, monkeypatch):
        # 대상 옵션이 현재 옵션에 없으면 전송하지 않는다(full-replace 로 옵션 소실 방지).
        import shared.platforms.eleven11.stocks_query as SQ
        import shared.platforms.eleven11.inventory as INV
        from lemouton.uploader.adapters.eleven11 import Eleven11Adapter

        monkeypatch.setattr(SQ, "get_stocks", lambda prd, client=None: self._current())
        called = {"opts": 0}
        monkeypatch.setattr(INV, "update_option_stocks",
                            lambda *a, **k: called.__setitem__("opts", 1))
        ad = Eleven11Adapter(client=object())
        r = ad.update_price_and_stock(canonical_sku="SKU-E", market_product_id="P100",
                                      market_option_id="9999", new_price=19000, new_stock=6)
        assert r.success is False
        assert called["opts"] == 0
        assert "미발견" in (r.error or "")

    def test_real_adapter_aborts_on_empty_current(self, monkeypatch):
        # 현재 옵션 0건이면 전송 중단(빈 full-replace 로 전체 소실 방지).
        import shared.platforms.eleven11.stocks_query as SQ
        from lemouton.uploader.adapters.eleven11 import Eleven11Adapter
        monkeypatch.setattr(SQ, "get_stocks", lambda prd, client=None: [])
        ad = Eleven11Adapter(client=object())
        r = ad.update_price_and_stock(canonical_sku="SKU-E", market_product_id="P100",
                                      market_option_id="1001", new_price=19000, new_stock=6)
        assert r.success is False


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
