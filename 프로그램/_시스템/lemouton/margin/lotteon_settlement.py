# -*- coding: utf-8 -*-
"""롯데온 정산예정금액 순수 계산 — 실정산 엑셀 86행 오차0 검증된 공식.

정산예정금액 = 정산대상 − 중개수수료
  정산대상  = 상품가 − 롯데부담할인 − 셀러부담할인 + shipping_sale(총판매금액 배송비)
  중개수수료 = round(상품가×상품율) + round(shipping_fee_base(수수료적용배송비 고객부담)×배송율)
             + (round(상품가×제휴율) if is_affiliate else 0) − 롯데부담할인
제휴수수료는 판매경로 == '제휴'인 주문에만 부과(롯데ON 직접 유입은 0). 배송비수수료 base 는
정산대상에 더하는 배송비(총판매금액 배송비)와 다른 '수수료적용배송비(고객부담)'다.
율 기본값은 이 셀러 계약율(13%/3.3%/2%). 정산완료분 SettleCommission 실수수료로 대체 가능.
"""

def compute_settlement(product_price: int, shipping_sale: int, shipping_fee_base: int,
                       seller_discount: int, platform_discount: int, is_affiliate: bool,
                       rate_product: float = 0.13,
                       rate_shipping: float = 0.033,
                       rate_affiliate: float = 0.02) -> int:
    settle_target = product_price - platform_discount - seller_discount + shipping_sale
    commission = (round(product_price * rate_product)
                  + round(shipping_fee_base * rate_shipping)
                  + (round(product_price * rate_affiliate) if is_affiliate else 0)
                  - platform_discount)
    return int(round(settle_target - commission))
