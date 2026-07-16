"""11번가 어댑터 — vendored shared/platforms/eleven11 호출.

계약: base.MarketAdapter.update_price_and_stock (옵션 1건 가격+재고).
매핑:
  · market_product_id → 11번가 상품번호(prdNo)
  · market_option_id  → 11번가 단품/옵션 식별자
개통(배치 경로): update_price_and_stock 이 ①재고조회로 현재 옵션 전체를 읽고 ②대상 옵션
재고만 바꿔 full-replace 로 전송 ③상품 단위 가격 전송. 대상 옵션 미발견·조회 실패 시 전송
중단(옵션 소실 방지). ⚠️라이브 미검증 — colValue0 옵션 매칭키는 1옵션 테스트 상품으로 확정.

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
        """옵션 1건 가격+재고 변경(배치 경로).

        11번가는 재고가 **옵션 full-replace**(updateProductOption)라 대상 옵션만 보내면
        나머지가 소실될 수 있다. 그래서 ①현재 옵션 전체를 재고조회(stocks_query)로 읽고
        ②대상 옵션 재고만 바꾼 echo-back 페이로드를 만들어 ③전체를 한 번에 보낸다.
        가격은 상품(prdNo) 단위로 별도 전송한다.

        안전장치(옵션 소실·부분전송 방지):
          · 현재 옵션 조회 실패/빈 응답 → 전송 안 함(실패 반환).
          · 대상 옵션(market_option_id=mixOptNo)이 현재 옵션에 없으면 → 전송 안 함.
          · 재고 full-replace 성공 후에만 가격 전송. 둘 중 하나라도 실패면 실패로 표면화.
        """
        from shared.platforms.eleven11.stocks_query import get_stocks
        from shared.platforms.eleven11.inventory import (
            build_full_replace_from_current, update_option_stocks)
        from shared.platforms.eleven11.prices import update_price
        client = self._ensure_client()
        prd = str(market_product_id)
        target = str(market_option_id)

        # ① 현재 옵션 전체 조회(full-replace echo-back 재료)
        try:
            current = get_stocks(prd, client=client)
        except Exception as e:  # noqa: BLE001
            return UploadResult(market="eleven11", canonical_sku=canonical_sku,
                                success=False, error=f"재고조회 실패: {type(e).__name__}: {e}")
        if not current:
            return UploadResult(market="eleven11", canonical_sku=canonical_sku,
                                success=False, error="현재 옵션 0건 — 옵션 소실 방지 위해 전송 중단")
        # ② 대상 옵션 존재 확인(못 찾으면 전송 안 함 — full-replace 로 날릴 위험)
        if not any(str(o.get("opt_no")) == target for o in current):
            return UploadResult(
                market="eleven11", canonical_sku=canonical_sku, success=False,
                error=f"대상 옵션(mixOptNo={target}) 미발견 — 전송 중단(옵션 소실 방지)")
        # ③ 대상 재고만 교체한 full-replace 페이로드
        try:
            options = build_full_replace_from_current(current, changes={target: int(new_stock)})
        except Exception as e:  # noqa: BLE001
            return UploadResult(market="eleven11", canonical_sku=canonical_sku,
                                success=False, error=f"페이로드 조립 실패: {type(e).__name__}: {e}")
        # ④ 재고 full-replace 전송
        try:
            sr = update_option_stocks(prd, options, client=client)
        except Exception as e:  # noqa: BLE001
            return UploadResult(market="eleven11", canonical_sku=canonical_sku,
                                success=False, error=f"재고전송 실패: {type(e).__name__}: {e}")
        if not sr.success:
            return UploadResult(market="eleven11", canonical_sku=canonical_sku,
                                success=False, error=f"재고: {sr.error_message or sr.result_code}")
        # ⑤ 재고 성공 후 가격 전송(상품 단위)
        try:
            pr = update_price(prd, int(new_price), client=client)
        except Exception as e:  # noqa: BLE001
            return UploadResult(market="eleven11", canonical_sku=canonical_sku,
                                success=False,
                                error=f"재고는 반영됐으나 가격전송 실패: {type(e).__name__}: {e}")
        if not pr.success:
            return UploadResult(market="eleven11", canonical_sku=canonical_sku,
                                success=False,
                                error=f"재고는 반영됐으나 가격 실패: {pr.error_message or pr.result_code}")
        return UploadResult(market="eleven11", canonical_sku=canonical_sku,
                            success=True, http_status=200)


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
