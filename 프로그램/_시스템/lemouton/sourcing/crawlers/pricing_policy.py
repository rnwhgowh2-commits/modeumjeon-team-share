"""사이트별 매입가 산정 공통 정책 헬퍼 — 2026-05-06 사용자 확정 정책.

각 크롤러가 ``apply_<site>_policy(sale_price, ...)`` 호출 → 매입가 + breakdown 반환.

★ 공통 원칙:
  · 누적식: 직전 단계 결과를 다음 단계 베이스로 (각 % 적립/할인은 누적 베이스 × 비율)
  · Fail-safe: sanity_check() 로 매입가 비율·차감 합 검증 → 실패 시 RuntimeError
  · 잘못된 가격 절대 DB 저장 금지

★ 사이트별 정책:
  · musinsa: musinsa_playwright._crawl() 자체 누적식 (LV별 % 매 크롤 추출, 별도 처리)
  · lemouton: 네이버페이 1% 적립 → 리뷰 5,000원 적립 → 현대카드 2.73% 캐시백 (누적)
  · ssf: 현대카드 2.73% 캐시백 (단일 단계)
  · lotteimall: 롯데카드 즉시할인 X% (페이지 추출) → 추가 카드할인 2% (누적)
  · ss_lemouton: 적용 안 함 (sale_price 그대로)
"""
from __future__ import annotations

from typing import Optional


# ════════════════════════════════════════════
#  공통 Sanity check
# ════════════════════════════════════════════
def sanity_check(site: str, sale_price: int, tier2_expected: int,
                 min_ratio: float = 0.50, max_ratio: float = 1.0,
                 max_deduction_ratio: float = 0.30) -> None:
    """매입가 비정상 여부 검사. 실패 시 RuntimeError.

    · 매입가가 sale_price 의 50%~100% 범위 벗어나면 비정상 (잘못된 추출 가능성)
    · 차감 합 (sale - tier2) 이 sale × 30% 초과면 의심 (과차감)
    """
    if sale_price <= 0:
        raise RuntimeError(f"[{site}] sale_price 0 또는 음수 ({sale_price}) — 추출 실패 (Fail-safe)")
    if tier2_expected < 0:
        raise RuntimeError(f"[{site}] 매입가 음수 ({tier2_expected}) — 산식 오류 (Fail-safe)")
    ratio = tier2_expected / sale_price
    if ratio < min_ratio:
        raise RuntimeError(
            f"[{site}] 매입가 비율 비정상 ({ratio*100:.1f}% < {min_ratio*100:.0f}%) — "
            f"tier2={tier2_expected:,}원 / sale={sale_price:,}원. 과차감 가능성 (Fail-safe)"
        )
    if ratio > max_ratio:
        raise RuntimeError(
            f"[{site}] 매입가가 sale_price 보다 큼 ({ratio*100:.1f}%) — 산식 오류 (Fail-safe)"
        )
    total_deduction = sale_price - tier2_expected
    if total_deduction > sale_price * max_deduction_ratio:
        raise RuntimeError(
            f"[{site}] 차감 합계 과다 ({total_deduction:,}원, "
            f"{total_deduction/sale_price*100:.1f}% > {max_deduction_ratio*100:.0f}% of sale) (Fail-safe)"
        )


# ════════════════════════════════════════════
#  르무통 공홈 (lemouton.co.kr)
# ════════════════════════════════════════════
LEMOUTON_NAVER_PAY_RATE = 0.01      # 네이버페이 결제 시 1% 적립
LEMOUTON_REVIEW_REWARD = 5000        # 리뷰 작성 시 5,000원 적립 (고정)
LEMOUTON_HYUNDAI_CARD_RATE = 0.0273  # 현대카드 결제 시 2.73% 캐시백


