# -*- coding: utf-8 -*-
"""마켓 수수료율은 **어디서 온 숫자인가** — 근거를 코드가 들고 있어야 한다.

🔴 왜 이 시험이 생겼나 (2026-08-13) — 「롯데온 수수료율」이라는 같은 이름의 값이
  저장소 안에 **세 벌** 있고, 서로 다르다:

    · `pricing/fee_defaults.SEED['lotteon']         = 18.0%`  ← **판매가를 정하는 값**
    · `margin/settle_plan._EXPECT_FEE_PCT['lotteon'] = 13.0%`  ← 정산율 경고 판정
    · `margin/lotteon_settlement.compute_settlement`
        = 상품가 13% + 배송비 3.3% + (제휴면 상품가 2%)   ← **실정산 엑셀 86행 오차0**

  셋 중 근거가 있는 건 마지막 하나뿐이다. `settle_plan` 주석도 「18% 는 어디서도
  뒷받침되지 않아 라이브에 9.6%p 거짓 경고를 띄우고 있었다」고 적고 있다.

  제휴를 늘 켜 두시므로(사장님) 롯데온 상품 실효 요율은 **13 + 2 = 15%** 다.
  18% 로 판매가를 내면 매입 50,000 기준 **2,800원(4.2%) 비싸게** 나간다 —
  적자는 아니지만 **안 팔리는 손해**다.

🔴 이 시험은 숫자를 **고치지 않는다.** 돈에 직접 닿는 공용 값이라 사장님 확인이
  먼저다. 대신 지금 상태를 못 박아, 누가 한쪽만 바꾸면 **바로 빨간불**이 뜨게 한다.
"""
import pytest

from lemouton.pricing.fee_defaults import RATE_EVIDENCE, SEED


def test_모든_마켓이_근거를_들고_있다():
    """🔴 근거 없는 숫자가 조용히 돈을 정하면 안 된다."""
    for market in SEED:
        assert market in RATE_EVIDENCE, f'{market} 요율의 근거가 어디에도 없다'
        assert RATE_EVIDENCE[market].get('source'), f'{market}: source 가 비었다'


def test_롯데온은_알려진_불일치를_숨기지_않는다():
    ev = RATE_EVIDENCE['lotteon']
    assert ev.get('disagrees_with'), '롯데온 18% 와 실정산 공식의 어긋남이 안 적혀 있다'
    assert '13' in str(ev['disagrees_with']), '어긋나는 값(13%)이 안 적혀 있다'


def test_근거가_실측인지_말뿐인지_구분한다():
    """🔴 「사장님이 불러 준 값」과 「실정산 대조로 확인」은 무게가 다르다."""
    kinds = {ev.get('kind') for ev in RATE_EVIDENCE.values()}
    assert kinds <= {'measured', 'stated', 'unknown'}, f'모르는 근거 종류: {kinds}'
    assert RATE_EVIDENCE['lotteon']['kind'] != 'measured', \
        '18% 는 실측이 아니다 — 실측된 것은 13+3.3+2 쪽이다'


def test_실정산_공식과_대조한다():
    """🔴 근거 문서가 아니라 **코드**와 맞대 본다 — 문서는 낡는다."""
    from lemouton.margin.lotteon_settlement import compute_settlement

    상품가 = 100_000
    # 제휴 켠 주문(사장님: 우리는 항상 켠다) — 배송비 0 으로 두면 상품 요율만 남는다
    정산 = compute_settlement(상품가, 0, 0, 0, 0, True)
    실효 = (상품가 - 정산) / 상품가 * 100
    assert abs(실효 - 15.0) < 0.01, f'실정산 공식의 상품 실효 요율이 15%가 아니다: {실효}'
    assert abs(SEED['lotteon']['base_pct'] - 실효) > 1.0, \
        '어긋남이 사라졌다 — 사장님 확인 후 고쳐졌다면 이 시험과 근거표도 함께 갱신할 것'


def test_근거_없는_마켓은_그렇다고_적혀_있다():
    """🔴 「모른다」를 「확인됨」으로 적으면 다음 사람이 그 위에 집을 짓는다."""
    for market in ('eleven11', 'auction', 'gmarket'):
        assert RATE_EVIDENCE[market]['kind'] in ('stated', 'unknown'), \
            f'{market} 요율은 실측 근거가 없다 — measured 로 적으면 안 된다'


def test_판매가_영향이_숫자로_적혀_있다():
    """사장님이 판단하시려면 「얼마나 차이 나나」가 있어야 한다."""
    note = str(RATE_EVIDENCE['lotteon'].get('impact') or '')
    assert '%' in note and any(c.isdigit() for c in note), \
        '판매가가 얼마나 차이 나는지 안 적혀 있다'
