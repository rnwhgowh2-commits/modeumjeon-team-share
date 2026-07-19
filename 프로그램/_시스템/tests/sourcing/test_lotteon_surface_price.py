# -*- coding: utf-8 -*-
"""롯데온(lotteon.com) 표면노출가 — **현재 코드 동작 스냅샷** (서버 pbf API 경로).

정본: ``docs/소싱처별-정답지-읽는법.md`` §롯데온 —
**확인 상태 ⚠️ 정의 3~4개 충돌. "현재 어떤 소스도 근거로 인용하면 안 된다."**

  표면가로 잡는 값 (서버 경로, `crawlers/lotteon.py:_parse_lotteon_prices`):
      1. ``qty.immdDcAplyTotAmt``  (즉시할인 적용가)
      2. 없으면 ``qty.orderDcAplyTotAmt`` (쿠폰까지 적용)
      3. 그것도 없으면 ``priceInfo.slPrc`` (정가)
  선반영된 것 (``dcTnnoCd`` 기준, `lotteon.py:717-727` 이 단일 진실 원천):
      1ST 스토어 즉시할인 · 2ND CM할인 · 3RD 무료배송 → **선반영**
      4TH 쿠폰 · 5TH 카드즉시할인                     → 미반영(별도 차감이 맞음)
  표면가 아님 : 「나의 혜택가」 — **롯데오너스까지 먹은 값**

🔴 **이 값이 옳은지는 미확정 — 코드 현재 동작을 고정한 것이다.**
정답지 §2 가 기록한 대로 표면가 정의가 4곳에서 충돌한다
(``background.js`` = 판매가 / ``lotteon.py`` = immdDcAplyTotAmt /
``크롤링-가이드.md`` = 나의 혜택가 / ``populate_lotteon_guide.py`` = 혜택가 아님).
특히 ``크롤링-가이드.md`` 는 확장이 "이중차감 위험" 이라 부른 바로 그 조합을
규정하고 있어 **정면 충돌**이다. 사장님이 라이브 대조로 확정하면 기대값을 바꾼다.

⚠️ **덮는 범위** — 본 테스트는 **서버 pbf API 경로**만 덮는다.
**라이브 경로인 크롬확장**(``background.js`` `pickSale()` 정규식
``/(\\d+)%\\s*([\\d,]{4,})\\s*원/``)은 JS 라 덮지 못한다 — 이 저장소에 JS 테스트
러너가 없다(``package.json`` 부재). 정답지 **D4**(판매가 실패 시 「나의 혜택가」로
폴백 → 오너스 이중차감)는 그 JS 경로 문제이므로 **여기서 검증되지 않는다.**

픽스처 출처: pbf API 응답을 **코드가 읽는 필드만 축약 재구성**했다
(라이브 응답 미수신). 실제와 다를 수 있다.
"""
from lemouton.sourcing.crawlers.lotteon import (
    _extract_lotteon_owners_member_discount,
    _parse_lotteon_prices,
    LOTTEON_AUTO_APPLIED_TIERS,
)

# 정답지에 기록된 실측 사례 (르무통, 2026-05-15 명세 검증)
ORIGIN_PRICE = 149000      # priceInfo.slPrc = 정가            ✗ 표면가 아님
IMMD_PRICE = 126060        # immdDcAplyTotAmt = 즉시할인 적용가  ★ 현재 표면가
ORDER_PRICE = 118000       # orderDcAplyTotAmt = 쿠폰까지 적용   ✗ 우선순위 2단
BENEFIT_PRICE = 124800     # 「나의 혜택가」(오너스 선반영)      ✗ 표면가 아님


def _base(slprc=ORIGIN_PRICE):
    return {"priceInfo": {"slPrc": slprc}}


def _qty(immd=IMMD_PRICE, order=ORDER_PRICE):
    return {"immdDcAplyTotAmt": immd, "orderDcAplyTotAmt": order}


# ─────────────────────────────────────────────────────────────
# ① 표면가로 무엇을 잡는가 — immdDcAplyTotAmt
# ─────────────────────────────────────────────────────────────
def test_surface_price_is_immd_dc_apply_tot_amt():
    sale, max_price, origin = _parse_lotteon_prices(_base(), _qty())
    assert sale == IMMD_PRICE
    assert max_price == IMMD_PRICE
    assert origin == ORIGIN_PRICE


def test_surface_price_identity_matches_spec_example():
    """정답지 실측 항등식: 149,000 − 8,940(1ST) − 14,000(2ND) = 126,060."""
    assert ORIGIN_PRICE - 8940 - 14000 == IMMD_PRICE


