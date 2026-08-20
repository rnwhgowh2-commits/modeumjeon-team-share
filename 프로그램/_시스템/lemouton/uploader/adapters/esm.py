"""옥션·G마켓(ESM 2.0) 어댑터 — vendored shared/platforms/esm 호출.

옥션·G마켓은 같은 ESM Trading API(마스터 계정 공통, site_id 만 A/G). 한 클래스로 두 마켓을
market 인자로 구분한다(EsmAdapter("auction") / EsmAdapter("gmarket")).

계약: base.MarketAdapter.update_price_and_stock (옵션 1건 가격+재고).
매핑:
  · market_product_id → goodsNo (마스터 상품번호)
  · market_option_id  → 옵션 판매자코드(manageCode)
가격(본품 대표가) 먼저, 성공 시 재고(옵션 full-replace). 어느 단계든 실패면 즉시 실패 반환.

⚠️ 라이브 미검증(키없음) — MOUM_LIVE_UPLOAD OFF 에서는 DryRunAdapter 가 대신 쓰인다.
"""
from .base import MarketAdapter, UploadResult

_MARKETS = ("auction", "gmarket")


class EsmAdapter(MarketAdapter):
    """실제 호출 시 shared.platforms.esm 사용. 테스트는 MockEsmAdapter."""

    def __init__(self, market: str, client=None):
        if market not in _MARKETS:
            raise ValueError(f"ESM 마켓 아님: {market} (auction|gmarket)")
        self.market_name = market
        self._client = client

    def _ensure_client(self):
        if self._client is None:
            from shared.platforms import AUCTION, GMARKET
            from shared.platforms.esm.client import EsmClient
            cfg = AUCTION if self.market_name == "auction" else GMARKET
            self._client = EsmClient(cfg)
        return self._client

    def update_price_and_stock(self, *, canonical_sku, market_product_id,
                               market_option_id, new_price, new_stock) -> UploadResult:
        from shared.platforms.esm.prices import update_price
        from shared.platforms.esm.inventory import update_stock

        client = self._ensure_client()
        mkt = self.market_name

        # 1) 가격(본품 대표가) 변경
        try:
            price_result = update_price(
                str(market_product_id), mkt, int(new_price), client=client,
            )
        except Exception as e:  # ValueError 등 사전 검증 실패 포함
            return UploadResult(market=mkt, canonical_sku=canonical_sku,
                                success=False, http_status=None, error=f"price: {e}")
        if not price_result.success:
            return UploadResult(market=mkt, canonical_sku=canonical_sku,
                                success=False, http_status=None,
                                error=price_result.error_message or "price update failed")

        # 2) 재고(옵션 full-replace echo-back) 변경
        try:
            stock_ok = update_stock(
                str(market_product_id), mkt, str(market_option_id),
                int(new_stock), client=client,
            )
        except Exception as e:
            return UploadResult(market=mkt, canonical_sku=canonical_sku,
                                success=False, http_status=None, error=f"stock: {e}")
        if not stock_ok:
            return UploadResult(market=mkt, canonical_sku=canonical_sku,
                                success=False, http_status=None, error="stock update failed")

        return UploadResult(market=mkt, canonical_sku=canonical_sku,
                            success=True, http_status=200)


class MockEsmAdapter(MarketAdapter):
    """테스트용 mock — 호출 기록을 self.calls 에 적재."""

    def __init__(self, market: str = "auction", fail_on: set | None = None):
        self.market_name = market
        self.calls: list[dict] = []
        self.fail_on = fail_on or set()  # canonical_sku 집합

    def update_price_and_stock(self, *, canonical_sku, market_product_id,
                               market_option_id, new_price, new_stock) -> UploadResult:
        self.calls.append({
            "canonical_sku": canonical_sku,
            "market_product_id": market_product_id,
            "market_option_id": market_option_id,
            "new_price": new_price,
            "new_stock": new_stock,
        })
        if canonical_sku in self.fail_on:
            return UploadResult(market=self.market_name, canonical_sku=canonical_sku,
                                success=False, http_status=500, error="Mock failure")
        return UploadResult(market=self.market_name, canonical_sku=canonical_sku,
                            success=True, http_status=200)
