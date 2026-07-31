# -*- coding: utf-8 -*-
"""[TEST] 「이 정책으로 계산하면」 미리보기.

사장님 확정 — 판매가 = **최종매입가** × (1 + 마진율). 표면가가 기준이 아니다.

여기서 못 박는 것:
  · 마진율을 **안 정했으면 계산하지 않는다**. 빈칸을 0% 로 읽으면 그 가격이
    그대로 마켓에 나간다(금전 손실).
  · 0% 는 「0% 로 정함」이라 값이다 — 안 정함과 다르다.
  · 최종매입가를 모르는 옵션은 판매가를 지어내지 않는다.
"""
from unittest.mock import patch

from lemouton.policy import preview as PV


def _matrix(options):
    return lambda mc: {'ok': True, 'options': options}


def _run(values, options, finals, *, market='smartstore'):
    from lemouton.orders import price_diff as PD
    with patch.object(PD, '_current_purchase', return_value=(finals, {})):
        return PV.preview_for_model(None, model_code='M', values=values,
                                    market=market, matrix_loader=_matrix(options))


# ── 마진율 읽기 ─────────────────────────────────────────────────────────────

def test_마진율을_안_정했으면_없음이다():
    assert PV.margin_rate_of({}) is None
    assert PV.margin_rate_of({'price': {}}) is None
    assert PV.margin_rate_of({'price': {'mode': 'margin_rate'}}) is None


def test_0퍼센트는_정한_값이다():
    """「안 정함」과 「0% 로 정함」은 다른 뜻이다."""
    assert PV.margin_rate_of({'price': {'mode': 'margin_rate', 'margin_rate': 0}}) == 0.0


# ── 계산 ────────────────────────────────────────────────────────────────────

def test_최종매입가에_마진율을_붙인다():
    out = _run({'price': {'mode': 'margin_rate', 'margin_rate': 25}},
               [{'sku': 'S1', 'color': '블랙', 'size': '250', 'ss_price': 120000}],
               {'S1': 100000})
    assert out['ok'] is True
    r = out['rows'][0]
    assert r['purchase'] == 100000
    assert r['policy_price'] == 125000        # 백원 버림
    assert r['current_price'] == 120000
    assert r['diff'] == 5000


def test_백원_단위로_버린다():
    out = _run({'price': {'mode': 'margin_rate', 'margin_rate': 13}},
               [{'sku': 'S1', 'ss_price': None}], {'S1': 107777})
    # 107777 × 1.13 = 121,787.01 → 121,700
    assert out['rows'][0]['policy_price'] == 121700


def test_마진율이_비면_아예_계산하지_않는다():
    out = _run({}, [{'sku': 'S1'}], {'S1': 100000})
    assert out['ok'] is False
    assert out['rows'] == []
    assert '마진율' in out['reason']


def test_최종매입가를_모르면_판매가를_지어내지_않는다():
    out = _run({'price': {'mode': 'margin_rate', 'margin_rate': 25}},
               [{'sku': 'S1', 'ss_price': 120000}], {})
    r = out['rows'][0]
    assert r['purchase'] is None
    assert r['policy_price'] is None
    assert r['diff'] is None


def test_고정_금액_방식이면_그_값을_쓴다():
    out = _run({'price': {'mode': 'fixed_amount', 'fixed_amount': 99000}},
               [{'sku': 'S1', 'ss_price': 120000}], {'S1': 100000})
    assert out['rows'][0]['policy_price'] == 99000
    assert out['rows'][0]['diff'] == -21000


def test_매트릭스가_판매가를_안_내는_마켓은_그렇다고_말한다():
    """스스·쿠팡 말고는 지금 판매가를 매트릭스가 내지 않는다 — 빈칸을 숨기지 않는다."""
    out = _run({'price': {'mode': 'margin_rate', 'margin_rate': 25}},
               [{'sku': 'S1', 'ss_price': 120000}], {'S1': 100000},
               market='lotteon')
    assert out['rows'][0]['current_price'] is None
    assert '지금 판매가' in out['reason']
