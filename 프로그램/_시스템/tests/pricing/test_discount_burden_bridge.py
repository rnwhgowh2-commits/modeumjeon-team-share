# -*- coding: utf-8 -*-
"""정책의 할인·부담 주체가 **가격 엔진까지 실제로 흐르는지**.

🔴 엔진에 인자를 넣어도 다리(`resolve_market_policy` → `compute_market_price`)가
  안 넘기면 값이 영영 0 으로 간다 — 「고쳤는데 화면이 안 바뀐다」의 전형.

부담 주체 규칙 (사장님 확정 2026-08-13):
  · seller = 판매자 100% 부담 → 그만큼 판매가를 올려 잡는다
  · market = 마켓이 부담 → **올리지 않는다**(그 몫은 우리 수입이다)
  · split  = 우리가 낸 몫만큼만 올린다
"""
import pytest

from lemouton.pricing.unified import (
    compute_market_price, resolve_market_policy, compute_sale_price_unified,
)


class 정책:
    """PriceTemplate 흉내 — 엔진이 읽는 속성만 갖는다."""

    def __init__(self, **kw):
        self.ss_mode_sourcing = "rate"
        # 🔴 정책은 **소수**로 저장한다(9.45% → 0.0945). 퍼센트를 넣으면
        #   수수료+마진이 100% 를 넘어 「판매가를 정할 수 없음」이 된다.
        self.ss_rate_sourcing = 0.0945
        self.ss_fee_rate = 0.06
        self.ss_delivery_fee = 0
        self.rounding_unit = 100
        for k, v in kw.items():
            setattr(self, k, v)


def test_다리가_할인을_엔진까지_넘긴다():
    """🔴 이게 끊기면 엔진을 아무리 고쳐도 값이 안 흐른다."""
    pol = resolve_market_policy(
        정책(ss_discount_unit="PERCENT", ss_discount_value=20, ss_discount_burden="seller"),
        "smartstore", "sourcing")
    assert pol["seller_discount_unit"] == "PERCENT"
    assert pol["seller_discount_value"] == 20


def test_판매자_부담이면_판매가를_올려_잡는다():
    없음 = compute_market_price(정책(), "smartstore", "sourcing", 50000).final_price
    있음 = compute_market_price(
        정책(ss_discount_unit="PERCENT", ss_discount_value=20, ss_discount_burden="seller"),
        "smartstore", "sourcing", 50000).final_price
    assert 있음 > 없음, f"판매자 부담인데 안 올랐다: {없음} → {있음}"


def test_마켓_부담이면_올리지_않는다():
    """마켓이 내는 몫까지 판매가에 얹으면 고객에게 괜히 비싸 보인다."""
    없음 = compute_market_price(정책(), "smartstore", "sourcing", 50000).final_price
    마켓 = compute_market_price(
        정책(ss_discount_unit="PERCENT", ss_discount_value=20, ss_discount_burden="market"),
        "smartstore", "sourcing", 50000).final_price
    assert 마켓 == 없음, f"마켓 부담인데 판매가가 올랐다: {없음} → {마켓}"


def test_반반이면_우리_몫만큼만_올린다():
    전부 = compute_market_price(
        정책(ss_discount_unit="PERCENT", ss_discount_value=20, ss_discount_burden="seller"),
        "smartstore", "sourcing", 50000).final_price
    반 = compute_market_price(
        정책(ss_discount_unit="PERCENT", ss_discount_value=20,
             ss_discount_burden="split", ss_discount_burden_pct=50),
        "smartstore", "sourcing", 50000).final_price
    없음 = compute_market_price(정책(), "smartstore", "sourcing", 50000).final_price
    assert 없음 < 반 < 전부, f"반반이 가운데가 아니다: {없음} / {반} / {전부}"


def test_부담_주체를_안_정했으면_판매자로_본다():
    """🔴 모르면 보수적으로 — 「마켓」으로 잘못 보면 판매가를 안 올려 적자가 된다."""
    기본 = compute_market_price(
        정책(ss_discount_unit="PERCENT", ss_discount_value=20),   # burden 미설정
        "smartstore", "sourcing", 50000).final_price
    판매자 = compute_market_price(
        정책(ss_discount_unit="PERCENT", ss_discount_value=20, ss_discount_burden="seller"),
        "smartstore", "sourcing", 50000).final_price
    assert 기본 == 판매자


def test_할인을_안_정한_기존_정책은_한_원도_안_바뀐다():
    """🔴 지금 저장된 정책은 할인 칸이 비어 있다 — 전 상품에 영향이 없어야 한다."""
    assert (compute_market_price(정책(), "smartstore", "sourcing", 50000).final_price
            == compute_sale_price_unified(50000, 0.0945, 0.06).final_price)
