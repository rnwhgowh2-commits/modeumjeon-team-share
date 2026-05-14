"""스마트스토어 어댑터 — vendored shared/platforms/smartstore 호출.

[E] live wiring:
- update_price_and_stock 옵션 1건 호출 → edit_product.edit_options 로 위임 (GET → PUT).
  옵션 단위 호출이지만 내부에선 product 전체 PUT (Naver Commerce 가 partial 거부).
  배치 처리는 batch_update_price_and_stock 사용 권장 (1 GET + 1 PUT 으로 N 옵션 처리).
"""
from .base import MarketAdapter, UploadResult


class SmartStoreAdapter(MarketAdapter):
    """실제 호출 시 shared.platforms.smartstore.edit_product 사용. 테스트는 MockSmartStoreAdapter."""
    market_name = "smartstore"

    def __init__(self, client=None):
        self._client = client

    def _ensure_client(self):
        if self._client is None:
            from shared.platforms.smartstore.client import SmartStoreClient
            self._client = SmartStoreClient()
        return self._client

    def update_price_and_stock(self, *, canonical_sku, market_product_id,
                               market_option_id, new_price, new_stock) -> UploadResult:
        from shared.platforms.smartstore.edit_product import edit_options
        client = self._ensure_client()
        try:
            r = edit_options(
                int(market_product_id),
                sale_price=int(new_price),
                option_updates={int(market_option_id): {
                    "stockQuantity": int(new_stock),
                    "price": 0,
                }},
                client=client,
            )
        except Exception as e:
            return UploadResult(market="smartstore", canonical_sku=canonical_sku,
                                success=False, error=f"{type(e).__name__}: {e}")
        if r.success:
            return UploadResult(market="smartstore", canonical_sku=canonical_sku,
                                success=True, http_status=200)
        return UploadResult(
            market="smartstore", canonical_sku=canonical_sku,
            success=False,
            error=f"{r.error_code}: {r.error_message}",
        )

    def batch_update(self, *, market_product_id: int, sale_price: int,
                     option_updates: dict,
                     immediate_discount: dict | None = None) -> UploadResult:
        """옵션 다수를 1 GET + 1 PUT 으로 일괄 변경 (rate limit 절약).

        immediate_discount 형식: {'value': int, 'unitType': 'WON'|'PERCENT'}
        """
        from shared.platforms.smartstore.edit_product import edit_options
        client = self._ensure_client()
        try:
            r = edit_options(
                int(market_product_id),
                sale_price=int(sale_price),
                option_updates={int(k): v for k, v in option_updates.items()},
                immediate_discount=immediate_discount,
                client=client,
            )
        except Exception as e:
            return UploadResult(market="smartstore", canonical_sku=str(market_product_id),
                                success=False, error=f"{type(e).__name__}: {e}")
        if r.success:
            return UploadResult(market="smartstore", canonical_sku=str(market_product_id),
                                success=True, http_status=200)
        return UploadResult(
            market="smartstore", canonical_sku=str(market_product_id),
            success=False,
            error=f"{r.error_code}: {r.error_message}",
        )


class MockSmartStoreAdapter(MarketAdapter):
    """테스트용 mock — 호출 기록을 self.calls에 적재."""
    market_name = "smartstore"

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
                market="smartstore", canonical_sku=canonical_sku,
                success=False, http_status=500, error="Mock failure",
            )
        return UploadResult(
            market="smartstore", canonical_sku=canonical_sku,
            success=True, http_status=200,
        )
