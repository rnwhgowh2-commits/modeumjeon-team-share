# -*- coding: utf-8 -*-
"""마켓별 정책 — 값 저장 · 채움 현황 · 상품 적용.

🔴 이 파일이 지키는 한 가지: **빈칸은 0 이 아니다.**
   수수료율이 비었는데 0 으로 읽히면 마진이 부풀어 그대로 마켓에 나간다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM     # noqa: F401 — 테이블 등록
from lemouton.policy.fields import MARKET_KEYS, fields_for
from lemouton.policy.models import BundlePolicyLink, MarketPolicyValue
from lemouton.policy.service import (
    PolicyError, applied_count, apply_to, create_policy, policy_of, readiness,
    save_values, set_default, values_for,
)
from lemouton.sourcing.models import Model


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _models(s, *codes):
    for c in codes:
        s.add(Model(model_code=c, model_name_raw=c, brand='르무통'))
    s.flush()


# ── 만들기 ────────────────────────────────────────────────────────────────

def test_이름이_없으면_막는다(db):
    with pytest.raises(PolicyError, match='이름'):
        create_policy(db, name='   ')


def test_같은_이름은_두_번_못_만든다(db):
    create_policy(db, name='르무통 기본')
    with pytest.raises(PolicyError, match='이미 있어요'):
        create_policy(db, name='르무통 기본')


# ── 값 ────────────────────────────────────────────────────────────────────

def test_저장하고_다시_읽힌다(db):
    p = create_policy(db, name='기본')
    save_values(db, policy=p, market='coupang',
                values={'fee_rate': '10.5', 'margin_rate': '20'})
    got = values_for(db, p.id, 'coupang')
    assert got['fee_rate'] == '10.5' and got['margin_rate'] == '20'


def test_마켓마다_따로_저장된다(db):
    p = create_policy(db, name='기본')
    save_values(db, policy=p, market='coupang', values={'fee_rate': '10'})
    save_values(db, policy=p, market='smartstore', values={'fee_rate': '5'})
    assert values_for(db, p.id, 'coupang')['fee_rate'] == '10'
    assert values_for(db, p.id, 'smartstore')['fee_rate'] == '5'


def test_빈칸은_0_이_아니라_없는_것이다(db):
    """★ 이 프로그램에서 가장 위험한 오해 — 빈칸을 0 으로 읽으면 가격이 틀린다."""
    p = create_policy(db, name='기본')
    save_values(db, policy=p, market='coupang', values={'fee_rate': '', 'margin_rate': '  '})
    got = values_for(db, p.id, 'coupang')
    assert 'fee_rate' not in got, '빈칸이 값으로 남았다'
    assert got.get('fee_rate') is None


def test_채웠다가_비우면_지워진다(db):
    p = create_policy(db, name='기본')
    save_values(db, policy=p, market='coupang', values={'fee_rate': '10'})
    save_values(db, policy=p, market='coupang', values={'fee_rate': ''})
    assert values_for(db, p.id, 'coupang') == {}
    assert db.query(MarketPolicyValue).count() == 0


def test_모르는_항목은_막는다(db):
    p = create_policy(db, name='기본')
    with pytest.raises(PolicyError, match='모르는 항목'):
        save_values(db, policy=p, market='coupang', values={'없는항목': '1'})


def test_모르는_마켓은_막는다(db):
    p = create_policy(db, name='기본')
    with pytest.raises(PolicyError, match='모르는 마켓'):
        save_values(db, policy=p, market='11st_wrong', values={'fee_rate': '1'})


# ── 채움 현황 ─────────────────────────────────────────────────────────────

def test_수수료율_마진율이_다_있어야_가격을_쓸_수_있다(db):
    p = create_policy(db, name='기본')
    assert readiness(db, p.id)['coupang']['price_ready'] is False
    save_values(db, policy=p, market='coupang', values={'fee_rate': '10'})
    assert readiness(db, p.id)['coupang']['price_ready'] is False, '마진율이 아직 없다'
    save_values(db, policy=p, market='coupang', values={'fee_rate': '10', 'margin_rate': '20'})
    rd = readiness(db, p.id)['coupang']
    assert rd['price_ready'] is True and rd['missing'] == []


def test_한_마켓만_채워도_다른_마켓은_그대로_못_쓴다(db):
    p = create_policy(db, name='기본')
    save_values(db, policy=p, market='coupang',
                values={'fee_rate': '10', 'margin_rate': '20'})
    rd = readiness(db, p.id)
    assert rd['coupang']['price_ready'] is True
    assert all(not rd[m]['price_ready'] for m in MARKET_KEYS if m != 'coupang')


# ── 항목표 ────────────────────────────────────────────────────────────────

def test_그_마켓에만_있는_항목은_다른_마켓에_안_나온다(db):
    cp = {f['key'] for g in fields_for('coupang') for f in g['fields']}
    ss = {f['key'] for g in fields_for('smartstore') for f in g['fields']}
    gm = {f['key'] for g in fields_for('gmarket') for f in g['fields']}
    assert 'max_per_person' in cp and 'max_per_person' not in ss   # 쿠팡 전용
    assert 'size_price_unify' in ss and 'size_price_unify' not in cp  # 스스 전용
    assert 'site_discount' in gm and 'site_discount' not in cp     # G마켓·롯데온만


# ── 상품 적용 ─────────────────────────────────────────────────────────────

def test_고른_상품에_붙는다(db):
    _models(db, 'A', 'B', 'C')
    p = create_policy(db, name='기본')
    assert apply_to(db, policy=p, model_codes=['A', 'B']) == 2
    assert policy_of(db, 'A').id == p.id
    assert policy_of(db, 'C') is None
    assert applied_count(db, p.id) == 2


def test_다시_붙이면_갈아끼워진다(db):
    """상품 하나에 정책 하나 — 두 개가 붙으면 어느 쪽이 진짜인지 알 수 없다."""
    _models(db, 'A')
    p1 = create_policy(db, name='정책1')
    p2 = create_policy(db, name='정책2')
    apply_to(db, policy=p1, model_codes=['A'])
    apply_to(db, policy=p2, model_codes=['A'])
    assert policy_of(db, 'A').id == p2.id
    assert db.query(BundlePolicyLink).filter_by(model_code='A').count() == 1


def test_같은_상품을_여러_번_골라도_한_번만(db):
    _models(db, 'A')
    p = create_policy(db, name='기본')
    assert apply_to(db, policy=p, model_codes=['A', 'A', 'A']) == 1


def test_없는_상품은_막는다(db):
    _models(db, 'A')
    p = create_policy(db, name='기본')
    with pytest.raises(PolicyError, match='없는 상품'):
        apply_to(db, policy=p, model_codes=['A', '없는코드'])


def test_하나도_안_고르면_막는다(db):
    p = create_policy(db, name='기본')
    with pytest.raises(PolicyError, match='하나도'):
        apply_to(db, policy=p, model_codes=[])


def test_기본_정책은_하나뿐이다(db):
    p1 = create_policy(db, name='정책1')
    p2 = create_policy(db, name='정책2')
    set_default(db, policy=p1)
    set_default(db, policy=p2)
    assert p1.is_default == 0 and p2.is_default == 1
