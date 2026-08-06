# -*- coding: utf-8 -*-
"""정책 「판매가 · 즉시할인」 → 마켓으로 나가는 모양 하나.

사장님 확정(2026-08-06) — 즉시할인은 **판매가 항목 안**에 둔다(별도 항목 없음).
값은 `rules['price']['discount_unit'|'discount_value']` 에 있다.

🔴 **보낼 수 있는 마켓에만 보낸다.** 지도 전수정독으로 확인된 것만:
    스마트스토어 = customerBenefit.immediateDiscountPolicy.discountMethod
                   {value, unitType: WON|PERCENT}  (전송 코드 이미 있음)
    쿠팡         = 즉시할인쿠폰을 만들어 옵션(vendorItemId)에 붙임
                   ⏰ **다음날 0시부터** 적용(오늘 못 켬)
  나머지 4마켓은 자리를 못 찾았다 → **안 보낸다**. 비슷해 보이는 칸에 끼워 넣으면
  엉뚱한 값이 마켓에 올라간다(날조 금지).

🔴 정상가(normal_price)와 헷갈리지 않게 — 정상가는 「원래 이 값이었다」고 **보여주는**
   숫자고, 즉시할인은 **실제로 깎이는** 값이다. 둘은 서로 대체하지 않는다.
"""
from __future__ import annotations

#: 즉시할인을 실제로 보낼 수 있는 마켓(실측 확인된 것만)
SUPPORTED = ('smartstore', 'coupang')

#: 정액(원) 할인의 최소 단위 — **마켓이 직접 알려준 규칙**.
#:   스스: 라이브 실측(2026-08-06) 12,345원을 보내니 거부하며
#:     「기본할인 항목은 10원 단위로 입력해 주세요」(invalid_inputs 원문).
#:   쿠팡: 문서에 정액 최소 100원·10원 단위(즉시할인쿠폰 생성 스펙).
#:   🔴 안 지키면 마켓이 「입력한 데이터가 유효하지 않습니다」만 뱉어 사장님은
#:     무엇이 잘못인지 알 수 없다 — 보내기 전에 여기서 걸러 말해 준다.
WON_STEP = {'smartstore': 10, 'coupang': 10}
COUPANG_MIN_WON = 100          # 쿠팡 정액 최소 금액(문서)

#: 화면·로그에 쓸 안내 — 나머지 마켓은 왜 안 나가는지 말한다(조용한 무시 금지)
UNSUPPORTED_NOTE = ('이 마켓은 즉시할인을 보낼 자리를 아직 못 찾았습니다 — '
                    '저장은 되지만 마켓으로 나가지 않습니다.')

_UNITS = ('WON', 'PERCENT')


def discount_of(rules) -> dict | None:
    """{'value': int, 'unitType': 'WON'|'PERCENT'} 또는 None(할인 없음).

    값이 없거나 0 이하면 None — 0 을 보내면 「0원 할인」이라는 뜻이 돼 버린다.
    모르는 방식이면 None + 그대로 두기(추측해서 %로 곱하지 않는다).
    """
    price = ((rules or {}).get('price') or {})
    raw = price.get('discount_value')
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    unit = str(price.get('discount_unit') or 'WON').upper()
    if unit not in _UNITS:
        return None
    if unit == 'PERCENT' and value >= 100:
        return None                     # 100% 이상 = 공짜. 실수로 본다(막는다).
    return {'value': value, 'unitType': unit}


def problem_for(market: str, discount) -> str | None:
    """이 마켓이 이 값을 받아 줄까 — 못 받으면 **사람 말로** 이유를 돌려준다.

    🔴 마켓에 보내 놓고 「입력한 데이터가 유효하지 않습니다」를 받으면 사장님은
      무엇이 잘못인지 알 수 없다. 보내기 전에 여기서 걸러 말한다.
    """
    if not discount:
        return None
    if market not in SUPPORTED:
        return UNSUPPORTED_NOTE
    if discount['unitType'] != 'WON':
        return None                     # 정률은 단위 규칙 없음(실측 근거 없음)
    v = int(discount['value'])
    step = WON_STEP.get(market)
    if step and v % step:
        return f'{market_label(market)}는 깎을 금액을 {step}원 단위로만 받습니다 ' \
               f'(예: {v // step * step:,}원)'
    if market == 'coupang' and v < COUPANG_MIN_WON:
        return f'쿠팡은 깎을 금액이 {COUPANG_MIN_WON}원 이상이어야 합니다'
    return None


def market_label(market: str) -> str:
    return {'smartstore': '스마트스토어', 'coupang': '쿠팡'}.get(market, market)


def exposed_price(sale_price, discount) -> int | None:
    """고객이 보게 될 값. 계산은 여기 한 곳에서만 한다(화면·전송이 갈리지 않게)."""
    if sale_price is None or not discount:
        return sale_price
    v, unit = discount['value'], discount['unitType']
    if unit == 'PERCENT':
        return int(round(int(sale_price) * (100 - v) / 100))
    return max(int(sale_price) - v, 0)
