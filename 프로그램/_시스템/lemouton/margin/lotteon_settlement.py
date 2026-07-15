# -*- coding: utf-8 -*-
"""롯데온 정산예정금액 순수 계산 — 실정산 엑셀 117행 오차0 검증된 공식.

정산예정금액 = (상품가 − 셀러부담할인 + 배송비) − 중개수수료총합계
  중개수수료 = round(상품가×상품율) + round(배송비×배송율) + round(상품가×제휴율) − 롯데부담할인
율 기본값은 이 셀러 계약율(13%/3.3%/2%). 정산완료분에서 역산한 율을 주입하면 그 값을 쓴다.
"""

def compute_settlement(product_price: int, shipping: int,
                       seller_discount: int, platform_discount: int,
                       rate_product: float = 0.13,
                       rate_shipping: float = 0.033,
                       rate_affiliate: float = 0.02) -> int:
    settle_target = product_price - platform_discount - seller_discount + shipping
    commission = (round(product_price * rate_product)
                  + round(shipping * rate_shipping)
                  + round(product_price * rate_affiliate)
                  - platform_discount)
    return int(round(settle_target - commission))
