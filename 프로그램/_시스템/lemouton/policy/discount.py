# -*- coding: utf-8 -*-
"""정책 「판매가 · 즉시할인」 → 마켓으로 나가는 모양 하나.

사장님 확정(2026-08-06) — 즉시할인은 **판매가 항목 안**에 둔다(별도 항목 없음).
값은 `rules['price']['discount_unit'|'discount_value']` 에 있다.

🔴 **보낼 수 있는 마켓에만 보낸다.** 지도 전수정독으로 확인된 것만:
    스마트스토어 = customerBenefit.immediateDiscountPolicy.discountMethod
                   {value, unitType: WON|PERCENT}  (전송 코드 이미 있음)
    쿠팡         = 즉시할인쿠폰을 만들어 옵션(vendorItemId)에 붙임
                   ⏰ **다음날 0시부터** 적용(오늘 못 켬)
    옥션·G마켓   = 등록 payload 의 addtionalInfo.sellerDiscount
                   {isUse, iac|gmkt: {type, priceOrRate1, startDate, endDate}}
                   [2026-08-26 지도 전수정독으로 실측 — 별도 API 가 아니라 등록 안에 있다]
  나머지(11번가·롯데ON)는 자리를 못 찾았다 → **안 보낸다**. 비슷해 보이는 칸에
  끼워 넣으면 엉뚱한 값이 마켓에 올라간다(날조 금지).
    · 롯데ON 은 「판매자할인 저장」(apiNo=122)이 지도에 **[off]·상세 미접수**다 —
      URL 도 칸 이름도 없어 **확인 불가**. 없다고 단정하지도 않는다.

🔴 정상가(normal_price)와 헷갈리지 않게 — 정상가는 「원래 이 값이었다」고 **보여주는**
   숫자고, 즉시할인은 **실제로 깎이는** 값이다. 둘은 서로 대체하지 않는다.
"""
from __future__ import annotations

#: 즉시할인을 실제로 보낼 수 있는 마켓(실측 확인된 것만)
#:   [2026-08-26] 옥션·G마켓 추가 — 지도 전수정독에서 등록 payload 안의
#:   `addtionalInfo.sellerDiscount` 를 찾았다. 별도 API 를 새로 부르지 않는다.
SUPPORTED = ('smartstore', 'coupang', 'auction', 'gmarket')

#: ESM 할인타입 코드 — 지도 원문: 「0 : 사용안함 1 : 정액 2 : 정률」
ESM_TYPE = {'WON': 1, 'PERCENT': 2}
#: ESM 이 우리 쪽 마켓키를 부르는 이름 — 옥션=iac, G마켓=gmkt.
#:   🔴 반대로 넣으면 **다른 사이트에 할인이 걸린다**(지도: 「옥션 경우 아래 gmkt
#:     Entity대신 iac 입력」).
ESM_SITE_KEY = {'auction': 'iac', 'gmarket': 'gmkt'}
#: ESM 정률 상한 — 지도 원문: 「정률 설정시 : 판매가대비 70%까지 허용」
ESM_MAX_PCT = 70
#: ESM 정액 최소 — 지도 원문: 「정액 설정시 : 최소 100원 이상,10원 단위」
ESM_MIN_WON = 100

#: 정액(원) 할인의 최소 단위 — **마켓이 직접 알려준 규칙**.
#:   스스: 라이브 실측(2026-08-06) 12,345원을 보내니 거부하며
#:     「기본할인 항목은 10원 단위로 입력해 주세요」(invalid_inputs 원문).
#:   쿠팡: 문서에 정액 최소 100원·10원 단위(즉시할인쿠폰 생성 스펙).
#:   🔴 안 지키면 마켓이 「입력한 데이터가 유효하지 않습니다」만 뱉어 사장님은
#:     무엇이 잘못인지 알 수 없다 — 보내기 전에 여기서 걸러 말해 준다.
#:   옥션·G마켓: 지도 문서에 정액 최소 100원·10원 단위(등록 sellerDiscount 스펙).
WON_STEP = {'smartstore': 10, 'coupang': 10, 'auction': 10, 'gmarket': 10}
COUPANG_MIN_WON = 100          # 쿠팡 정액 최소 금액(문서)

#: [2026-08-13 사장님 확정] 쿠팡 쿠폰 기본값 — 「보통 쿠폰은 100원만 준다」.
#:   ★ 쿠팡에서 **즉시할인과 쿠폰적용은 다른 것**이다(목적은 같다). 정산 엑셀도
#:     `판매자 할인쿠폰(A.즉시할인)` / `(B.다운로드)` 로 따로 준다. 둘 다 판매자
#:     부담이라 정산 기준(할인가)에서 **둘 다 빠진다**.
COUPANG_DEFAULT_WON = 100

#: 🔴 100원이 **거부된 실측**이 있다 — 다른 세션 라이브 시험(2026-08-06 · `6d4164d9`):
#:     128,900원 상품에 100원(0.07%) → [CIE06] 「할인이 너무 작거나 너무 큽니다」
#:     같은 상품에 1,400원(1.09%)   → 통과 (사장님 실쿠폰)
#:   문서 하한은 100원인데 **판매가 대비 비율 하한이 따로 있는 것으로 보인다.**
#:   🔴 관측이 1건뿐이라 **규칙으로 못 박지 않는다** — 상한처럼 쓰면 멀쩡한 쿠폰까지 막는다.
#:   막지 않고 **미리 알리기만** 한다(`warn_for`). 말 안 하면 사장님은 [CIE06] 을
#:   받고도 무엇이 잘못인지 알 수 없다.
COUPANG_OBSERVED_OK_PCT = 1.0      # 통과가 확인된 최저 비율(1.09% → 보수적으로 1.0)

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


