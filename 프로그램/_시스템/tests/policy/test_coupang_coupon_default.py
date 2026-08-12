# -*- coding: utf-8 -*-
"""[2026-08-13 사장님 확정] 쿠팡 쿠폰 기본값 100원 + 「너무 작아 거부될 수 있다」 미리 알림.

■ 사장님 말씀
    「쿠팡에서 즉시할인과 쿠폰적용은 **다른 것**이다(목적은 같음).
      보통 쿠폰은 **100원만 준다**. 그래서 기본값으로 100원을 주도록 해야 한다.」

  쿠팡 정산 엑셀도 둘을 따로 준다 — `판매자 할인쿠폰(A.즉시할인)` / `(B.다운로드)`.
  둘 다 판매자 부담이라 정산 기준(할인가)에서 **둘 다 빠진다**.

■ 🔴 그런데 100원이 거부된 실측이 있다
  다른 세션 라이브 시험(2026-08-06 · 커밋 `6d4164d9`):
      128,900원 상품에 100원(0.07%) → **[CIE06] 「할인이 너무 작거나 너무 큽니다」**
      같은 상품에 1,400원(1.09%)  → 통과 (사장님 실쿠폰)
  문서상 하한은 100원이지만, **판매가 대비 비율 하한이 따로 있는 것으로 보인다**.

  → 기본값은 사장님 말씀대로 **100원**으로 둔다(막지 않는다).
    다만 비율이 너무 낮으면 **보내기 전에 「거부될 수 있다」고 말한다** —
    말 안 하면 사장님은 [CIE06] 을 받고도 무엇이 잘못인지 알 수 없다.
  🔴 비율 하한을 **규칙으로 못 박지 않는다** — 관측 1건뿐이라 그걸 상한처럼 쓰면
    멀쩡한 쿠폰까지 막는다. 막는 게 아니라 **알리는** 자리다.
"""
from lemouton.policy.discount import (
    COUPANG_DEFAULT_WON, default_discount, problem_for, warn_for,
)


# ── 기본값 ────────────────────────────────────────────────────

def test_쿠팡_기본_쿠폰은_100원():
    assert COUPANG_DEFAULT_WON == 100
    d = default_discount('coupang')
    assert d == {'value': 100, 'unitType': 'WON'}


def test_기본값은_쿠팡_규칙을_통과한다():
    """기본값이 자기 규칙에 걸리면 안 된다(10원 단위·최소 100원)."""
    assert problem_for('coupang', default_discount('coupang')) is None


def test_쿠폰을_안_쓰는_마켓엔_기본값이_없다():
    """🔴 자리를 못 찾은 마켓에 기본값을 만들어 주면 안 나가는 값이 생긴다."""
    for mk in ('lotteon', 'eleven11', 'auction', 'gmarket'):
        assert default_discount(mk) is None


# ── 거부 위험 미리 알림 ───────────────────────────────────────

def test_100원이_비싼_상품이면_거부될_수_있다고_말한다():
    """라이브 실측 그대로 — 128,900원에 100원(0.07%)은 [CIE06] 로 거부됐다."""
    note = warn_for('coupang', {'value': 100, 'unitType': 'WON'}, 128900)
    assert note, '거부된 적 있는 조합인데 아무 말도 안 한다'
    assert '100' in note or '거부' in note


def test_실제로_통과한_조합엔_경고를_안_한다():
    """사장님 실쿠폰 128,900원 / 1,400원(1.09%)은 통과 중이다 — 겁주지 않는다."""
    assert warn_for('coupang', {'value': 1400, 'unitType': 'WON'}, 128900) is None


def test_싼_상품의_100원은_경고_안_한다():
    """5,000원짜리에 100원이면 2% — 통과한 비율보다 높다."""
    assert warn_for('coupang', {'value': 100, 'unitType': 'WON'}, 5000) is None


def test_판매가를_모르면_겁주지_않는다():
    """🔴 모르면 「모른다」 — 없는 근거로 경고하면 진짜 경고까지 무시하게 된다."""
    assert warn_for('coupang', {'value': 100, 'unitType': 'WON'}, None) is None


def test_경고는_막는_게_아니다():
    """warn 은 안내고, problem 이 막는 자리다. 둘을 섞으면 멀쩡한 쿠폰이 막힌다."""
    d = {'value': 100, 'unitType': 'WON'}
    assert warn_for('coupang', d, 128900) is not None      # 알린다
    assert problem_for('coupang', d) is None               # 막지는 않는다