def apply_lemouton_policy(sale_price: int) -> dict:
    """르무통 공홈 매입가 산정 (누적식).

    sale_price → -1% (네이버페이) → -5,000 (리뷰) → -2.73% (현대카드)
    """
    base1 = max(sale_price, 0)
    naver_pay = int(base1 * LEMOUTON_NAVER_PAY_RATE)
    base2 = max(base1 - naver_pay, 0)
    review = LEMOUTON_REVIEW_REWARD if base2 > LEMOUTON_REVIEW_REWARD else 0
    base3 = max(base2 - review, 0)
    card_cb = int(base3 * LEMOUTON_HYUNDAI_CARD_RATE)
    tier2 = max(base3 - card_cb, 0)

    sanity_check("lemouton", sale_price, tier2)

    return {
        "tier2_expected": tier2,
        "breakdown": {
            "sale_price": sale_price,
            "naver_pay_reward_rate": LEMOUTON_NAVER_PAY_RATE,
            "naver_pay_reward_amount": naver_pay,
            "review_reward": review,
            "hyundai_card_rate": LEMOUTON_HYUNDAI_CARD_RATE,
            "hyundai_card_amount": card_cb,
            "base1_after_naver": base1 - naver_pay,
            "base2_after_review": base2 - review,
            "base3_after_card": tier2,
        },
        "discount_info": (
            f"네이버페이 -{naver_pay:,}원 (1%) / "
            f"리뷰 -{review:,}원 / "
            f"현대카드 -{card_cb:,}원 (2.73%)"
        ),
    }


# ════════════════════════════════════════════
#  SSF (ssfshop.com)
# ════════════════════════════════════════════
SSF_HYUNDAI_CARD_RATE = 0.0273  # 현대카드 결제 시 2.73% 캐시백


def apply_ssf_policy(sale_price: int) -> dict:
    """SSF 매입가 산정.

    sale_price → -2.73% (현대카드)
    """
    sale_price = max(sale_price, 0)
    card_cb = int(sale_price * SSF_HYUNDAI_CARD_RATE)
    tier2 = max(sale_price - card_cb, 0)

    sanity_check("ssf", sale_price, tier2)

    return {
        "tier2_expected": tier2,
        "breakdown": {
            "sale_price": sale_price,
            "hyundai_card_rate": SSF_HYUNDAI_CARD_RATE,
            "hyundai_card_amount": card_cb,
        },
        "discount_info": f"현대카드 -{card_cb:,}원 (2.73%)",
    }


# ════════════════════════════════════════════
#  lotteimall (롯데홈쇼핑)
# ════════════════════════════════════════════
# 사용자 확정 정책 (2026-05-06):
#   1) "최대할인가" 를 sale_price 로 사용 (max_price)
#   2) 롯데카드 청구할인 7% (고정) — 매번 페이지에서 받는 표준 혜택
#   3) 롯데카드 추가 카드할인 2% (고정) — 청구할인 별개의 추가 혜택
#   누적식: max_price → -7% → -2% → 매입가
LOTTEIMALL_LOTTE_CARD_INSTANT_RATE = 0.07  # 롯데카드 청구할인 7% (고정)
LOTTEIMALL_LOTTE_CARD_EXTRA_RATE   = 0.02  # 롯데카드 추가 카드할인 2% (고정)


def apply_lotteimall_policy(sale_price: int,
                             lotte_card_instant_rate: float | None = None) -> dict:
    """lotteimall 매입가 산정 (누적식).

    sale_price (최대할인가) → -7% (청구할인, 고정) → -2% (추가 카드할인, 고정)

    Args:
        sale_price: max_price = 사이트 "롯데홈쇼핑 최대할인가"
        lotte_card_instant_rate: None 이면 정책 기본값 7% 사용. 명시 시 그 값 사용.
    """
    sale_price = max(sale_price, 0)
    rate = LOTTEIMALL_LOTTE_CARD_INSTANT_RATE if lotte_card_instant_rate is None else lotte_card_instant_rate
    instant = int(sale_price * rate)
    base1 = max(sale_price - instant, 0)
    extra = int(base1 * LOTTEIMALL_LOTTE_CARD_EXTRA_RATE)
    tier2 = max(base1 - extra, 0)

    sanity_check("lotteimall", sale_price, tier2)

    return {
        "tier2_expected": tier2,
        "breakdown": {
            "sale_price": sale_price,
            "lotte_card_instant_rate": rate,
            "lotte_card_instant_amount": instant,
            "lotte_card_extra_rate": LOTTEIMALL_LOTTE_CARD_EXTRA_RATE,
            "lotte_card_extra_amount": extra,
            "base1_after_instant": base1,
        },
        "discount_info": (
            f"롯데카드 청구할인 -{instant:,}원 ({rate*100:.0f}%) / "
            f"롯데카드 추가 -{extra:,}원 (2%)"
        ),
    }
