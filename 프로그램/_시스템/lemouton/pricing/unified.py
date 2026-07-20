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
    base = purchase_price / denom          # 배송비 제외 판매가
    raw = base + shipping_fee
    final = round_to_unit(int(round(raw)), rounding_unit)
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
    }
    return PriceResult(final_price=final, guardrail_status=status, breakdown=breakdown)


# ════════════════════════════════════════════════════════════
#  정책 해석기 — PriceTemplate + (마켓, 공급) → 가격 산출 인자
# ════════════════════════════════════════════════════════════
#  [2026-06-02] 모달의 마켓별·공급별 정책(mode/rate/amount/지정가)을 실제 가격
#  계산에 연결하는 단일 진입점. 화면·업로드 전 경로가 이 해석기를 경유해야
#  "화면값 = 업로드값" 이 보장된다.

_PREFIX_MAP = {'ss': 'ss', 'smartstore': 'ss', 'coupang': 'coupang', 'cp': 'coupang'}
_DEFAULT_RATE = {'ss': 0.0945, 'coupang': 0.1242}


def resolve_market_policy(tpl, market: str, side: str) -> dict:
    """PriceTemplate(tpl) 에서 (market, side) 정책을 추출.

    Args:
        tpl: PriceTemplate ORM (또는 동일 속성 보유 객체). None 허용(기본값 반환).
        market: 'ss'|'smartstore'|'coupang'|'cp'.
        side: 'sourcing'(소싱처) | 'purchase'(사입).

    Returns:
        {mode, rate, amount, fixed_price, fee_rate, shipping_fee} (전부 원시값).
    """
    prefix = _PREFIX_MAP.get((market or '').lower(), 'ss')
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
        fee_rate = 0.06 if prefix == 'ss' else 0.1155
    shipping_fee = g(f'{prefix}_delivery_fee', 0) or 0

    return {
        'mode': str(mode).lower(),
        'rate': float(rate),
        'amount': int(amount),
        'fixed_price': int(fixed),
        'fee_rate': float(fee_rate),
        'shipping_fee': int(shipping_fee),
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
    )
