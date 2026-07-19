# -*- coding: utf-8 -*-
"""캐시백 적립의 **기준금액 계수**(base_ratio) — 공급가(부가세 제외) 기준.

■ 사장님 확정 (2026-07-19)
  캐시백 사이트는 결제 전액이 아니라 **부가세를 뺀 공급가**에 적립해 준다.
      캐시백 적립 = 기준금액 × 0.9 × 적립율      ← 기본
      캐시백 적립 = 기준금액 × 1.0 × 적립율      ← SSG · 신세계쇼핑 · CJ (전액 기준)

■ 근거 (M6 실주문 3,458건 대조 — 엑셀 「대량위탁」 L열 수식 원문)
      -(K*IF(OR(G="SSG",G="신세계쇼핑",G="CJ"),1,0.9)*VLOOKUP(G,캐시백표,2))
  계수 반영 전 캐시백 '그 외' 구간 일치율 32.9% → 반영 후 77.4%.
  잔여 불일치는 전부 ±100원(순차 누적 차감 ↔ 엑셀 병렬 차감 모델차 × 백원 버림)이고,
  방향도 **매입가 과대**(안전) 쪽으로 뒤집혔다. 반영 전엔 과소(=언더프라이싱)였다.

■ 왜 계수를 적립율에 미리 곱해 넣지 않나
  1.1% × 0.9 = 0.99% 로 뭉개면 영수증에서 사장님이 "왜 1.1%인데 0.99%?" 하게 되고
  근거가 사라진다. 계수는 **기준금액 쪽**에만 걸고, 적립율은 원본 그대로 노출한다.
"""
import pytest

from lemouton.pricing.final_price import compute_final_price


class B:
    """legacy 아이템 (pay_method/channel 없음 → _is_tagged False)."""

    def __init__(self, *, id=1, name='', btype='rate', value=0.0, enabled=True,
                 category=None, apply_mode=None, base_ratio=None):
        self.id = id
        self.benefit_name = name
        self.benefit_type = btype
        self.value = value
        self.enabled = enabled
        self.category = category
        if apply_mode is not None:
            self.apply_mode = apply_mode
        if base_ratio is not None:
            self.base_ratio = base_ratio


def _cash(value, base_ratio=None, name='OK캐시백'):
    return ('tpl', B(name=name, value=value, category='캐시백',
                     apply_mode='cashback', base_ratio=base_ratio))


# ════════════════════════════════════════════════════════════
#  1. 계수가 실제로 차감액을 줄인다
# ════════════════════════════════════════════════════════════

def test_cashback_deduct_uses_supply_price_base():
    """100,000원 × 0.9 × 1.1% → 989원 (계수 없으면 1,100원).

    989 는 오타가 아니다. 부동소수 표현상 100000*0.9*0.011 = 989.9999999999999 이고
    엔진은 차감액을 예전부터 ``int()`` 로 **버림**한다(기존 규약, 여기서 안 바꾼다).
    1원 덜 깎이는 = 매입가가 1원 높아지는 안전 방향이다.
    """
    res = compute_final_price(100000, [_cash(0.011, 0.9)])
    assert res['steps'][0]['deduct'] == 989
    # 계수가 없을 때보다는 확실히 덜 깎인다 (= 매입가 과다차감 교정)
    assert res['steps'][0]['deduct'] < compute_final_price(
        100000, [_cash(0.011)])['steps'][0]['deduct']


def test_ratio_one_is_full_amount_base():
    """예외 3사(SSG·신세계쇼핑·CJ)는 전액 기준 — 100,000 × 1.0 × 2% = 2,000원."""
    res = compute_final_price(100000, [_cash(0.02, 1.0)])
    assert res['steps'][0]['deduct'] == 2000


def test_missing_ratio_defaults_to_full_base():
    """계수 미설정(NULL) = 1.0. 기존 행의 동작이 바뀌지 않는다."""
    assert (compute_final_price(100000, [_cash(0.011)])['steps'][0]['deduct']
            == compute_final_price(100000, [_cash(0.011, 1.0)])['steps'][0]['deduct'])


