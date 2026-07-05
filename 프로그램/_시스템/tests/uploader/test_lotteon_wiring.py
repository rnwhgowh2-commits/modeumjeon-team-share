# -*- coding: utf-8 -*-
"""[TEST] 롯데온 판매처 연동 배선 — 어댑터·플랫폼 래퍼·오케스트레이터 라우팅.

라이브 미검증(키 없음) 상태에서 코드 근거를 Mock/Fake 로 검증한다.
근거 스펙: docs/markets/lotteon.yaml (API 센터 공개 개발가이드 실측).
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
#  Fake 클라이언트 — HTTP 없이 request(method, path, body) 를 가로챈다
# ──────────────────────────────────────────────────────────

class FakeLotteonClient:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def request(self, method, path, body=None):
        self.calls.append({"method": method, "path": path, "body": body})
        resp = self.responses.get(path)
        if callable(resp):
            return resp(body)
        return resp if resp is not None else {"returnCode": "0000", "data": []}


_DETAIL = "/v1/openapi/product/v1/product/detail"
_PRICE = "/v1/openapi/product/v1/item/price/change"
_STOCK = "/v1/openapi/product/v1/item/stock/change"


# ──────────────────────────────────────────────────────────
#  auth 헤더
# ──────────────────────────────────────────────────────────

class TestAuthHeaders:
    def test_bearer_and_required_headers(self):
        from shared.platforms.lotteon.auth import build_headers
        h = build_headers("KEY123")
        assert h["Authorization"] == "Bearer KEY123"
        assert h["Accept"] == "application/json"
        assert h["Accept-Language"] == "ko"
        assert h["X-Timezone"] == "GMT+09:00"
        assert h["Content-Type"] == "application/json"

    def test_empty_key_raises(self):
        from shared.platforms.lotteon.auth import build_headers
        with pytest.raises(ValueError):
            build_headers("")


# ──────────────────────────────────────────────────────────
#  products.extract_items — 옵션(단품) 파싱
# ──────────────────────────────────────────────────────────

class TestExtractItems:
    def _detail(self):
        return {
            "spdNm": "테스트상품",
            "itmLst": [
                {
                    "sitmNo": "LO100_1", "sitmNm": "블랙 260", "slStatCd": "SALE",
                    "slPrc": 119000, "stkQty": 5, "stkMgtYn": "Y",
                    "itmOptLst": [
                        {"optNm": "색상", "optVal": "블랙"},
                        {"optNm": "사이즈", "optVal": "260"},
                    ],
                },
                {
                    "sitmNo": "LO100_2", "sitmNm": "화이트 270", "slStatCd": "SOUT",
                    "slPrc": 119000, "stkQty": 999_999_999, "stkMgtYn": "N",
                    "itmOptLst": [
                        {"optNm": "색상", "optVal": "화이트"},
                        {"optNm": "사이즈", "optVal": "270"},
                    ],
                },
            ],
        }

    def test_parses_option_id_color_size(self):
        from shared.platforms.lotteon.products import extract_items
        items = extract_items(self._detail())
        assert len(items) == 2
        a = items[0]
        assert a["sitm_no"] == "LO100_1"
        assert a["color"] == "블랙"
        assert a["size"] == "260"
        assert a["stock"] == 5
        assert a["sale_price"] == 119000
        assert a["status"] == "SALE"

    def test_unmanaged_stock_becomes_none(self):
        # stkMgtYn=N (재고 미관리) → 센티넬 999,999,999 을 그대로 노출하지 않고 None.
        from shared.platforms.lotteon.products import extract_items
        items = extract_items(self._detail())
        assert items[1]["stock"] is None
        assert items[1]["stock_managed"] is False

    def test_missing_sitm_no_skipped(self):
        from shared.platforms.lotteon.products import extract_items
        items = extract_items({"itmLst": [{"sitmNm": "no id"}]})
        assert items == []


# ──────────────────────────────────────────────────────────
#  prices / inventory — 배치 결과 파싱
# ──────────────────────────────────────────────────────────

class TestPrices:
    def test_success(self):
        from shared.platforms.lotteon.prices import update_price
        fake = FakeLotteonClient({_PRICE: {
            "returnCode": "0000",
            "data": [{"spdNo": "LO100", "sitmNo": "LO100_1", "resultCode": "0000"}],
        }})
        r = update_price("LO100", "LO100_1", 119000, client=fake)
        assert r.success is True
        # 전송 body 검증 — itmPrcLst 구조·필수필드
        sent = fake.calls[0]["body"]["itmPrcLst"][0]
        assert sent["trGrpCd"] == "SR"
        assert sent["spdNo"] == "LO100"
        assert sent["sitmNo"] == "LO100_1"
        assert sent["slPrc"] == 119000
        assert sent["itmDcTypCd"] == "GNRL"
        assert sent["hstStrtDttm"] and sent["hstEndDttm"]

    def test_item_result_code_failure_surfaces(self):
        from shared.platforms.lotteon.prices import update_price
        fake = FakeLotteonClient({_PRICE: {
            "returnCode": "0000",
            "data": [{"sitmNo": "LO100_1", "resultCode": "1001",
                      "resultMessage": "[slPrc]은 필수입력입니다."}],
        }})
        r = update_price("LO100", "LO100_1", 119000, client=fake)
        assert r.success is False
        assert "필수입력" in (r.error_message or "")

    def test_top_level_failure_all_fail(self):
        from shared.platforms.lotteon.prices import update_prices
        fake = FakeLotteonClient({_PRICE: {"returnCode": "9999", "message": "SYSTEM ERROR"}})
        rs = update_prices([{"spd_no": "LO100", "sitm_no": "LO100_1", "price": 1000}],
                           client=fake)
        assert rs[0].success is False

    def test_missing_item_in_response_is_failure(self):
        # 조용한 누락 금지 — 응답 data[] 에 없으면 실패로 표면화.
        from shared.platforms.lotteon.prices import update_prices
        fake = FakeLotteonClient({_PRICE: {"returnCode": "0000", "data": []}})
        rs = update_prices([{"spd_no": "LO100", "sitm_no": "LO100_1", "price": 1000}],
                           client=fake)
        assert rs[0].success is False

    def test_non_positive_price_raises(self):
        from shared.platforms.lotteon.prices import update_prices
        with pytest.raises(ValueError):
            update_prices([{"spd_no": "LO100", "sitm_no": "LO100_1", "price": 0}],
                          client=FakeLotteonClient())


class TestInventory:
    def test_success(self):
        from shared.platforms.lotteon.inventory import update_stock
        fake = FakeLotteonClient({_STOCK: {
            "returnCode": "0000",
            "data": [{"sitmNo": "LO100_1", "resultCode": "0000"}],
        }})
        assert update_stock("LO100", "LO100_1", 0, client=fake) is True
        sent = fake.calls[0]["body"]["itmStkLst"][0]
        assert sent["sitmNo"] == "LO100_1"
        assert sent["stkQty"] == 0

    def test_failure(self):
        from shared.platforms.lotteon.inventory import update_stock
        fake = FakeLotteonClient({_STOCK: {"returnCode": "9999"}})
        assert update_stock("LO100", "LO100_1", 3, client=fake) is False

    def test_negative_stock_raises(self):
        from shared.platforms.lotteon.inventory import update_stocks
        with pytest.raises(ValueError):
            update_stocks([{"spd_no": "LO100", "sitm_no": "LO100_1", "stock": -1}],
                          client=FakeLotteonClient())


# ──────────────────────────────────────────────────────────
#  어댑터
# ──────────────────────────────────────────────────────────

class TestLotteonAdapter:
    def _ok_client(self):
        return FakeLotteonClient({
            _PRICE: {"returnCode": "0000", "data": [{"sitmNo": "LO100_1", "resultCode": "0000"}]},
            _STOCK: {"returnCode": "0000", "data": [{"sitmNo": "LO100_1", "resultCode": "0000"}]},
        })

    def test_price_then_stock_success(self):
        from lemouton.uploader.adapters.lotteon import LotteonAdapter
        ad = LotteonAdapter(client=self._ok_client())
        r = ad.update_price_and_stock(canonical_sku="SKU-L", market_product_id="LO100",
                                      market_option_id="LO100_1", new_price=119000, new_stock=5)
        assert r.success is True
        assert r.market == "lotteon"

    def test_price_failure_stops(self):
        from lemouton.uploader.adapters.lotteon import LotteonAdapter
        fake = FakeLotteonClient({
            _PRICE: {"returnCode": "0000", "data": [{"sitmNo": "LO100_1", "resultCode": "1002"}]},
            _STOCK: {"returnCode": "0000", "data": [{"sitmNo": "LO100_1", "resultCode": "0000"}]},
        })
        ad = LotteonAdapter(client=fake)
        r = ad.update_price_and_stock(canonical_sku="SKU-L", market_product_id="LO100",
                                      market_option_id="LO100_1", new_price=119000, new_stock=5)
        assert r.success is False
        # 가격 실패 시 재고 호출까지 가지 않는다
        assert all(c["path"] != _STOCK for c in fake.calls)

    def test_mock_adapter_records(self):
        from lemouton.uploader.adapters.lotteon import MockLotteonAdapter
        m = MockLotteonAdapter()
        m.update_price_and_stock(canonical_sku="SKU-L", market_product_id="LO100",
                                 market_option_id="LO100_1", new_price=1000, new_stock=2)
        assert m.calls[0]["market_option_id"] == "LO100_1"


# ──────────────────────────────────────────────────────────
#  market_fetch — 기존 상품 연동(옵션 조회)
# ──────────────────────────────────────────────────────────

class TestFetchLotteon:
    def test_fetch_maps_options(self, monkeypatch):
        from lemouton.uploader import market_fetch as MF
        detail = {"spdNm": "상품", "itmLst": [
            {"sitmNo": "LO100_1", "slStatCd": "SALE", "slPrc": 119000, "stkQty": 5,
             "stkMgtYn": "Y",
             "itmOptLst": [{"optNm": "색상", "optVal": "블랙"}, {"optNm": "사이즈", "optVal": "260"}]},
        ]}
        monkeypatch.setattr(
            "shared.platforms.lotteon.products.get_product_detail",
            lambda spd_no, client=None: detail,
        )
        r = MF.fetch_market_options("lotteon", "LO100")
        assert r.success is True
        assert r.product_name == "상품"
        assert len(r.options) == 1
        assert r.options[0].option_id == "LO100_1"
        assert r.options[0].color == "블랙"
        assert r.options[0].size == "260"


# ──────────────────────────────────────────────────────────
#  오케스트레이터 라우팅 — dict 레지스트리 + 함정 방지
# ──────────────────────────────────────────────────────────

@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _cout_lotteon():
    return {
        "smartstore": {}, "coupang": {},
        "lotteon": {"M1": {
            "product_id": "LO100",
            "options": [{"option_id": "LO100_1", "price": 119000, "stock": 5}],
        }},
        "alerts": [],
    }


class TestOrchestratorRouting:
    def test_lotteon_row_goes_to_lotteon_adapter_not_coupang(self, db, tmp_path):
        # 함정 방지: lotteon 행이 쿠팡 어댑터로 새어나가면 금전 손실.
        from lemouton.uploader.orchestrator import run_uploader
        from lemouton.uploader.adapters.lotteon import MockLotteonAdapter
        from lemouton.uploader.adapters.coupang import MockCoupangAdapter

        lot = MockLotteonAdapter()
        cp = MockCoupangAdapter()
        r = run_uploader(
            db, _cout_lotteon(),
            sku_by_option={("lotteon", "LO100_1"): "SKU-L"},
            adapters={"lotteon": lot, "coupang": cp,
                      "smartstore": MockCoupangAdapter()},
            dlq_path=str(tmp_path / "dlq.jsonl"),
        )
        assert r["uploaded"] == 1
        assert len(lot.calls) == 1
        assert lot.calls[0]["market_option_id"] == "LO100_1"
        assert cp.calls == []   # 쿠팡으로 절대 안 감

    def test_missing_adapter_fails_not_misroute(self, db, tmp_path):
        # 어댑터 미등록 마켓 → 임의 어댑터로 보내지 않고 실패로 기록.
        from lemouton.uploader.orchestrator import run_uploader
        from lemouton.uploader.adapters.coupang import MockCoupangAdapter

        cp = MockCoupangAdapter()
        r = run_uploader(
            db, _cout_lotteon(),
            sku_by_option={("lotteon", "LO100_1"): "SKU-L"},
            adapters={"coupang": cp},   # lotteon 없음
            dlq_path=str(tmp_path / "dlq.jsonl"),
        )
        assert r["uploaded"] == 0
        assert r["failed"] == 1
        assert cp.calls == []   # 쿠팡으로 오배송 안 함
