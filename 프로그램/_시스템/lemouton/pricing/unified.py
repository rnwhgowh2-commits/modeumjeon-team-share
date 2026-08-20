"""통합 가격 계산기 — 모음전 시스템 가격 계산의 단일 진실 원천.

ai-workflow cycle 20260521 · Phase 1 · Task 1

문제:
  가격 계산이 3곳으로 흩어져 같은 옵션에 다른 가격이 나옴.
    ① 스케줄러 엔진 (pricing/engine.py) — 분모형 마진식
    ② 매트릭스 화면 (sourcing/models_pricing.py:calc_auto_price) — 곱셈형
    ③ 재고관리 (pricing/boxhero_margin.py:compute_sale_price) — rate/amount

해결:
  이 모듈의 compute_sale_price_unified() 하나로 통일.
  ①②③ 모두 이 함수를 경유하게 하여 "화면값 = 마켓 업로드값" 보장.

계산식 (사용자 확정 — 마켓별·공급별 mode 3종):
    · mode='rate'   (마진율)   마진율 = **판매가 대비** (2026-07-20 변경)
                               판매가 × (1 - 수수료율) - 원가 = 판매가 × 마진율
                               → 판매가 = 원가 / (1 - 수수료율 - 마진율) + 배송비
                               (이전: 원가 × (1+마진율) × (1+수수료율) — 원가 대비 가산이라
                                「9.45%」로 넣어도 실제 판매가 대비 마진은 7.77% 였다)
    · mode='amount' (마진금액) 수수료 뒤 실수령 = 마진금액 → 역산
                               판매가 = 원가 / (1 - 수수료율) + 마진금액/(1 - 수수료율) + 배송비
                               즉 (원가 + 마진금액) / (1 - 수수료율) + 배송비
    · mode='fixed'  (지정가)   판매가 = 사용자가 지정한 할인가 그대로 (계산 없음)

  ※ 'amount' 는 'rate' 와 수수료 모델이 다르다(역산 vs 곱셈) — 사용자가 의미를
    "수수료 차감 후 손에 남는 금액 = 마진금액" 으로 확정(2026-06-02). 두 모드는 독립.

용어:
  · 원가(purchase_price): 혜택(적립·할인)이 모두 반영된 실매입가 (정수 원).
                          혜택 차감은 이 함수 호출 전에 끝나 있어야 함.
  · margin_rate / fee_rate: 소수 표기 (0.10 = 10%).
  · margin_amount: 마진금액 모드의 목표 실수령액 (원, mode='amount' 일 때만).
  · fixed_price: 지정가 모드의 최종 판매가 (원, mode='fixed' 일 때만).
  · 라운딩: round_to_unit (floor 기반 round-half-up) — 전 경로 통일.
            단 mode='fixed' 는 사용자 입력 할인가를 그대로 보존(라운딩 안 함).
  · 가드레일: (하한, 상한). 벗어나면 status 로만 표시하고 가격은 그대로 산출한다.
             "그 소싱처를 후보에서 제외" 같은 판단은 호출자 몫.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .rounding import round_to_unit


def is_crawl_valid(price, status) -> bool:
    """크롤 결과를 '실가격'으로 신뢰할 수 있는가 — 단일 진실 원천.

    조건: 가격 > 0  AND  last_status != 'error'.

    [2026-06-05] 실패(error)한 소싱처는 예전 성공 때의 옛 가격(stale)이 그대로
    남아 있어도 **절대 유효한 가격으로 취급하지 않는다**. 옛 가격을 성공으로
    둔갑시키면 거짓 100%·잘못된 원가·금전 손실로 직결되기 때문(데이터 무결성 원칙).
    화면 진행률 집계·최저가 winner·원가 선정·업로드 원가 — 전 경로 공용 게이트.
    """
    return bool(price and price > 0 and status != 'error')


def benefits_fresh(snapshot, last_status=None) -> bool:
    """혜택 크롤 스냅샷(dynamic_benefits_json['_crawl'])이 계산에 쓸 수 있는가 — 혜택용 게이트.

    조건: 스냅샷이 dict이고 benefits_ok=True (= 실제로 혜택영역을 긁은 성공 크롤).
    스냅샷 없음/benefits_ok=False → '미수집'(폴백·템플릿 금지). 옛 시스템이 템플릿/타-소싱처
    값을 현재처럼 쓰던 사고(문제2·3)를 막는 핵심 게이트.

    last_status 는 신선도에 반영하지 않는다(N1, 사용자 2026-06-14): crawl-result 는 성공
    크롤에서만 _crawl 을 덮어쓰므로 스냅샷은 '마지막 성공 크롤'이다. 이후 재크롤이 error 여도
    마지막 성공값을 유지(+화면에 크롤 시각 표시)한다. (표면가는 별도 is_crawl_valid 가 error 차단)
    """
    if not isinstance(snapshot, dict):
        return False
    return bool(snapshot.get('benefits_ok'))


@dataclass
class PriceResult:
    """통합 가격 계산 결과."""
    final_price: int                      # 최종 판매가 (정수 원)
    guardrail_status: str = 'none'         # 'ok' | 'below' | 'above' | 'none'
    breakdown: dict = field(default_factory=dict)   # 산출과정 표시용


def _apply_guardrail(final: int, guardrail: tuple[int, int] | None) -> str:
    if guardrail is None:
        return 'none'
    lower, upper = guardrail
    if final < lower:
        return 'below'
    if final >= upper:
        return 'above'
    return 'ok'


def _grossup(raw: float, unit: str, value) -> tuple[float, bool]:
    """**판매자가 부담하는** 할인만큼 판매가를 올려 잡는다. `(올려잡은 값, 불가능한가)`.

    사장님 확정(2026-08-13) — 마진 기준가 = 판매가 − 판매자 부담 할인액.
    고객이 내는 돈이 `raw` 가 되도록 표시 판매가를 키운다:
      · 정률 d% → raw / (1 − d)
      · 정액 N원 → raw + N

    🔴 **마켓이 같이 부담하는 할인은 여기 넣지 않는다.** 그 몫은 우리 수입이라
      판매가를 올릴 이유가 없다 — 올리면 고객에게 괜히 비싸 보인다.
    🔴 **버림은 여기서 하지 않는다.** 부르는 쪽이 맨 마지막에 한 번만 버린다 —
      두 번 버리면 100원을 더 손해 본다.
    """
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return raw, False
    if v <= 0:
        return raw, False
    if str(unit or 'WON').upper() == 'PERCENT':
        if v >= 100:
            return 0.0, True          # 100% 할인 = 공짜. 지어내지 말고 못 낸다고 한다
        return raw / (1.0 - v / 100.0), False
    return raw + v, False


def _net_basis(final: int, unit: str, value) -> int:
    """**우리 수입 기준가** = 판매가 − 판매자 부담 할인액. 마진은 이 값으로 잰다.

    🔴 이것은 「고객이 내는 값」이 **아니다.** 마켓이 할인을 같이 부담하면
      고객은 전체 할인만큼 싸게 사고, 마켓이 낸 몫은 우리에게 들어온다 —
      그래서 우리 수입 기준은 고객가보다 크다. 판매자 100% 부담일 때만
      두 숫자가 우연히 같아진다(그래서 못 알아채기 쉽다).

      고객이 내는 값이 필요하면 `policy/discount.exposed_price` 를 쓴다.
      그쪽이 **전체 할인**을 안다.
    """
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return int(final)
    if v <= 0:
        return int(final)
    if str(unit or 'WON').upper() == 'PERCENT':
        return int(round(final * (1.0 - v / 100.0)))
    return int(max(0, final - v))


def compute_sale_price_unified(
    purchase_price: int | None,
    margin_rate: float,
    fee_rate: float,
    shipping_fee: int = 0,
    rounding_unit: int = 100,
    guardrail: tuple[int, int] | None = None,
    *,
    mode: str = 'rate',
    margin_amount: int = 0,
    fixed_price: int = 0,
    seller_discount_unit: str = 'WON',
    seller_discount_value: int = 0,
) -> PriceResult:
    """마켓별·공급별 정책(mode)에 따라 판매가 산출 — 단일 진실 원천.

    Args:
        purchase_price: 혜택 모두 반영된 실매입가 (원). 0 이하/None 이면 판매가 0
                        (단 mode='fixed' 는 원가와 무관하게 지정가 그대로).
        margin_rate: 마진율 소수 (0.10 = 10%). mode='rate' 에서 사용.
        fee_rate: 마켓 수수료율 소수 (0.1155 = 11.55%). rate·amount 모두 사용.
        shipping_fee: 배송비 (원).
        rounding_unit: 끝자리 라운딩 단위 (기본 100원). mode='fixed' 는 미적용.
        guardrail: (하한, 상한). None 이면 검사 안 함.
        mode: 'rate'(마진율) | 'amount'(마진금액=수수료 뒤 실수령) | 'fixed'(지정가).
              알 수 없는 값 → 'rate' 로 처리. mode='fixed' 인데 fixed_price<=0 이면
              지정가 미설정으로 보고 'rate' 로 폴백(판매가 0 방지).
        margin_amount: mode='amount' 의 목표 실수령액 (원).
        fixed_price: mode='fixed' 의 최종 판매가 (원).

    Returns:
        PriceResult(final_price, guardrail_status, breakdown)
    """
    purchase_price = int(purchase_price or 0)
    mode = (mode or 'rate').lower()
    margin_amount = int(margin_amount or 0)
    fixed_price = int(fixed_price or 0)

    # mode='fixed' 폴백 — 지정가 미설정이면 rate 로
    if mode == 'fixed' and fixed_price <= 0:
        mode = 'rate'

    # ── mode='fixed' (지정가) — 사용자 지정 할인가 그대로, 라운딩 안 함 ──
    if mode == 'fixed':
        final = fixed_price
        status = _apply_guardrail(final, guardrail)
        return PriceResult(
            final_price=final, guardrail_status=status,
            breakdown={
                'mode': 'fixed', 'purchase_price': purchase_price,
                'fixed_price': fixed_price, 'fee_rate': fee_rate,
                'shipping_fee': shipping_fee, 'rounding_unit': rounding_unit,
                'raw_total': float(final), 'final_price': final,
                'guardrail': guardrail, 'guardrail_status': status,
                'seller_discount_unit': seller_discount_unit,
                'seller_discount_value': seller_discount_value,
                # 🔴 지정가는 **올려 잡지 않는다**(사람이 친 값 그대로) — 다만 할인이
                #   걸려 있으면 고객이 내는 돈은 그만큼 적다. 마진을 정직하게 재려면
                #   그 값을 알려 줘야 한다. 안 그러면 마진이 부풀어 가드가 헛돈다.
                'net_basis_price': _net_basis(final, seller_discount_unit,
                                          seller_discount_value),
            },
        )

    # rate·amount 는 원가 필요 — 0 이하면 판매가 0
    if purchase_price <= 0:
        return PriceResult(
            final_price=0, guardrail_status='none',
            breakdown={
                'mode': mode, 'purchase_price': 0, 'margin_rate': margin_rate,
                'margin_amount': margin_amount, 'fee_rate': fee_rate,
                'shipping_fee': shipping_fee, 'raw_total': 0.0,
                'rounding_unit': rounding_unit, 'final_price': 0,
                'guardrail': guardrail, 'guardrail_status': 'none',
            },
        )

    if mode == 'amount':
        # 수수료 뒤 실수령 = margin_amount → (원가 + 마진금액) / (1 - 수수료율) + 배송비
        denom = (1 - fee_rate) or 1e-9
        base = (purchase_price + margin_amount) / denom
        raw = base + shipping_fee
        final = round_to_unit(int(round(raw)), rounding_unit)
        breakdown = {
            'mode': 'amount', 'purchase_price': purchase_price,
            'margin_amount': margin_amount, 'fee_rate': fee_rate,
            'fee_amount': int(round(base * fee_rate)),
            'subtotal_before_ship': int(round(base)),
            'shipping_fee': shipping_fee, 'raw_total': raw,
            'rounding_unit': rounding_unit, 'final_price': final,
            'guardrail': guardrail, 'guardrail_status': 'none',
        }
        status = _apply_guardrail(final, guardrail)
        breakdown['guardrail_status'] = status
        # 🔴 모드마다 따로 채우면 하나를 빠뜨린다 — 나가기 직전에 보장한다.
        #   기준가(net_basis_price)가 없으면 마진을 표시 판매가로 재서 부풀어 보인다.
        breakdown.setdefault('seller_discount_unit', seller_discount_unit)
        breakdown.setdefault('seller_discount_value', seller_discount_value)
        breakdown.setdefault('net_basis_price',
                             _net_basis(final, seller_discount_unit, seller_discount_value))
        return PriceResult(final_price=final, guardrail_status=status, breakdown=breakdown)

    # ── mode='rate' — 마진율 = **판매가 대비** (2026-07-20 변경) ──
    #   이전: 판매가 = 원가 × (1+마진율) × (1+수수료율)  ← 원가 대비 가산(markup)이고
    #         수수료를 '더해서' 근사 보전만 했다. 그 결과 「9.45%」로 설정해도
    #         실제 판매가 대비 마진은 7.77% 로, 어느 기준으로도 설명되지 않는 값이었다.
    #   지금: 판매가에서 수수료를 뗀 실수령이 원가보다 '판매가 × 마진율' 만큼 많게 잡는다.
    #         판매가 × (1 - 수수료율) - 원가 = 판매가 × 마진율
    #         → 판매가 = 원가 / (1 - 수수료율 - 마진율)
    #   이러면 amount 모드((원가+마진금액)/(1-수수료율))와 같은 계통이 된다 —
    #   마진금액 = 판매가 × 마진율 을 넣으면 두 식이 정확히 일치한다.
    #   화면 표시(_matrix_v3.html 마진 %)도 같은 정의를 쓴다.
    denom = 1.0 - fee_rate - margin_rate
    if denom <= 0:
        # 수수료 + 마진율 ≥ 100% → 성립하는 판매가가 없다. 폴백 금지 — 0 으로 막는다.
        return PriceResult(
            final_price=0, guardrail_status='none',
            breakdown={
                'mode': 'rate', 'purchase_price': purchase_price,
                'margin_rate': margin_rate, 'margin_amount': 0,
                'fee_rate': fee_rate, 'shipping_fee': shipping_fee,
                'raw_total': 0.0, 'rounding_unit': rounding_unit, 'final_price': 0,
                'guardrail': guardrail, 'guardrail_status': 'none',
                'impossible': True,
                'impossible_reason': '수수료율 + 마진율이 100% 이상이라 판매가를 정할 수 없어요.',
            },
        )
    base = purchase_price / denom          # 배송비 제외 판매가 = **마진 기준가**
    raw = base + shipping_fee
    # 판매자 부담 할인이 있으면, 고객이 내는 돈이 `raw` 가 되도록 표시가를 올려 잡는다.
    grossed, impossible = _grossup(raw, seller_discount_unit, seller_discount_value)
    if impossible:
        return PriceResult(
            final_price=0, guardrail_status='none',
            breakdown={
                'mode': 'rate', 'purchase_price': purchase_price,
                'margin_rate': margin_rate, 'fee_rate': fee_rate,
                'shipping_fee': shipping_fee, 'raw_total': 0.0,
                'rounding_unit': rounding_unit, 'final_price': 0,
                'guardrail': guardrail, 'guardrail_status': 'none',
                'seller_discount_unit': seller_discount_unit,
                'seller_discount_value': seller_discount_value,
                'impossible': True,
                'impossible_reason': '할인이 100% 이상이라 판매가를 정할 수 없어요.',
            },
        )
    final = round_to_unit(int(round(grossed)), rounding_unit)   # 버림은 여기 한 번뿐
    status = _apply_guardrail(final, guardrail)
    breakdown = {
        'mode': 'rate',
        'purchase_price': purchase_price,
        'margin_rate': margin_rate,
        'margin_amount': int(round(base * margin_rate)),   # 판매가 대비
        'subtotal_before_ship': int(round(base)),
        'fee_rate': fee_rate,
        'fee_amount': int(round(base * fee_rate)),
        'shipping_fee': shipping_fee,
        'raw_total': raw,
        'rounding_unit': rounding_unit,
        'final_price': final,
        'guardrail': guardrail,
        'guardrail_status': status,
        # 화면이 다시 계산하지 않게 근거를 같이 준다 — 두 곳이 각자 세면 갈린다.
        'seller_discount_unit': seller_discount_unit,
        'seller_discount_value': seller_discount_value,
        'margin_basis': int(round(base)),        # 마진을 어느 값 기준으로 쟀나
        'net_basis_price': _net_basis(final, seller_discount_unit, seller_discount_value),
    }
    # 🔴 모드마다 따로 채우면 하나를 빠뜨린다 — 나가기 직전에 보장한다.
    #   기준가(net_basis_price)가 없으면 마진을 표시 판매가로 재서 부풀어 보인다.
    breakdown.setdefault('seller_discount_unit', seller_discount_unit)
    breakdown.setdefault('seller_discount_value', seller_discount_value)
    breakdown.setdefault('net_basis_price',
                         _net_basis(final, seller_discount_unit, seller_discount_value))
    return PriceResult(final_price=final, guardrail_status=status, breakdown=breakdown)


# ════════════════════════════════════════════════════════════
#  정책 해석기 — PriceTemplate + (마켓, 공급) → 가격 산출 인자
# ════════════════════════════════════════════════════════════
#  [2026-06-02] 모달의 마켓별·공급별 정책(mode/rate/amount/지정가)을 실제 가격
#  계산에 연결하는 단일 진입점. 화면·업로드 전 경로가 이 해석기를 경유해야
#  "화면값 = 업로드값" 이 보장된다.

class UnknownMarketPolicyError(ValueError):
    """가격 정책(수수료·마진)이 없는 마켓으로 계산을 시도했다. 조용한 폴백 금지."""


_PREFIX_MAP = {
    'ss': 'ss', 'smartstore': 'ss',
    'coupang': 'coupang', 'cp': 'coupang',
    # [2026-07-20] 4개 마켓 추가 — 컬럼 이름 규칙이 같아 아래 g(f'{prefix}_...') 가 그대로 읽는다.
    'lotteon': 'lotteon', 'lotte': 'lotteon',
    'eleven11': 'eleven11', '11st': 'eleven11', 'eleven': 'eleven11',
    'auction': 'auction',
    'gmarket': 'gmarket',
}
_DEFAULT_RATE = {'ss': 0.0945, 'coupang': 0.1242, 'lotteon': 0.1242,
                 'eleven11': 0.1242, 'auction': 0.1242, 'gmarket': 0.1242}
# 수수료 기본 — **표는 DB 에 있다** (`lemouton/pricing/fee_defaults.py`).
#   사장님 확정 2026-08-02: 「마켓 정책이 언제든 변경될 수 있으니 기본값도 수기로
#   조정 가능하게」 → 요율을 코드에 박아 두면 마켓이 바꿀 때마다 개발자를 불러야 한다.
#   여기 값은 표를 못 읽었을 때만 쓰는 **마지막 방어선**이다(계산이 멈추면 안 되므로).
#   🔴 요율을 고칠 자리는 화면(🔧 상품 정책화 > 정책 생성 > 마켓별 수수료 기준)이다.
#   ⚠️ 요율이 바뀌면 판매가가 움직인다: 판매가 = 매입가 / (1 − 수수료율 − 마진율).
_FALLBACK_FEE_BY_PREFIX = {'ss': 0.06, 'coupang': 0.1155, 'lotteon': 0.18,
                           'eleven11': 0.11, 'auction': 0.15, 'gmarket': 0.15}

#: 엔진 접두어 → 표의 마켓 키 (fee_defaults.SEED 와 짝)
_PREFIX_TO_MARKET = {'ss': 'smartstore', 'coupang': 'coupang', 'lotteon': 'lotteon',
                     'eleven11': 'eleven11', 'auction': 'auction', 'gmarket': 'gmarket'}
#: 모르는 마켓의 마지막 값 — 0 으로 두면 수수료 0% 로 계산돼 판매가가 실제보다
#: 싸게 나간다(금전 손실). 그래서 가장 흔한 값을 둔다.
_FALLBACK_FEE = 0.13


def default_fee_rate(market: str) -> float:
    """정책에 수수료율이 없을 때 그 마켓에 쓰는 값(소수).

    🔴 숫자를 베껴 쓰지 말 것 — 판매가를 정하는 모든 경로가 이 함수 하나를 부른다.
      예전에 `scheduler/jobs.py` 가 0.06/0.1155 를 손으로 적어 두고 있어서, 정책
      화면에서 아무리 고쳐도 그 파이프라인만 옛 요율로 계산했다(같은 상품에 두 가격).
    """
    prefix = _PREFIX_MAP.get((market or '').lower(), '')
    if not prefix:
        return _FALLBACK_FEE
    try:
        from lemouton.pricing.fee_defaults import base_pct
        pct = base_pct(_PREFIX_TO_MARKET.get(prefix, ''))
        if pct is not None:
            return float(pct) / 100.0
    except Exception:                                    # noqa: BLE001
        pass        # 표를 못 읽어도 계산은 이어간다 — 아래 방어선으로
    return _FALLBACK_FEE_BY_PREFIX.get(prefix, _FALLBACK_FEE)


def default_fee_pct(market: str) -> float:
    """화면에 넣을 퍼센트 표기 — 6.0 · 11.55 · 18.0 …

    🔴 화면이 이 함수를, 계산이 `default_fee_rate` 를 쓰므로 **둘이 절대 안 갈린다.**
      (화면에 숫자를 손으로 적어 두면 표를 고쳐도 화면이 안 따라온다.)
    """
    pct = round(default_fee_rate(market) * 100, 4)
    # 6.0 대신 6 으로 — 화면에 「6.0%」가 뜨면 소수 자리가 의미 있는 값처럼 보인다.
    #   (쿠팡 11.55 처럼 진짜 소수인 값은 그대로 남는다.)
    return int(pct) if float(pct).is_integer() else pct


def resolve_market_policy(tpl, market: str, side: str) -> dict:
    """PriceTemplate(tpl) 에서 (market, side) 정책을 추출.

    Args:
        tpl: PriceTemplate ORM (또는 동일 속성 보유 객체). None 허용(기본값 반환).
        market: 'ss'|'smartstore'|'coupang'|'cp'.
        side: 'sourcing'(소싱처) | 'purchase'(사입).

    Returns:
        {mode, rate, amount, fixed_price, fee_rate, shipping_fee} (전부 원시값).
    """
    # [2026-07-20] 모르는 마켓을 조용히 'ss' 로 떨어뜨리지 않는다.
    #   이전: _PREFIX_MAP.get(market, 'ss') — 'lotteon'/'eleven11'/'auction'/'gmarket' 이
    #   들어오면 스마트스토어 정책(수수료 6%·마진율 9.45%)으로 계산돼 **틀린 가격**이 나왔다.
    #   지금은 호출자가 실수로 넣어도 즉시 터뜨려 알린다(정합성 원칙: 모르면 멈춘다).
    #   reconcile.PRICED_MARKETS 가드가 1차로 막지만, 그 가드가 빠진 새 호출자를 대비한 방어선.
    _key = (market or '').lower()
    if _key not in _PREFIX_MAP:
        raise UnknownMarketPolicyError(
            f"'{market}' 는 가격 정책이 없는 마켓입니다 — 수수료·마진 설정을 먼저 넣어야 "
            f"자동 계산할 수 있어요. (지원: {', '.join(sorted(set(_PREFIX_MAP.values())))})")
    prefix = _PREFIX_MAP[_key]
    side = 'purchase' if side == 'purchase' else 'sourcing'

    def g(attr, default=None):
        return getattr(tpl, attr, default) if tpl is not None else default

    mode = (g(f'{prefix}_mode_{side}') or 'rate')
    rate = g(f'{prefix}_rate_{side}')
    if rate is None:
        rate = g(f'{prefix}_margin_rate')  # DEPRECATED 단일 모드 폴백
    if rate is None:
        rate = _DEFAULT_RATE[prefix]
    amount = g(f'{prefix}_amount_{side}', 0) or 0
    if side == 'sourcing':
        fixed = g(f'{prefix}_external_sale_price', 0) or 0
    else:
        fixed = g(f'{prefix}_boxhero_sale_price', 0) or 0
    fee_rate = g(f'{prefix}_fee_rate')
    if fee_rate is None:
        fee_rate = default_fee_rate(prefix)
    shipping_fee = g(f'{prefix}_delivery_fee', 0) or 0

    # ── 할인 · 누가 부담하나 (사장님 확정 2026-08-13) ──────────────────────────
    #   판매가를 올려 잡을 근거는 **판매자가 실제로 내는 몫**뿐이다.
    #   마켓이 내는 몫까지 얹으면 고객에게 괜히 비싸 보이고, 덜 얹으면 적자가 된다.
    #   🔴 부담 주체를 안 정했으면 **판매자**로 본다 — 모르면 보수적으로.
    #     「마켓」으로 잘못 두면 판매가를 안 올려 그대로 손해다.
    #   🔴 규칙 자체는 `policy/discount.seller_share` 한 곳에만 둔다 —
    #     여기서 다시 쓰면 미리보기 화면과 실제 업로드가가 갈린다.
    from lemouton.policy.discount import seller_share
    burden = str(g(f'{prefix}_discount_burden') or 'seller').lower()
    d_unit, seller_value = seller_share({
        'discount_unit': g(f'{prefix}_discount_unit'),
        'discount_value': g(f'{prefix}_discount_value'),
        'discount_burden': burden,
        'discount_burden_pct': g(f'{prefix}_discount_burden_pct'),
    })

    return {
        'mode': str(mode).lower(),
        'rate': float(rate),
        'amount': int(amount),
        'fixed_price': int(fixed),
        'fee_rate': float(fee_rate),
        'shipping_fee': int(shipping_fee),
        'seller_discount_unit': d_unit,
        'seller_discount_value': seller_value,
        'discount_burden': burden,
    }


def compute_market_price(
    tpl, market: str, side: str, purchase_price: int | None,
    *, guardrail: tuple[int, int] | None = None,
) -> PriceResult:
    """(tpl, market, side, 원가) → 정책 적용 최종 판매가.

    화면 표시·마켓 업로드 양쪽이 공통으로 호출하는 단일 진입점.
    """
    pol = resolve_market_policy(tpl, market, side)
    rounding_unit = (getattr(tpl, 'rounding_unit', 100) if tpl is not None else 100) or 100
    return compute_sale_price_unified(
        purchase_price,
        margin_rate=pol['rate'],
        fee_rate=pol['fee_rate'],
        shipping_fee=pol['shipping_fee'],
        rounding_unit=rounding_unit,
        guardrail=guardrail,
        mode=pol['mode'],
        margin_amount=pol['amount'],
        fixed_price=pol['fixed_price'],
        # 🔴 여기서 안 넘기면 엔진을 고쳐도 값이 영영 0 으로 간다.
        seller_discount_unit=pol['seller_discount_unit'],
        seller_discount_value=pol['seller_discount_value'],
    )