@pytest.mark.parametrize('bad', [0, -0.5, 1.5, 'x', None])
def test_invalid_ratio_falls_back_to_one(bad):
    """이상값은 1.0 으로 — 계수는 '덜 깎는' 방향이라 모르면 안 줄이는 쪽이 안전하다."""
    res = compute_final_price(100000, [_cash(0.011, bad)])
    assert res['steps'][0]['deduct'] == 1100


# ════════════════════════════════════════════════════════════
#  2. 캐시백이 아닌 혜택에는 절대 붙지 않는다
# ════════════════════════════════════════════════════════════

def test_ratio_ignored_on_non_cashback_item():
    """카드 청구할인에 계수가 붙으면 10% 덜 깎여 매입가가 통째로 틀어진다."""
    card = ('tpl', B(name='현대카드 청구할인', value=0.0273, category='결제',
                     apply_mode='payment', base_ratio=0.9))
    res = compute_final_price(100000, [card])
    assert res['steps'][0]['deduct'] == 2730          # 0.9 가 곱해지지 않았다
    assert res['steps'][0]['base_ratio'] == 1.0


def test_payment_named_cashback_is_not_given_ratio():
    """'무신사머니 캐시백' 은 결제수단 표기가 붙어 캐시백 축이 아니다 → 계수 미적용."""
    it = ('tpl', B(name='무신사머니 캐시백', value=0.02, base_ratio=0.9))
    res = compute_final_price(100000, [it])
    assert res['steps'][0]['deduct'] == 2000
    assert res['steps'][0]['base_ratio'] == 1.0


# ════════════════════════════════════════════════════════════
#  3. 영수증 투명성 — 적립율은 뭉개지 않는다
# ════════════════════════════════════════════════════════════

def test_receipt_keeps_raw_rate_and_exposes_ratio():
    """value 는 1.1% 그대로, 계수는 별도 필드로 드러난다."""
    st = compute_final_price(100000, [_cash(0.011, 0.9)])['steps'][0]
    assert st['value'] == pytest.approx(0.011)   # 0.0099 로 뭉개지지 않았다
    assert st['base_ratio'] == pytest.approx(0.9)
    assert st['base_note'] == '공급가 기준'
    assert st['name'] == 'OK캐시백'              # 이름은 원본 (매트릭스 steps↔items 매칭 키)


def test_no_base_note_when_ratio_is_one():
    """계수가 없으면 영수증에 군더더기 문구를 붙이지 않는다."""
    st = compute_final_price(100000, [_cash(0.02, 1.0)])['steps'][0]
    assert 'base_note' not in st


# ════════════════════════════════════════════════════════════
#  4. 순차 누적 차감 모델은 그대로 (직전 잔액 기준)
# ════════════════════════════════════════════════════════════

def test_ratio_applies_to_running_base_not_original_price():
    """계수는 '직전 잔액'에 건다 — 순차 누적 모델(2026-06-07 확정)을 바꾸지 않는다.

    100,000 → 카드 2.73% 차감 2,730 → 잔액 97,270
             → 캐시백 97,270 × 0.9 × 1.1% = 962원 (원 판매가 기준이었다면 989원)
    """
    card = ('tpl', B(id=1, name='현대카드 청구할인', value=0.0273, category='결제'))
    res = compute_final_price(100000, [card, _cash(0.011, 0.9)])
    assert res['steps'][0]['base_after'] == 97270
    assert res['steps'][1]['deduct'] == int(97270 * 0.9 * 0.011)
    assert res['steps'][1]['deduct'] == 962
    # 원 판매가(100,000)가 아니라 직전 잔액(97,270)에 걸렸다는 증거
    assert res['steps'][1]['deduct'] != int(100000 * 0.9 * 0.011)
