# -*- coding: utf-8 -*-
"""수수료율 13% 맞추기 — 재기·고치기·되돌리기 가드.

사장님 확정 2026-08-02 — 「수수료율은 기본 다 13% 해놓고 내가 수정한다.
마켓별·카테고리별·제휴이벤트별로 전부 달라서 수기로 넣어야 한다.」

🔴 판매가가 움직이는 일이라 **재보기가 기본**이어야 한다. confirm 없이 고쳐지면
   사장님이 모르는 사이 라이브 판매가가 바뀐다.
"""
import pytest

from lemouton.pricing.fee_audit import (
    FEE_COLUMNS, apply_defaults, price_multiplier, restore, target_fee,
)

#: 사장님 확정 — 마켓별 실제 요율
#:   🔴 [2026-08-13 재확정] 롯데온 0.18 → **0.15** · 11번가 0.11 → **0.13**
#:     (롯데온 = 판매 13 + 유입 2 · 11번가 = 계약 11 + 가격비교 2)
OWNER = {'ss': 0.06, 'coupang': 0.1155, 'lotteon': 0.15,
         'eleven11': 0.13, 'auction': 0.15, 'gmarket': 0.15}


def test_목표는_마켓마다_다르다():
    """🔴 한 숫자로 통일하면 마켓마다 엉뚱한 값으로 맞춰진다.

    11번가 10% 는 **조건부**(1년 이내 계정)라 기본값이 아니다 — 기본은 13%.
    """
    for prefix, want in OWNER.items():
        assert target_fee(prefix) == want, f'{prefix} 목표가 {want} 가 아니다'


def test_여섯_마켓_수수료칸을_다_본다():
    """한 마켓이라도 빠지면 그 마켓만 옛 요율로 남는다 — 조용히."""
    assert set(FEE_COLUMNS) == {
        'ss_fee_rate', 'coupang_fee_rate', 'lotteon_fee_rate',
        'eleven11_fee_rate', 'auction_fee_rate', 'gmarket_fee_rate'}


def test_판매가_배수는_분모비다():
    """판매가 = 매입가 / (1 − 수수료율 − 마진율) → 배수는 매입가와 무관하다."""
    # 롯데온: 13% → 18%, 마진율 12.42%
    m = price_multiplier(0.13, 0.18, 0.1242)
    assert m == pytest.approx((1 - 0.13 - 0.1242) / (1 - 0.18 - 0.1242))
    assert m == pytest.approx(1.0718, abs=1e-4)      # 판매가 약 +7.2%
    # 11번가: 13% → 8% (내려간다)
    assert price_multiplier(0.13, 0.08, 0.1242) == pytest.approx(0.9372, abs=1e-4)


def test_성립하지_않는_조합은_지어내지_않는다():
    """수수료 + 마진이 100% 이상이면 판매가가 없다 — 숫자를 만들지 말고 None."""
    assert price_multiplier(0.5, 0.6, 0.5) is None
    assert price_multiplier(0.06, 0.18, 0.95) is None


class _Tpl:
    """PriceTemplate 흉내 — 칸 이름만 맞으면 된다."""

    def __init__(self, tid, **cols):
        self.id = tid
        self.name = f'T{tid}'
        for c in FEE_COLUMNS:
            setattr(self, c, cols.get(c))


class _Session:
    def __init__(self, rows):
        self._rows = rows

    def query(self, _model):
        return self

    def order_by(self, *_a):
        return self

    def all(self):
        return self._rows

    def get(self, _model, tid):
        return next((r for r in self._rows if r.id == tid), None)


def test_재보기가_기본이라_아무것도_안_고친다():
    """🔴 confirm 없이 값이 바뀌면 사장님 모르게 라이브 판매가가 움직인다."""
    t = _Tpl(1, ss_fee_rate=0.13, coupang_fee_rate=0.13)
    out = apply_defaults(_Session([t]), dry_run=True)
    assert out['dry_run'] is True
    assert out['changed'] == 2
    assert t.ss_fee_rate == 0.13, '재보기인데 값이 바뀌었다'
    assert t.coupang_fee_rate == 0.13


def test_고치면_13이_되고_이전_값을_돌려준다():
    t = _Tpl(1, ss_fee_rate=0.13, coupang_fee_rate=0.13, gmarket_fee_rate=0.15)
    out = apply_defaults(_Session([t]), dry_run=False)
    assert t.ss_fee_rate == OWNER['ss']
    assert t.coupang_fee_rate == OWNER['coupang']
    # 이미 맞는 칸(G마켓 15%)은 건드리지 않는다 — before 에도 안 들어간다
    assert t.gmarket_fee_rate == 0.15
    assert out['changed'] == 2
    assert {b['column'] for b in out['before']} == {'ss_fee_rate', 'coupang_fee_rate'}
    assert {b['to'] for b in out['before']} == {0.06, 0.1155}


def test_되돌리면_원래_값으로_돌아온다():
    t = _Tpl(1, ss_fee_rate=0.13, coupang_fee_rate=0.13)
    s = _Session([t])
    out = apply_defaults(s, dry_run=False)
    assert restore(s, out['before'])['restored'] == 2
    assert t.ss_fee_rate == 0.13
    assert t.coupang_fee_rate == 0.13


def test_값이_없는_칸은_만들지_않는다():
    """None = 「안 정함」. 여기에 13을 채우면 안 정한 것을 정한 것으로 바꾸는 셈이다."""
    t = _Tpl(1)                       # 전 칸 None
    out = apply_defaults(_Session([t]), dry_run=False)
    assert out['changed'] == 0
    assert all(getattr(t, c) is None for c in FEE_COLUMNS)
