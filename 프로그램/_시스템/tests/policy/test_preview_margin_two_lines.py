# -*- coding: utf-8 -*-
"""[2026-08-13 사장님 확정] 정책 미리보기 마진을 **두 줄**로 — 정가 기준 / 할인가 기준.

■ 사장님 정의
    「할인가 = 판매가 − 즉시할인 − 쿠폰적용.
      **정산되는 기준이 되는 금액이 할인가**」

  쿠팡 정산 엑셀 상품행 299건 전수로 확인된 사실이다:
      정산금액 = 할인가 − 수수료   → 안 맞는 행 0
      정산금액 = 판매액 − 수수료   → 안 맞는 행 109
  (쿠팡에서 「즉시할인」은 즉시할인쿠폰으로 구현되므로 둘이 같은 값이다.)

■ 종전 — 마진이 **정가 기준 한 줄뿐**이었다
  `preview.py` 는 `policy_price`(정가)로만 마진을 냈다. 즉시할인을 걸어 두면
  실제로 받는 돈은 그보다 적은데 화면은 정가 기준 마진만 보여줘, 남는 줄 알았던
  마진이 실제로는 없을 수 있었다.

■ 🔴 지어내지 않는다
  즉시할인이 없으면 **할인가 줄을 만들지 않는다**(정가와 같은 값을 두 번 보여주면
  「할인이 걸린 것처럼」 읽힌다). 계산에 필요한 값이 없으면 `None` — 0 으로 채우지 않는다.
"""
from lemouton.policy.preview import margin_lines


def _line(정가=100000, 매입가=60000, 수수료율=11.55, 할인=None):
    return margin_lines(price=정가, purchase=매입가, fee_pct=수수료율,
                        discount=할인)


# ── 정가 줄은 종전 그대로 ─────────────────────────────────────

def test_정가_기준_줄은_종전과_같다():
    """맞던 것까지 바꾸지 않는다 — 이 값이 흔들리면 기존 화면이 통째로 달라진다."""
    got = _line()
    # 100,000 × 11.55% = 11,550 → 100,000 − 60,000 − 11,550 = 28,450
    assert got['list']['margin'] == 28450
    assert got['list']['price'] == 100000
    # 28,450 / 100,000 = 28.45% → 기존 화면과 같은 자리·같은 반올림(28.4)
    assert got['list']['margin_rate'] == 28.4


# ── 할인가 줄 ─────────────────────────────────────────────────

def test_즉시할인이_있으면_할인가_줄이_생긴다():
    got = _line(할인={'value': 10000, 'unitType': 'WON'})
    d = got['discounted']
    assert d is not None, '즉시할인을 걸었는데 할인가 줄이 없다'
    assert d['price'] == 90000
    # 90,000 × 11.55% = 10,395 → 90,000 − 60,000 − 10,395 = 19,605
    assert d['margin'] == 19605


def test_퍼센트_할인도_같은_함수로():
    got = _line(할인={'value': 10, 'unitType': 'PERCENT'})
    assert got['discounted']['price'] == 90000


def test_할인이_없으면_할인가_줄을_안_만든다():
    """🔴 정가와 같은 값을 두 번 보여주면 「할인이 걸린 것처럼」 읽힌다."""
    assert _line(할인=None)['discounted'] is None
    assert _line(할인={'value': 0, 'unitType': 'WON'})['discounted'] is None


def test_할인가_마진이_정가_마진보다_작다():
    """당연해 보이지만, 수수료를 정가로 물리는 실수를 하면 이게 깨진다."""
    got = _line(할인={'value': 10000, 'unitType': 'WON'})
    assert got['discounted']['margin'] < got['list']['margin']


def test_수수료는_할인가에_물린다():
    """🔴 정산 기준이 할인가이므로 수수료도 할인가로 매겨진다(엑셀 299행 전수 확인)."""
    got = _line(정가=100000, 매입가=0, 수수료율=10.0,
                할인={'value': 20000, 'unitType': 'WON'})
    assert got['discounted']['margin'] == 80000 - 8000   # 정가로 물리면 72,000 이 된다


# ── 모르면 「확인 불가」 ───────────────────────────────────────

def test_매입가를_모르면_0이_아니라_모른다고_한다():
    got = margin_lines(price=100000, purchase=None, fee_pct=11.55, discount=None)
    assert got['list']['margin'] is None, '매입가가 없는데 마진을 지어냈다'


def test_수수료율을_모르면_마진을_안_만든다():
    got = margin_lines(price=100000, purchase=60000, fee_pct=None, discount=None)
    assert got['list']['margin'] is None
