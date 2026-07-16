"""11번가 어댑터 — vendored shared/platforms/eleven11 호출.

계약: base.MarketAdapter.update_price_and_stock (옵션 1건 가격+재고).
매핑:
  · market_product_id → 11번가 상품번호(prdNo)
  · market_option_id  → 11번가 단품/옵션 식별자
가격 먼저, 성공 시 재고 (쿠팡·롯데온 어댑터와 동일 순서). 어느 단계든 실패면 즉시 실패 반환.

★ 스펙 확보(콘솔 추출) 상태:
  · 가격 = **상품(prdNo) 단위** GET /rest/prodservices/product/price/{prdNo}/{selPrc}
    → per-option 계약이라도 prdNo 로 안전히 호출 가능(같은 상품이면 멱등). 배선 완료.
  · 재고 = **옵션 full-replace** POST /rest/prodservices/updateProductOption/{prdNo}
    → 옵션 **전체**를 한 번에 보내야 한다. per-option 계약(단건 옵션)으로는 다른 옵션을
      날릴 위험이 있어 안전히 배선 불가.

⚠️ 설계이슈(DONE_WITH_CONCERNS): update_price_and_stock 은 옵션 1건 단위라 재고 full-replace
   와 구조가 어긋난다. 안전을 위해 재고는 **단건 전송하지 않는다** — inventory.update_stock
   은 NotImplementedError 로 막혀 있고(임의 단건 전송으로 타 옵션 소실 방지), 이 어댑터는
   그 실패를 그대로 표면화한다. 재고 실전송은 상품 단위로 전체 옵션을 모으는 별도 경로
   (inventory.update_option_stocks + products 상세조회로 현재 옵션 확보)가 완성돼야 한다.
   → TODO: 상품 단위 배치 어댑터(가칭 update_product_options) 신설 후 재고 연결.

⚠️ 실전송은 MOUM_LIVE_UPLOAD OFF(기본)라 정상 흐름에선 호출되지 않는다. 라이브 미검증
   (SellerAPI 승인·서버IP 필요). 테스트·드라이런은 MockEleven11Adapter / DryRunAdapter.
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

        # 1) 가격 변경 — 상품(prdNo) 단위 GET. option_id 는 로깅용으로만 넘긴다.
        try:
            price_result = update_price(
                str(market_product_id),
                int(new_price),
                client=client,
            )
        except Exception as e:  # ValueError(사전검증) 등
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

        # 2) 재고 변경 — ⚠️ 11번가는 옵션 full-replace 라 단건 전송이 다른 옵션을 날린다.
        #    update_stock 은 안전상 막혀 있고(NotImplementedError), 그 실패를 그대로 표면화한다.
        #    per-option 계약으로는 재고를 안전히 못 보낸다(설계이슈 — 모듈 docstring 참고).
        #    TODO: 상품 단위로 전체 옵션을 모아 inventory.update_option_stocks 로 배선.
        try:
            stock_ok = update_stock(
                str(market_product_id),
                str(market_option_id),
                int(new_stock),
                client=client,
            )
        except Exception as e:  # NotImplementedError(full-replace 필요) 포함
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
