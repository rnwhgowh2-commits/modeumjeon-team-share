"""롯데온 어댑터 — vendored shared/platforms/lotteon 호출.

계약: base.MarketAdapter.update_price_and_stock (옵션 1건 가격+재고).
매핑:
  · market_product_id → spdNo (판매자상품번호)
  · market_option_id  → sitmNo (판매자단품번호 = 옵션ID)
가격 먼저, 성공 시 재고 (쿠팡 어댑터와 동일 순서). 어느 단계든 실패면 즉시 실패 반환.
"""
from .base import MarketAdapter, UploadResult


class LotteonAdapter(MarketAdapter):
    """실제 호출 시 shared.platforms.lotteon 사용. 테스트는 MockLotteonAdapter."""
    market_name = "lotteon"

    def __init__(self, client=None):
        # client 가 None 이면 첫 호출 시 lazy 로 실 클라이언트 생성.
        self._client = client

    def _ensure_client(self):
        if self._client is None:
            from shared.platforms.lotteon.client import LotteonClient
            self._client = LotteonClient()
        return self._client

    def update_price_and_stock(self, *, canonical_sku, market_product_id,
                               market_option_id, new_price, new_stock) -> UploadResult:
        from shared.platforms.lotteon.prices import update_price
        from shared.platforms.lotteon.inventory import update_stock

        client = self._ensure_client()

        # 1) 가격 변경
        try:
            price_result = update_price(
                spd_no=str(market_product_id),
                sitm_no=str(market_option_id),
                price=int(new_price),
                client=client,
            )
        except Exception as e:  # ValueError 등 사전 검증 실패 포함
            return UploadResult(
                market="lotteon", canonical_sku=canonical_sku,
                success=False, http_status=None, error=f"price: {e}",
            )
        if not price_result.success:
            return UploadResult(
                market="lotteon", canonical_sku=canonical_sku,
                success=False, http_status=None,
                error=price_result.error_message or "price update failed",
            )

        # 2) 재고 변경
        try:
            stock_ok = update_stock(
                spd_no=str(market_product_id),
                sitm_no=str(market_option_id),
                stock=int(new_stock),
                client=client,
            )
        except Exception as e:
            return UploadResult(
                market="lotteon", canonical_sku=canonical_sku,
                success=False, http_status=None, error=f"stock: {e}",
            )
        if not stock_ok:
            return UploadResult(
                market="lotteon", canonical_sku=canonical_sku,
                success=False, http_status=None, error="stock update failed",
            )

        return UploadResult(
            market="lotteon", canonical_sku=canonical_sku,
            success=True, http_status=200,
        )


class MockLotteonAdapter(MarketAdapter):
    """테스트용 mock — 호출 기록을 self.calls에 적재."""
    market_name = "lotteon"

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
                market="lotteon", canonical_sku=canonical_sku,
                success=False, http_status=500, error="Mock failure",
            )
        return UploadResult(
            market="lotteon", canonical_sku=canonical_sku,
            success=True, http_status=200,
        )
