# -*- coding: utf-8 -*-
"""마진은 **고객이 실제로 내는 값** 기준으로 재야 한다.

🔴 왜 이 시험이 생겼나 — 판매자 부담 할인만큼 판매가를 올려 잡게 되면서
  `final_price`(표시 판매가)와 `exposed_price`(고객이 내는 값)가 갈렸다.
  마진을 표시 판매가로 재면 **실제보다 훨씬 많이 남는 것처럼 보인다** —
  스스 20% 할인 기준으로 +5,573원이 +19,466원으로 보인다(3.5배 과대).

  그 숫자가 **역마진 가드의 입력**이라, 과대평가되면 적자 상품이 그대로 통과한다.
  가드 자체는 멀쩡한데 먹이는 값이 틀려서 조용히 뚫린다 — 이 저장소가
  반복해서 당한 「에러 없이 숫자만 틀리는」 형태다.
"""
import pytest

from lemouton.pricing.unified import compute_sale_price_unified
from lemouton.uploader.reconcile import compute_margin_amount

매입 = 50000


def test_할인이_없으면_지금과_같다():
    """기존 전 상품에 영향이 없어야 한다."""
    r = compute_sale_price_unified(매입, 0.0945, 0.06)
    got = compute_margin_amount(r, 매입)
    직접 = int(round(r.final_price * (1 - 0.06))) - 매입
    assert got == 직접


def test_할인이_있으면_고객이_내는_값으로_잰다():
    """🔴 표시 판매가로 재면 3배 넘게 부풀어 보인다."""
    r = compute_sale_price_unified(매입, 0.0945, 0.06,
                                   seller_discount_unit="PERCENT", seller_discount_value=20)
    got = compute_margin_amount(r, 매입)
    노출 = r.breakdown["net_basis_price"]
    옳은값 = int(round(노출 * (1 - 0.06))) - 매입
    부풀린값 = int(round(r.final_price * (1 - 0.06))) - 매입
    assert got == 옳은값, f"고객가 기준이어야 한다: {got:,} vs {옳은값:,}"
    assert got != 부풀린값, "표시 판매가로 재고 있다"
    assert 부풀린값 > 옳은값 * 2, "이 시험의 전제가 깨졌다 — 원래 크게 부풀었어야 한다"


def test_적자_상품이_적자로_보인다():
    """마진율이 손익분기(할인율)보다 낮으면 음수가 나와야 가드가 잡는다."""
    r = compute_sale_price_unified(매입, 0.03, 0.06,       # 마진 3% 인데
                                   seller_discount_unit="PERCENT", seller_discount_value=20)
    # 올려 잡았으므로 고객가 기준으로는 목표(3%)가 남는다 — 즉 적자가 아니다
    assert compute_margin_amount(r, 매입) > 0
    # 그런데 「올려 잡지 않은」 옛 방식이라면 적자였다
    옛방식 = compute_sale_price_unified(매입, 0.03, 0.06)
    노출 = int(round(옛방식.final_price * 0.8))
    assert int(round(노출 * 0.94)) - 매입 < 0


def test_모든_모드가_고객가를_알려_준다():
    """🔴 한 모드만 넣으면 다른 경로가 조용히 표시가로 잰다."""
    for kw in ({}, {"mode": "amount", "margin_amount": 5000},
               {"mode": "fixed", "fixed_price": 70000}):
        r = compute_sale_price_unified(매입, 0.0945, 0.06, **kw)
        assert "net_basis_price" in r.breakdown, f"{kw} 모드에 고객가가 없다"
        assert r.breakdown["net_basis_price"] > 0
