# -*- coding: utf-8 -*-
"""판매자 부담 할인 — 할인 뒤에도 목표 마진이 남게 판매가를 올려 잡는다.

사장님 확정(2026-08-13):
  마진 기준가 = 판매가 − **판매자 부담** 할인액. 마켓이 같이 부담하는 몫은
  우리 수입이라 빼지 않는다.

무슨 사고였나 — 스마트스토어에 「고객에게 싸게 보이려고」 20% 할인을 걸어 뒀는데,
마진율은 **할인 전 판매가** 기준으로 계산돼 있었다. 고객이 내는 돈은 80% 인데
마진은 100% 기준으로 잡아, 마진율 9.45% 상품이 **적자로 넘어갔다**
(손익분기 할인율 = 마진율 ÷ (1 − 수수료율) = 9.45 ÷ 0.94 ≈ 10.0%).

🔴 이 시험이 지키는 것
  ① 할인 0 이면 **지금과 한 원도 다르지 않다**(기존 전 상품에 영향 없음)
  ② 할인이 있으면 **할인 뒤 실수령이 목표 마진과 맞는다**
  ③ 버림은 **맨 마지막 한 번만** — 두 번 하면 100원을 더 손해 본다
"""
import pytest

from lemouton.pricing.unified import compute_sale_price_unified

매입 = 50000
스스수수료 = 0.06
스스마진 = 0.0945


def _실수령(노출가: int, 수수료율: float, 배송비: int = 0) -> float:
    """고객이 내는 돈에서 수수료를 뗀 실수령. 마켓 수수료는 **실결제액 기준**이다."""
    return (노출가 - 배송비) * (1 - 수수료율)


def test_할인이_없으면_지금과_똑같다():
    """🔴 기존 전 상품에 영향이 없어야 한다 — 새 인자의 기본값은 「할인 없음」."""
    전 = compute_sale_price_unified(매입, 스스마진, 스스수수료)
    후 = compute_sale_price_unified(매입, 스스마진, 스스수수료,
                                    seller_discount_unit="PERCENT", seller_discount_value=0)
    assert 전.final_price == 후.final_price


def test_정률_할인이면_판매가를_그만큼_올려_잡는다():
    """20% 할인이면 고객이 내는 80% 가 원래 판매가와 같아야 한다."""
    할인없음 = compute_sale_price_unified(매입, 스스마진, 스스수수료).final_price
    할인있음 = compute_sale_price_unified(매입, 스스마진, 스스수수료,
                                          seller_discount_unit="PERCENT", seller_discount_value=20)
    노출가 = round(할인있음.final_price * 0.8)
    # 버림(100원) 때문에 딱 떨어지지 않을 수 있으나, 한 단위 안이어야 한다
    assert abs(노출가 - 할인없음) <= 100, f"할인 뒤 고객가 {노출가} vs 원래 판매가 {할인없음}"


def test_정률_할인_뒤에도_목표_마진이_남는다():
    """🔴 이게 핵심 — 할인 뒤 실수령이 매입가보다 목표 마진만큼 많아야 한다."""
    r = compute_sale_price_unified(매입, 스스마진, 스스수수료,
                                   seller_discount_unit="PERCENT", seller_discount_value=20)
    노출가 = r.final_price * 0.8
    남는돈 = _실수령(노출가, 스스수수료) - 매입
    목표 = 노출가 * 스스마진
    assert 남는돈 > 0, f"할인 뒤에도 적자다: {남는돈:,.0f}원"
    assert abs(남는돈 - 목표) <= 200, f"목표 {목표:,.0f} vs 실제 {남는돈:,.0f}"


def test_고치기_전이라면_적자였다는_것을_숫자로_남긴다():
    """할인을 안 올려 잡으면 실제로 적자가 된다 — 왜 고쳤는지 숫자로 못 박는다."""
    올려잡지_않은_판매가 = compute_sale_price_unified(매입, 스스마진, 스스수수료).final_price
    노출가 = 올려잡지_않은_판매가 * 0.8
    남는돈 = _실수령(노출가, 스스수수료) - 매입
    assert 남는돈 < 0, "이 시험의 전제가 깨졌다 — 원래는 적자였어야 한다"


def test_정액_할인은_그_금액만큼_올려_잡는다():
    할인없음 = compute_sale_price_unified(매입, 0.1242, 0.1155).final_price
    할인있음 = compute_sale_price_unified(매입, 0.1242, 0.1155,
                                          seller_discount_unit="WON", seller_discount_value=100)
    assert 할인있음.final_price - 할인없음 in (100, 0), \
        f"정액 100원 할인이면 판매가도 100원 올라야 한다: {할인없음} → {할인있음.final_price}"


def test_버림은_맨_마지막_한_번만():
    """🔴 이미 버림한 값을 다시 나눠 또 버리면 100원을 더 손해 본다."""
    r = compute_sale_price_unified(매입, 스스마진, 스스수수료,
                                   seller_discount_unit="PERCENT", seller_discount_value=20)
    # 두 번 버린 값(잘못된 방식)보다 크거나 같아야 한다
    두번버림 = (int(compute_sale_price_unified(매입, 스스마진, 스스수수료).final_price / 0.8) // 100) * 100
    assert r.final_price >= 두번버림


def test_100퍼센트_할인은_막는다():
    """공짜가 되는 값은 받지 않는다 — 폴백으로 넘기지 말고 못 낸다고 말한다."""
    r = compute_sale_price_unified(매입, 스스마진, 스스수수료,
                                   seller_discount_unit="PERCENT", seller_discount_value=100)
    assert r.final_price == 0
    assert r.breakdown.get("impossible") is True


def test_근거를_breakdown_에_남긴다():
    """화면이 다시 계산하지 않도록 기준가와 고객 노출가를 같이 준다."""
    r = compute_sale_price_unified(매입, 스스마진, 스스수수료,
                                   seller_discount_unit="PERCENT", seller_discount_value=20)
    b = r.breakdown
    assert b["seller_discount_unit"] == "PERCENT"
    assert b["seller_discount_value"] == 20
    assert b["margin_basis"] > 0, "마진을 어느 값 기준으로 쟀는지"
    assert b["net_basis_price"] > 0, "고객이 실제로 보는 값"
    assert b["net_basis_price"] < r.final_price, "노출가는 판매가보다 작아야 한다"


def test_지정가_모드는_올려_잡지_않는다():
    """사람이 직접 친 값은 그대로 둔다 — 할인은 그 값 안에 이미 반영된 것으로 본다."""
    r = compute_sale_price_unified(매입, 0, 0.06, mode="fixed", fixed_price=70000,
                                   seller_discount_unit="PERCENT", seller_discount_value=20)
    assert r.final_price == 70000
