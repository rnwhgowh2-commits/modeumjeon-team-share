# -*- coding: utf-8 -*-
"""정산 추정에 배송비(고객배송비) 전액 포함 — 롯데온·11번가 미정산 추정.

샵마인 정산예상금액_배송비포함 = 상품정산(수수료 차감) + 배송비(전액). 미정산 주문 추정 시
배송비가 빠지면 마진이 배송비만큼 과소(사용자 지적 2026-07-15). 실결제 기반은 (실결제−배송비)에
수수료율을 곱해 상품정산을 만들고 배송비를 전액 재가산, 단가 기반은 단가×수량×수수료율 + 배송비.
정산완료(real: 롯데온 실결제−실수수료, 11번가 stlPlnAmt)는 이미 배송비 포함 → 재가산 안 함.
"""
from lemouton.margin.sell_source import (
    _settlement_for,
    LO_FEE_FACTOR_PAID, LO_FEE_FACTOR_LIST,
    EL_FEE_FACTOR_PAID, EL_FEE_FACTOR_LIST,
)


def test_lotteon_estimate_realpaid_adds_full_shipping():
    row = {"판매처": "롯데온", "실결제금액": 34000, "마켓수수료": "",
           "배송비": 4000, "단가": 30000, "수량": 1}
    settle, src = _settlement_for(row)
    assert src == "estimated"
    assert settle == round((34000 - 4000) * LO_FEE_FACTOR_PAID) + 4000


def test_lotteon_estimate_unitbased_adds_full_shipping():
    row = {"판매처": "롯데온", "실결제금액": "", "마켓수수료": "",
           "배송비": 3000, "단가": 50000, "수량": 2}
    settle, src = _settlement_for(row)
    assert src == "estimated"
    assert settle == round(50000 * 2 * LO_FEE_FACTOR_LIST) + 3000


def test_eleven11_estimate_realpaid_adds_full_shipping():
    row = {"판매처": "11번가", "_settle_source": "none", "정산예정금액": "",
           "실결제금액": 25000, "배송비": 2500, "단가": 20000, "수량": 1}
    settle, src = _settlement_for(row)
    assert src == "estimated"
    assert settle == round((25000 - 2500) * EL_FEE_FACTOR_PAID) + 2500


def test_eleven11_estimate_unitbased_adds_full_shipping():
    row = {"판매처": "11번가", "_settle_source": "none", "정산예정금액": "",
           "실결제금액": "", "배송비": 2500, "단가": 20000, "수량": 1}
    settle, src = _settlement_for(row)
    assert settle == round(20000 * 1 * EL_FEE_FACTOR_LIST) + 2500


def test_lotteon_real_does_not_double_add_shipping():
    # 실수수료 확보 → 실결제−수수료. 실결제에 배송비 이미 포함 → 재가산 금지.
    row = {"판매처": "롯데온", "실결제금액": 34000, "마켓수수료": 1800, "배송비": 4000}
    settle, src = _settlement_for(row)
    assert src == "real" and settle == 34000 - 1800


def test_eleven11_real_stlpln_does_not_double_add_shipping():
    # stlPlnAmt(정산예정금액) 확보 → 그대로. 이미 배송비 포함 → 재가산 금지.
    row = {"판매처": "11번가", "_settle_source": "real", "정산예정금액": 59404, "배송비": 4000}
    settle, src = _settlement_for(row)
    assert src == "real" and settle == 59404


def test_no_shipping_key_is_treated_as_zero():
    row = {"판매처": "롯데온", "실결제금액": "", "마켓수수료": "", "단가": 10000, "수량": 1}
    settle, src = _settlement_for(row)
    assert settle == round(10000 * 1 * LO_FEE_FACTOR_LIST)   # 배송비 없음 → +0
