"""11번가 어댑터 — vendored shared/platforms/eleven11 호출.

계약: base.MarketAdapter.update_price_and_stock (옵션 1건 가격+재고).
매핑:
  · market_product_id → 11번가 상품번호
  · market_option_id  → 11번가 단품/옵션 식별자
가격 먼저, 성공 시 재고 (쿠팡·롯데온 어댑터와 동일 순서). 어느 단계든 실패면 즉시 실패 반환.

⚠️ 실 전송 경로(prices/inventory)는 셀러 REST 스펙 미확보로 NotImplementedError 를 던진다.
   실전송은 LEMOUTON_LIVE_UPLOAD OFF(기본)라 정상 흐름에선 호출되지 않고, 만약 켜서
   호출되면 '스펙 미확보'가 실패로 명시 표면화된다(추측 전송으로 금전 손실 방지).
   테스트·드라이런은 MockEleven11Adapter / DryRunAdapter 를 사용.
"""
from .base import MarketAdapter, UploadResult


class Eleven11Adapter(MarketAdapter):
    """실제 호출 시 shared.platforms.eleven11 사용. 테스트는 MockEleven11Adapter."""
    market_name = "eleven11"

    def __init__(self, client=None):
        self._client = client

    def _ensure_client(self):
        if self._client is None:
            from shared.platforms.eleven11.client import Eleven11Client
            self._client = Eleven11Client()
        return self._client

    def update_price_and_stock(self, *, canonical_sku, market_product_id,
                               market_option_id, new_price, new_stock) -> UploadResult:
        from shared.platforms.eleven11.prices import update_price
        from shared.platforms.eleven11.inventory import update_stock

        client = self._ensure_client()

        # 1) 가격 변경
        try:
            price_result = update_price(
                product_id=str(market_product_id),
                option_id=str(market_option_id),
                price=int(new_price),
                client=client,
            )
        except Exception as e:  # NotImplementedError(스펙 미확보) / ValueError 등
            return UploadResult(
                market="eleven11", canonical_sku=canonical_sku,
                success=False, http_status=None, error=f"price: {e}",
            )
        if not price_result.success:
            return UploadResult(
                market="eleven11", canonical_sku=canonical_sku,
                success=False, http_status=None,
                error=price_result.error_message or "price update failed",
            )

        # 2) 재고 변경
        try:
            stock_ok = update_stock(
                product_id=str(market_product_id),
                option_id=str(market_option_id),
                stock=int(new_stock),
                client=client,
            )
        except Exception as e:
            return UploadResult(
                market="eleven11", canonical_sku=canonical_sku,
                success=False, http_status=None, error=f"stock: {e}",
            )
        if not stock_ok:
            return UploadResult(
                market="eleven11", canonical_sku=canonical_sku,
                success=False, http_status=None, error="stock update failed",
            )

        return UploadResult(
            market="eleven11", canonical_sku=canonical_sku,
            success=True, http_status=200,
        )


class MockEleven11Adapter(MarketAdapter):
    """테스트용 mock — 호출 기록을 self.calls에 적재."""
    market_name = "eleven11"

    def __init__(self, fail_on: set | None = None):
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
            return UploadResult(
                market="eleven11", canonical_sku=canonical_sku,
                success=False, http_status=500, error="Mock failure",
            )
        return UploadResult(
            market="eleven11", canonical_sku=canonical_sku,
            success=True, http_status=200,
        )
