"""11번가 어댑터 — vendored shared/platforms/eleven11 호출.

계약: base.MarketAdapter.update_price_and_stock (옵션 1건 가격+재고).
매핑:
  · market_product_id → 11번가 상품번호(prdNo)
  · market_option_id  → 11번가 단품/옵션 식별자
현재 이 어댑터는 **전송 보류**(아무것도 안 보냄) — 부분 전송 방지. 아래 설계이슈 참고.

★ 스펙 확보(콘솔 추출) 상태:
  · 가격 = **상품(prdNo) 단위** GET /rest/prodservices/product/price/{prdNo}/{selPrc}
    → 프리미티브 prices.update_price 구현·테스트 완료(같은 상품이면 멱등).
  · 재고 = **옵션 full-replace** POST /rest/prodservices/updateProductOption/{prdNo}
    → 옵션 **전체**를 한 번에 보내야 한다. per-option 계약(단건 옵션)으로는 다른 옵션을
      날릴 위험이 있어 안전히 배선 불가. 프리미티브 inventory.update_option_stocks 는 구현 완료.

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
        # ⚠️ 부분 전송 방지 — 아무것도 보내지 않는다(가격 포함).
        #    11번가는 가격=상품단위(즉시 반영 가능)지만 재고=옵션 full-replace 라 옵션 단위
        #    계약으로는 안전히 못 보낸다. 가격만 먼저 보내고 재고를 실패시키면 '가격만 바뀐'
        #    부분 전송이 되어 위험하다. 따라서 재고 배치 경로(products 상세조회 +
        #    inventory.update_option_stocks)가 완성돼 가격·재고를 함께 보낼 수 있을 때까지
        #    이 어댑터는 전송을 보류한다(정직한 미준비 — 거짓 성공/부분 성공 금지).
        #    → TODO(Phase 3b): 상품 단위 배치 어댑터(update_product_options)로 가격+재고 동시 배선.
        #    프리미티브(prices.update_price / inventory.update_option_stocks)는 구현·테스트 완료라
        #    배치 경로만 얹으면 된다.
        return UploadResult(
            market="eleven11", canonical_sku=canonical_sku,
            success=False, http_status=None,
            error=("11번가 미개통 — 재고가 옵션 full-replace 라 옵션 단위 전송 미지원. "
                   "부분전송(가격만 반영) 방지 위해 전송 보류. "
                   "상품 단위 배치 경로 완성 후 개통(가격 프리미티브는 준비됨)."),
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
