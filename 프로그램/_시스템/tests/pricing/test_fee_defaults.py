# -*- coding: utf-8 -*-
"""마켓별 수수료 기준 — 화면에서 고칠 수 있는 표.

사장님 확정 2026-08-02:
  「11번가는 기본 11% 설정하고, 1년 이내 계정 체크버튼 만들어줘. 체크하면 8% 되도록.
   다만, 우리 마켓 정책 언제든 변경될 수 있으니 기본값과 체크하면 X% 이런것들도
   수기로 조정가능하도록 해줘.」
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.pricing import fee_defaults as FD


@pytest.fixture()
def db():
    from shared.db import Base
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng, tables=[FD.MarketFeeDefault.__table__])
    s = sessionmaker(bind=eng)()
    FD.invalidate()
    yield s
    s.close()
    FD.invalidate()


# ── 씨앗 ────────────────────────────────────────────────────────────────

def test_사장님이_불러준_값이_씨앗이다():
    want = {'smartstore': 6.0, 'coupang': 11.55, 'lotteon': 18.0,
            'eleven11': 11.0, 'auction': 15.0, 'gmarket': 15.0}
    for market, pct in want.items():
        assert FD.SEED[market]['base_pct'] == pct, f'{market} 씨앗이 {pct} 가 아니다'


def test_11번가만_조건부_요율을_가진다():
    """1년 이내 계정이면 8% — 지나면 11%."""
    assert FD.SEED['eleven11']['alt_label'] == '1년 이내 계정'
    assert FD.SEED['eleven11']['alt_pct'] == 8.0
    for m in ('smartstore', 'coupang', 'lotteon', 'auction', 'gmarket'):
        assert not FD.SEED[m]['alt_label'], f'{m} 에 조건이 붙었다'


def test_처음_열면_씨앗이_심긴다(db):
    got = FD.load(db)
    assert set(got) == set(FD.SEED)
    assert got['eleven11']['base_pct'] == 11.0
    assert got['eleven11']['alt_pct'] == 8.0


# ── 고치기 ──────────────────────────────────────────────────────────────

def test_사장님이_고친_값이_이긴다(db):
    FD.load(db)
    FD.save(db, 'eleven11', base_pct=12.5, alt_label='1년 이내 계정', alt_pct=9)
    db.commit()
    FD.invalidate()
    got = FD.load(db)
    assert got['eleven11']['base_pct'] == 12.5
    assert got['eleven11']['alt_pct'] == 9.0


def test_조건_이름을_지우면_조건_요율도_사라진다(db):
    """이름 없는 조건은 화면에 못 그린다 — 값만 남으면 아무도 못 쓰는 숫자가 된다."""
    FD.load(db)
    FD.save(db, 'eleven11', base_pct=11, alt_label='', alt_pct=8)
    db.commit()
    FD.invalidate()
    assert FD.load(db)['eleven11']['alt_pct'] is None


@pytest.mark.parametrize('bad', [0, -1, 100, 100.1, None, True, '11'])
def test_말이_안_되는_기본요율은_막는다(db, bad):
    """🔴 0% 면 수수료를 안 뗀 것으로 계산돼 판매가가 싸게 나간다(금전 손실).
    100% 이상이면 성립하는 판매가가 아예 없다."""
    FD.load(db)
    with pytest.raises(ValueError):
        FD.save(db, 'eleven11', base_pct=bad)


def test_조건_이름만_있고_요율이_없으면_막는다(db):
    FD.load(db)
    with pytest.raises(ValueError):
        FD.save(db, 'eleven11', base_pct=11, alt_label='1년 이내 계정', alt_pct=None)


def test_모르는_마켓은_거부한다(db):
    FD.load(db)
    with pytest.raises(ValueError):
        FD.save(db, '없는마켓', base_pct=10)


# ── 표기 ────────────────────────────────────────────────────────────────

def test_정수는_소수점을_안_붙인다():
    """「6.0%」로 보이면 소수 자리가 뜻이 있는 값처럼 읽힌다."""
    assert FD.pretty(6.0) == 6
    assert FD.pretty(15.0) == 15
    assert FD.pretty(11.55) == 11.55      # 진짜 소수는 남긴다
    assert FD.pretty(None) is None


# ── 계산이 이 표를 본다 ─────────────────────────────────────────────────

def test_엔진이_표를_읽는다(db, monkeypatch):
    """🔴 표를 고쳤는데 계산이 옛 값을 쓰면 화면과 계산이 갈린다."""
    from lemouton.pricing import unified
    FD.load(db)
    FD.save(db, 'eleven11', base_pct=9.5)
    db.commit()
    FD.invalidate()
    monkeypatch.setattr(FD, 'load', lambda session=None: {
        'eleven11': {'base_pct': 9.5, 'alt_label': '', 'alt_pct': None}})
    assert unified.default_fee_rate('eleven11') == pytest.approx(0.095)


def test_표를_못_읽어도_계산은_멈추지_않는다(monkeypatch):
    """🔴 DB 가 잠깐 안 되더라도 판매가 계산이 죽으면 안 된다 — 방어선이 있어야 한다."""
    from lemouton.pricing import unified

    def boom(session=None):
        raise RuntimeError('DB 없음')

    monkeypatch.setattr(FD, 'base_pct', lambda m: (_ for _ in ()).throw(RuntimeError()))
    assert unified.default_fee_rate('eleven11') == 0.11
    assert unified.default_fee_rate('smartstore') == 0.06
