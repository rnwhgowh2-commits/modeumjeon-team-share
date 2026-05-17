"""쿠팡 어댑터 — vendored shared/platforms/coupang 호출.

[E] Task 2 wiring:
- 테스트는 fake/mock client 를 주입 (`CoupangAdapter(client=fake)`).
- 운영 호출은 client=None 으로 인스턴스화 → lazy-import 로 실 CoupangClient 생성.
- update_price_and_stock 은 vendored update_price + update_quantity 를 순차 호출.
"""
from .base import MarketAdapter, UploadResult


class CoupangAdapter(MarketAdapter):
    """실제 호출 시 shared.platforms.coupang 사용. 테스트는 fake client 주입."""
    market_name = "coupang"

    def __init__(self, client=None):
        # client 가 None 이면 첫 호출 시 lazy 로 실 클라이언트 생성.
        self._client = client

    def _ensure_client(self):
        if self._client is None:
            from shared.platforms.coupang.client import CoupangClient
            self._client = CoupangClient()
        return self._client

    def update_price_and_stock(self, *, canonical_sku, market_product_id,
                               market_option_id, new_price, new_stock) -> UploadResult:
        # vendored API: vendor_item_id (== market_option_id) 단위로 동작
        from shared.platforms.coupang.prices import update_price
        from shared.platforms.coupang.inventory import update_quantity

        client = self._ensure_client()
        try:
            vendor_item_id = int(market_option_id)
        except (TypeError, ValueError):
            return UploadResult(
                market="coupang", canonical_sku=canonical_sku,
                success=False, http_status=None,
                error=f"invalid market_option_id: {market_option_id!r}",
            )

        # 1) 가격 변경
        try:
            price_result = update_price(
                vendor_item_id=vendor_item_id,
                price=int(new_price),
                client=client,
            )
        except Exception as e:  # ValueError 등 사전 검증 실패 포함
            return UploadResult(
                market="coupang", canonical_sku=canonical_sku,
                success=False, http_status=None, error=f"price: {e}",
            )
        if not price_result.success:
            return UploadResult(
                market="coupang", canonical_sku=canonical_sku,
                success=False, http_status=None,
                error=price_result.error_message or "price update failed",
            )

        # 2) 재고 변경
        try:
            stock_ok = update_quantity(
                vendor_item_id=vendor_item_id,
                quantity=int(new_stock),
                client=client,
            )
        except Exception as e:
            return UploadResult(
                market="coupang", canonical_sku=canonical_sku,
                success=False, http_status=None, error=f"stock: {e}",
            )
        if not stock_ok:
            return UploadResult(
                market="coupang", canonical_sku=canonical_sku,
                success=False, http_status=None, error="stock update failed",
            )

        return UploadResult(
            market="coupang", canonical_sku=canonical_sku,
            success=True, http_status=200,
        )


class MockCoupangAdapter(MarketAdapter):
    """테스트용 mock — 호출 기록을 self.calls에 적재."""
    market_name = "coupang"

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
                market="coupang", canonical_sku=canonical_sku,
                success=False, http_status=500, error="Mock failure",
            )
        return UploadResult(
            market="coupang", canonical_sku=canonical_sku,
            success=True, http_status=200,
        )
