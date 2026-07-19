# -*- coding: utf-8 -*-
"""혜택 차감 순서 = 정액(원) → 정률(%). 선반영·후반영 구분 없음.

사용자 확정 2026-07-19:
  "선반영, 후반영 이제는 빼. 그냥 정액 → 정률 순서로만."

바로잡는 것 2가지
  ① 이름이 금액을 바꾸던 문제
     기존 `_benefit_priority` 가 **이름에 '적립' 두 글자가 있는지**로 순서를 정했다.
     → 「등급 적립」을 「등급 리워드」로 이름만 바꿔도 차감 순서가 달라져 최종가가 변했다.
     패널에서 혜택 이름을 편집하게 되므로 그대로 두면 편집이 곧 사고다.
  ② 선반영이면 안 빼던 문제
     apply_mode='preapplied' 는 차감을 건너뛰었다. 그런데 무신사 표면가(salePrice)는
     등급할인 **적용 전** 값이라 빼는 게 맞다. 가이드 표기가 틀렸던 것.
     → 선반영 개념을 없애고 전부 차감한다.

유지하는 것 (별개 축이라 건드리지 않음)
  · payment  = 결제수단 택1 (L.PAY vs 네이버페이 vs 카드 — 동시 적용 불가)
  · cashback = 유입경로 축 + base_ratio(공급가 기준 계수)
"""
import pytest

from lemouton.pricing.final_price import compute_final_price


class _It:
    """compute_final_price 가 기대하는 혜택 항목 최소 형태."""
    def __init__(self, name, btype, value, *, apply_mode=None, enabled=True):
        self.id = -1
        self.benefit_name = name
        self.benefit_type = btype          # 'amount' | 'rate'
        self.value = value                 # amount=원 / rate=0.05 = 5%
        self.enabled = enabled
        self.apply_mode = apply_mode
        self.category = None
        self.sort_order = 999
        self.template_id = None
        self.base_ratio = 1.0
        self.pay_method = None
        self.channel = None


def _run(items, sale_price=100000):
    return compute_final_price(float(sale_price), [('t', it) for it in items])


# ── ① 이름이 금액을 바꾸면 안 된다 ────────────────────────────────────────

def test_renaming_a_benefit_does_not_change_final_price():
    """「등급 적립」 → 「등급 리워드」로 이름만 바꿔도 최종가가 같아야 한다."""
    before = _run([_It('등급 적립', 'rate', 0.01), _It('쿠폰', 'amount', 3000)])
    after = _run([_It('등급 리워드', 'rate', 0.01), _It('쿠폰', 'amount', 3000)])
    assert before['final_price'] == after['final_price']


def test_name_containing_jeoklip_does_not_reorder():
    """이름에 '적립'이 있든 없든 정률끼리는 순서가 금액을 바꾸지 않아야 한다."""
    a = _run([_It('A 적립', 'rate', 0.05), _It('B 할인', 'rate', 0.03)])
    b = _run([_It('A 할인', 'rate', 0.05), _It('B 적립', 'rate', 0.03)])
    assert a['final_price'] == b['final_price']


# ── ② 정액 먼저, 정률 나중 ────────────────────────────────────────────────

def test_amount_is_deducted_before_rate():
    """정액 3,000원 먼저 빼고, 남은 97,000 에 10% → 9,700. 최종 87,300."""
    r = _run([_It('정률 10%', 'rate', 0.10), _It('정액 3천', 'amount', 3000)])
    assert r['final_price'] == 87300


def test_input_order_does_not_matter():
    """입력 순서를 뒤집어도 결과가 같아야 한다(정렬이 순서를 결정)."""
    a = _run([_It('정액', 'amount', 5000), _It('정률', 'rate', 0.10)])
    b = _run([_It('정률', 'rate', 0.10), _It('정액', 'amount', 5000)])
    assert a['final_price'] == b['final_price'] == 85500


# ── ③ 선반영은 더 이상 건너뛰지 않는다 ────────────────────────────────────

def test_preapplied_is_now_deducted():
    """apply_mode='preapplied' 도 그냥 차감된다 (선반영 개념 폐지)."""
    r = _run([_It('등급 할인', 'rate', 0.05, apply_mode='preapplied')])
    assert r['final_price'] == 95000


def test_preapplied_and_deduct_give_same_result():
    """선반영으로 적혔든 후반영으로 적혔든 결과가 같아야 한다."""
    pre = _run([_It('등급 할인', 'rate', 0.05, apply_mode='preapplied')])
    ded = _run([_It('등급 할인', 'rate', 0.05, apply_mode='deduct')])
    assert pre['final_price'] == ded['final_price']


def test_no_item_is_marked_preapplied_in_receipt():
    """영수증에 'preapplied' 표시가 더는 남지 않는다."""
    r = _run([_It('등급 할인', 'rate', 0.05, apply_mode='preapplied')])
    for it in (r.get('items_used') or []):
        assert not it.get('preapplied')


# ── ④ 꺼진 혜택은 여전히 안 빠진다 ────────────────────────────────────────

def test_disabled_benefit_is_not_deducted():
    r = _run([_It('제외한 혜택', 'rate', 0.10, enabled=False)])
    assert r['final_price'] == 100000
