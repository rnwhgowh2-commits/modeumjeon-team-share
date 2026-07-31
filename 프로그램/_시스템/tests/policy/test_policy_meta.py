# -*- coding: utf-8 -*-
"""정책의 브랜드 · 내보낼 마켓.

브랜드 = 노션 「브랜드별로 정책분류」. 정책이 늘면 목록에서 못 찾는다.
내보낼 마켓 = 노션 「상세 보기 전에 마켓별 토글 활성화(전체선택 포함)」.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM     # noqa: F401 — 테이블 등록
from lemouton.policy.service import PolicyError, create_policy


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


# ── 브랜드 ──────────────────────────────────────────────────────────────

def test_브랜드는_안_정해도_된다(db):
    p = create_policy(db, name='르무통 기본')
    assert p.brand is None, '브랜드 없는 정책은 「브랜드 없음」으로 모인다'


def test_브랜드를_정할_수_있다(db):
    p = create_policy(db, name='르무통 기본', brand='르무통')
    assert p.brand == '르무통'


def test_브랜드_목록은_개수까지_준다(db):
    from lemouton.policy.service import brand_counts
    create_policy(db, name='르무통 기본', brand='르무통')
    create_policy(db, name='르무통 프리미엄', brand='르무통')
    create_policy(db, name='나이키 기본', brand='나이키')
    create_policy(db, name='TEST')

    assert brand_counts(db) == [('르무통', 2), ('나이키', 1), (None, 1)]


def test_지운_정책은_브랜드_수에서_빠진다(db):
    from datetime import datetime
    from lemouton.policy.service import brand_counts
    p = create_policy(db, name='르무통 기본', brand='르무통')
    create_policy(db, name='나이키 기본', brand='나이키')
    p.deleted_at = datetime.now()
    db.flush()

    assert brand_counts(db) == [('나이키', 1)]


# ── 내보낼 마켓 ─────────────────────────────────────────────────────────

def test_처음에는_모든_마켓이_켜져_있다(db):
    from lemouton.policy.fields import MARKET_KEYS
    from lemouton.policy.service import enabled_markets
    p = create_policy(db, name='르무통 기본')
    assert enabled_markets(db, p) == MARKET_KEYS


def test_마켓을_끌_수_있다(db):
    from lemouton.policy.service import enabled_markets, set_enabled_markets
    p = create_policy(db, name='르무통 기본')
    set_enabled_markets(db, policy=p, markets=['smartstore', 'coupang'])
    assert enabled_markets(db, p) == ['smartstore', 'coupang']


def test_모르는_마켓은_켤_수_없다(db):
    from lemouton.policy.service import set_enabled_markets
    p = create_policy(db, name='르무통 기본')
    with pytest.raises(PolicyError):
        set_enabled_markets(db, policy=p, markets=['없는마켓'])


def test_전부_끌_수_있다(db):
    """전부 끄면 아무 데도 안 나간다 — 화면이 그렇게 말해야 한다."""
    from lemouton.policy.service import enabled_markets, set_enabled_markets
    p = create_policy(db, name='르무통 기본')
    set_enabled_markets(db, policy=p, markets=[])
    assert enabled_markets(db, p) == []


def test_켜진_순서는_화면_순서를_따른다(db):
    """거꾸로 넣어도 화면 탭 순서(스스·쿠팡·G마켓…)로 돌아온다."""
    from lemouton.policy.service import enabled_markets, set_enabled_markets
    p = create_policy(db, name='르무통 기본')
    set_enabled_markets(db, policy=p, markets=['coupang', 'smartstore'])
    assert enabled_markets(db, p) == ['smartstore', 'coupang']


def test_값이_깨져_있으면_전부_켜진_것으로_본다(db):
    """읽다 실패했다고 전송을 멈추면 안 된다 — 안전한 쪽은 「켜짐」이다."""
    from lemouton.policy.fields import MARKET_KEYS
    from lemouton.policy.service import enabled_markets
    p = create_policy(db, name='르무통 기본')
    p.enabled_markets = '{망가진 값'
    db.flush()
    assert enabled_markets(db, p) == MARKET_KEYS