# ─────────────────────────────────────────────────────────────
# ② 정가·쿠폰가·혜택가를 표면가로 잡으면 실패해야 한다
# ─────────────────────────────────────────────────────────────
def test_origin_price_is_not_used_when_immd_exists():
    """정가(149,000)가 표면가로 새면 즉시할인 22,940 만큼 매입가가 부풀려진다."""
    sale, _, _ = _parse_lotteon_prices(_base(), _qty())
    assert sale != ORIGIN_PRICE


def test_coupon_applied_price_is_not_used_when_immd_exists():
    """``orderDcAplyTotAmt``(쿠폰까지 적용)를 우선 잡으면 쿠폰 이중차감이 된다.

    쿠폰(4TH)은 **미반영** 항목이라 엔진이 따로 뺀다.
    """
    sale, _, _ = _parse_lotteon_prices(_base(), _qty())
    assert sale != ORDER_PRICE


def test_my_benefit_price_field_is_ignored_by_server_parser():
    """★ 「나의 혜택가」는 **롯데오너스까지 먹은 값** → 표면가로 쓰면 오너스 이중차감.

    응답에 혜택가류 필드가 섞여 들어와도 서버 파서는 그 필드를 보지 않는다.
    """
    qty = _qty()
    qty.update({"benefitPrc": BENEFIT_PRICE, "myBenefitAmt": BENEFIT_PRICE,
                "ownersAplyTotAmt": BENEFIT_PRICE})
    sale, _, _ = _parse_lotteon_prices(_base(), qty)
    assert sale == IMMD_PRICE
    assert sale != BENEFIT_PRICE


def test_owners_discount_is_extracted_separately_not_baked_in():
    """오너스율은 **별도 키**로 추출된다 = 표면가에 선반영이 아니라는 전제.

    (이 전제가 깨지면 = 표면가가 혜택가로 바뀌면 오너스가 두 번 빠진다.)
    """
    rate, label = _extract_lotteon_owners_member_discount(
        {"additionFavorInfo": {"ownersFavor": {
            "ownersDcCnts": "추가 1% 할인", "ownersHighLight": ["1%"]}}})
    assert rate == 0.01
    assert label == "롯데오너스 할인 1%"
    # 표면가는 오너스 미반영값 그대로여야 한다
    sale, _, _ = _parse_lotteon_prices(_base(), _qty())
    assert sale == IMMD_PRICE
    assert sale != round(IMMD_PRICE * (1 - rate))


def test_owners_absent_yields_zero_not_guess():
    assert _extract_lotteon_owners_member_discount({}) == (0.0, "")
    assert _extract_lotteon_owners_member_discount(None) == (0.0, "")


# ─────────────────────────────────────────────────────────────
# ③ 폴백이 엉뚱한 값으로 떨어지지 않는가
# ─────────────────────────────────────────────────────────────
def test_falls_back_to_order_price_only_when_immd_missing():
    sale, _, _ = _parse_lotteon_prices(_base(), _qty(immd=0))
    assert sale == ORDER_PRICE


def test_falls_back_to_origin_when_both_qty_amounts_missing():
    """즉시할인·쿠폰 적용가가 모두 없으면 정가 (할인 없는 상품)."""
    sale, _, origin = _parse_lotteon_prices(_base(), _qty(immd=0, order=0))
    assert sale == ORIGIN_PRICE == origin


def test_garbage_amounts_do_not_crash_or_leak():
    """문자열·None 이 와도 0 취급 → 정가 폴백. 예외로 옵션 통째 유실 금지."""
    sale, _, _ = _parse_lotteon_prices(
        _base(), {"immdDcAplyTotAmt": "abc", "orderDcAplyTotAmt": None})
    assert sale == ORIGIN_PRICE


def test_empty_everything_yields_zero_not_guess():
    sale, max_price, origin = _parse_lotteon_prices({}, {})
    assert (sale, max_price, origin) == (0, 0, 0)


# ─────────────────────────────────────────────────────────────
# 선반영 판정표 — dcTnnoCd 계층이 조용히 바뀌면 이중차감/누락
# ─────────────────────────────────────────────────────────────
def test_auto_applied_tiers_are_exactly_1st_2nd_3rd():
    """1ST·2ND·3RD 만 선반영. 4TH(쿠폰)·5TH(카드)가 여기 들어가면 **차감 누락**,
    빠지면 **이중차감**. 어느 쪽이든 금전 직결이라 집합 자체를 고정한다."""
    assert LOTTEON_AUTO_APPLIED_TIERS == {"1ST", "2ND", "3RD"}
