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


def test_확정된_요율은_실측으로_적혀_있다():
    """🔴 [2026-08-13] 롯데온·11번가는 사장님이 확정해 주셨다 — 근거가 생겼다.

    전에는 둘 다 「구두 전달」이었고 롯데온은 실정산 공식과 **어긋나** 있었다
    (18% vs 13+3.3+2). 그 어긋남을 화면과 이 시험이 드러냈고, 사장님이 13% 로
    확정해 주시면서 해소됐다. 이제 근거표도 그렇게 말해야 한다.
    """
    for market in ('lotteon', 'eleven11'):
        ev = RATE_EVIDENCE[market]
        assert ev['kind'] == 'measured', f'{market} 은 이제 확정된 값이다'
        assert not ev.get('disagrees_with'),             f'{market} 에 해소된 어긋남이 아직 적혀 있다 — 낡은 경고는 진짜 경고를 가린다'
        assert '2026-08-13' in ev['source'], '언제 확정됐는지 안 적혀 있다'


def test_근거가_실측인지_말뿐인지_구분한다():
    """🔴 「사장님이 불러 준 값」과 「대조로 확인」은 무게가 다르다."""
    kinds = {ev.get('kind') for ev in RATE_EVIDENCE.values()}
    assert kinds <= {'measured', 'stated', 'unknown'}, f'모르는 근거 종류: {kinds}'


def test_실정산_공식과_대조한다():
    """🔴 근거 문서가 아니라 **코드**와 맞대 본다 — 문서는 낡는다.

    롯데온 **제휴 경유** 주문의 상품 실효 요율 = 판매가가 쓰는 값(늘 켜므로).
    """
    from lemouton.margin.lotteon_settlement import compute_settlement

    상품가 = 100_000
    제휴 = compute_settlement(상품가, 0, 0, 0, 0, True)     # 늘 켜는 쪽이 기준
    실효 = (상품가 - 제휴) / 상품가 * 100
    assert abs(SEED['lotteon']['base_pct'] - 실효) < 0.01,         f'판매가용 요율이 실정산 공식과 다르다: {SEED["lotteon"]["base_pct"]} vs {실효}'

    # 직영(롯데ON 직접 유입)은 제휴 2%p 가 안 붙는다
    직영 = compute_settlement(상품가, 0, 0, 0, 0, False)
    assert (직영 - 제휴) == round(상품가 * 0.02), '제휴 2% 전제가 깨졌다'


def test_아직_대조_못_한_마켓은_그렇다고_적혀_있다():
    """🔴 「모른다」를 「확인됨」으로 적으면 다음 사람이 그 위에 집을 짓는다."""
    for market in ('auction', 'gmarket'):
        assert RATE_EVIDENCE[market]['kind'] in ('stated', 'unknown'),             f'{market} 은 아직 정산 공식으로 대조하지 못했다'