def default_discount(market: str) -> dict | None:
    """그 마켓의 기본 쿠폰 값. 쿠폰을 못 보내는 마켓엔 **만들지 않는다**(None).

    🔴 자리를 못 찾은 마켓에 기본값을 만들어 주면 「걸어 뒀는데 안 나가는 값」이 생긴다.
    """
    if market != 'coupang':
        return None
    return {'value': COUPANG_DEFAULT_WON, 'unitType': 'WON'}


def warn_for(market: str, discount, sale_price) -> str | None:
    """보내도 되지만 **마켓이 거부할 수 있는** 조합을 미리 말한다. 막지는 않는다.

    🔴 `problem_for` 와 자리가 다르다 — 저건 **막는** 곳, 여긴 **알리는** 곳.
      섞으면 관측 1건짜리 추정으로 멀쩡한 쿠폰까지 막게 된다.
    🔴 판매가를 모르면 아무 말도 안 한다 — 없는 근거로 겁주면 진짜 경고까지 무시하게 된다.
    """
    if not discount or market != 'coupang':
        return None
    if discount.get('unitType') != 'WON':
        return None
    try:
        price = int(sale_price)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    pct = int(discount['value']) / price * 100
    if pct >= COUPANG_OBSERVED_OK_PCT:
        return None
    return (f'쿠팡이 이 쿠폰을 거부할 수 있습니다 — {int(discount["value"]):,}원은 '
            f'판매가 {price:,}원의 {pct:.2f}% 입니다. '
            f'라이브 실측에서 0.07%는 거부([CIE06] 할인이 너무 작거나 너무 큽니다), '
            f'1.09%는 통과했습니다. 그래도 보내 볼 수 있습니다.')


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
        # 🔴 옥션·G마켓은 정률 상한이 **문서에 있다** — 넘기면 마켓이 거부한다.
        if market in ESM_SITE_KEY and int(discount['value']) > ESM_MAX_PCT:
            _mk = market_label(market)
            return (f'{_mk}{_은는(_mk)} 판매가 대비 {ESM_MAX_PCT}% 까지만 깎을 수 '
                    f'있습니다 (지금 {discount["value"]}%)')
        return None                     # 나머지는 단위 규칙 없음(실측 근거 없음)
    v = int(discount['value'])
    step = WON_STEP.get(market)
    if step and v % step:
        _mk = market_label(market)
        return (f'{_mk}{_은는(_mk)} 깎을 금액을 {step}원 단위로만 받습니다 '
                f'(예: {v // step * step:,}원)')
    if market == 'coupang' and v < COUPANG_MIN_WON:
        return f'쿠팡은 깎을 금액이 {COUPANG_MIN_WON}원 이상이어야 합니다'
    if market in ESM_SITE_KEY and v < ESM_MIN_WON:
        _mk = market_label(market)
        return f'{_mk}{_은는(_mk)} 깎을 금액이 {ESM_MIN_WON}원 이상이어야 합니다'
    return None


def _은는(말: str) -> str:
    """받침에 맞는 조사 — 「옥션는」처럼 읽히면 사장님이 바로 어색해한다."""
    if not 말:
        return '는'
    끝 = 말[-1]
    if '가' <= 끝 <= '힣':
        return '는' if (ord(끝) - 0xAC00) % 28 == 0 else '은'
    return '은'


def market_label(market: str) -> str:
    return {'smartstore': '스마트스토어', 'coupang': '쿠팡',
            'auction': '옥션', 'gmarket': 'G마켓',
            'eleven11': '11번가', 'lotteon': '롯데온'}.get(market, market)


def exposed_price(sale_price, discount) -> int | None:
    """고객이 보게 될 값. 계산은 여기 한 곳에서만 한다(화면·전송이 갈리지 않게)."""
    if sale_price is None or not discount:
        return sale_price
    v, unit = discount['value'], discount['unitType']
    if unit == 'PERCENT':
        return int(round(int(sale_price) * (100 - v) / 100))
    return max(int(sale_price) - v, 0)


def esm_seller_discount(market: str, discount, *, start=None, end=None) -> dict | None:
    """옥션·G마켓 등록 payload 의 `addtionalInfo.sellerDiscount` 조각. 없으면 None.

    지도 실측(2026-08-26 전수정독)::

        sellerDiscount: {
          isUse: bool,
          iac|gmkt: {type: 0사용안함|1정액|2정률, priceOrRate1: number,
                     startDate: 'YYYY-MM-DD', endDate: 'YYYY-MM-DD'}
        }

    🔴 옥션은 `iac`, G마켓은 `gmkt` — **반대로 넣으면 다른 사이트에 할인이 걸린다**
      (지도 원문: 「옥션 경우 아래 gmkt Entity대신 iac 입력」).
    🔴 기간(start/end)을 안 주면 **날짜 칸을 아예 안 넣는다.** 오늘 날짜를 지어
      넣으면 사장님이 정한 적 없는 기간이 마켓에 걸린다.
    🔴 마켓이 못 받을 값이면 None 을 돌려준다 — `problem_for` 가 이미 사람 말로
      사유를 말하므로, 여기서 조용히 깎거나 반올림하지 않는다.
    """
    key = ESM_SITE_KEY.get(market)
    if not key or not discount:
        return None
    if problem_for(market, discount):
        return None
    한쪽 = {'type': ESM_TYPE[discount['unitType']],
           'priceOrRate1': int(discount['value'])}
    if start:
        한쪽['startDate'] = str(start)
    if end:
        한쪽['endDate'] = str(end)
    return {'isUse': True, key: 한쪽}
