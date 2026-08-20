# -*- coding: utf-8 -*-
"""정책 복사 — 노션 「생성된 정책 복사기능」.

목적 = 「한 상품을 정책별로 다르게 가공해 여러 상품으로 올리기」.
🔴 붙은 상품은 복사하지 않는다 — 복사본이 같은 상품을 낚아채면 원본이 조용히 풀린다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM     # noqa: F401 — 테이블 등록
from lemouton.policy.fields import COMMON_KEY
from lemouton.policy.service import (
    PolicyError, applied_count, apply_to, create_policy, save_item, values_for,
)
from lemouton.sourcing.models import Model


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_값이_전부_복사된다(db):
    from lemouton.policy.copy import copy_policy
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    save_item(db, policy=p, market='coupang', item_key='price',
              config={'sourcing_rate': 32})

    c = copy_policy(db, policy=p)

    assert c.id != p.id
    assert values_for(db, c.id, COMMON_KEY) == {'price': {'sourcing_rate': 25}}
    assert values_for(db, c.id, 'coupang') == {'price': {'sourcing_rate': 32}}


def test_이름은_겹치지_않게_붙는다(db):
    from lemouton.policy.copy import copy_policy
    p = create_policy(db, name='르무통 기본')
    c1 = copy_policy(db, policy=p)
    c2 = copy_policy(db, policy=p)
    assert c1.name == '르무통 기본 (복사)'
    assert c2.name == '르무통 기본 (복사 2)'


def test_붙은_상품은_따라오지_않는다(db):
    from lemouton.policy.copy import copy_policy
    db.add(Model(model_code='M1', model_name_raw='M1', brand='르무통'))
    db.flush()
    p = create_policy(db, name='르무통 기본')
    apply_to(db, policy=p, model_codes=['M1'])

    c = copy_policy(db, policy=p)

    assert applied_count(db, p.id) == 1
    assert applied_count(db, c.id) == 0


def test_기본_정책_표시는_따라오지_않는다(db):
    from lemouton.policy.copy import copy_policy
    from lemouton.policy.service import toggle_default
    p = create_policy(db, name='르무통 기본')
    toggle_default(db, policy=p)

    c = copy_policy(db, policy=p)

    assert p.is_default == 1
    assert c.is_default == 0


def test_이름을_직접_줄_수_있다(db):
    from lemouton.policy.copy import copy_policy
    p = create_policy(db, name='르무통 기본')
    c = copy_policy(db, policy=p, name='르무통 프리미엄')
    assert c.name == '르무통 프리미엄'


def test_이미_있는_이름으로는_복사하지_못한다(db):
    from lemouton.policy.copy import copy_policy
    p = create_policy(db, name='르무통 기본')
    create_policy(db, name='르무통 프리미엄')
    with pytest.raises(PolicyError):
        copy_policy(db, policy=p, name='르무통 프리미엄')


def test_공통에서_받은_표시도_같이_복사된다(db):
    """복사본에서 「직접 고침」으로 잘못 뜨면 사장님이 다시 불러오게 된다."""
    from lemouton.policy.common_sync import market_summary, push_to_markets
    from lemouton.policy.copy import copy_policy
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    push_to_markets(db, policy=p, markets=['smartstore'])

    c = copy_policy(db, policy=p)

    assert market_summary(db, c.id)['smartstore']['state'] == 'common'
