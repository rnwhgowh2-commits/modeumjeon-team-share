# -*- coding: utf-8 -*-
"""정책 쿠폰 값을 바꿀 때 뜨는 확인창 (사장님 확정 **B5** + 전체 선택/해제).

■ 사장님 확정
    「몇 개가 바뀌고 몇 개는 안 건드리는지 **먼저 보여 주고** 누르게 한다.」
    「전부가 아니라 **고른 상품만** 다시 건다. 전체 선택은 다시 누르면 전체 해제.」

■ 🔴 이 시험이 지키는 것
  1. **비정책 상품은 목록에서 갈라 놓는다.** 정책을 바꿔도 안 따라가는 상품이라,
     같이 세어 보여 주면 사장님이 12개가 바뀌는 줄 안다(실제론 9개).
  2. **고른 것만** 걸린다. 안 고른 상품은 대기열에 안 들어간다.
  3. 지금 값과 바뀔 값을 **둘 다** 준다 — 확인창이 「−100 → −250」을 보여줘야 한다.
  4. 정책에 즉시할인이 없으면 **아예 안 묻는다**(걸 것이 없다).
"""
import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

for _m in ("lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
           "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
           "lemouton.uploader.models", "lemouton.templates.models",
           "lemouton.inventory.models", "lemouton.sources.models",
           "lemouton.multitenancy.models", "lemouton.audit.models",
           "lemouton.mapping.models", "lemouton.sets.models"):
    try:
        __import__(_m)
    except ImportError:
        pass

from lemouton.policy import coupon_service as CS               # noqa: E402
from lemouton.sets.models import (ProductSet, SetChannel,      # noqa: E402
                                  SetChannelOption)

_NOW = _dt.datetime(2026, 8, 13, 15, 0, 0)


@pytest.fixture
def db():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


@pytest.fixture
def world(db):
    """정책 1개 + 그 정책이 물린 상품 3개(그중 1개는 비정책)."""
    from lemouton.policy.models import SetPolicyLink
    from lemouton.policy.service import create_policy, save_values
    from lemouton.sourcing.models import Model

    p = create_policy(db, name='할인정책')
    save_values(db, policy=p, market='coupang',
                values={'price': {'discount_unit': 'WON', 'discount_value': 250}})
    made = []
    for i, (code, own) in enumerate([('A', False), ('B', False), ('C', True)]):
        db.add(Model(model_code=code, model_name_raw=f'상품{code}'))
        ps = ProductSet(model_code=code, name='기본')
        db.add(ps)
        db.flush()
        fields = {CS.COUPON_KEY: {'ok': True, 'coupon_id': 100 + i, 'value': 100,
                                  'ends_at': '2027-12-31 23:59:59'}}
        if own:
            fields[CS.OVERRIDE_KEY] = {'mode': 'own', 'value': 300}
        ch = SetChannel(set_id=ps.id, market='coupang', account_key='세소쿠팡',
                        market_product_id=str(900 + i), status='linked',
                        api_fields=fields)
        db.add(ch)
        db.flush()
        db.add(SetChannelOption(channel_id=ch.id, canonical_sku=f'{code}-1',
                                market_option_id=str(1000 + i), status='matched',
                                mkt_price=128900))
        db.add(SetPolicyLink(set_id=ps.id, policy_id=p.id))
        made.append(ch)
    db.commit()
    return {'policy_id': p.id, 'channels': made}


# ── ① 확인창이 무엇을 보여 주나 ──────────────────────────────

def test_바뀔_것과_안_건드릴_것을_갈라_준다(db, world):
    plan = CS.coupon_plan(db, world['policy_id'])
    assert len(plan['will']) == 2, '비정책 상품까지 바뀔 것으로 셌다'
    assert len(plan['skip']) == 1
    assert plan['next_value'] == 250, '바뀔 값을 안 알려 준다'


def test_지금_값과_바뀔_값을_둘_다_준다(db, world):
    """확인창이 「−100 → −250」을 보여 주려면 둘 다 있어야 한다."""
    plan = CS.coupon_plan(db, world['policy_id'])
    row = plan['will'][0]
    assert row['now'] == 100
    assert row['next'] == 250
    assert row['name'], '상품 이름이 없으면 어느 상품인지 모른다'
    assert row['channel_id']


def test_안_건드리는_줄은_왜인지_말한다(db, world):
    plan = CS.coupon_plan(db, world['policy_id'])
    skip = plan['skip'][0]
    assert skip['now'] == 300, '비정책 상품의 지금 값이 틀렸다'
    assert '비정책' in skip['reason']


def test_즉시할인이_없는_정책은_아예_안_묻는다(db):
    """걸 것이 없는데 확인창을 띄우면 사장님이 「무엇을 하는 거지」가 된다."""
    from lemouton.policy.service import create_policy
    p = create_policy(db, name='할인없음')
    db.commit()
    plan = CS.coupon_plan(db, p.id)
    assert plan['will'] == [] and plan['skip'] == []
    assert '즉시할인' in plan['message']


# ── ② 고른 것만 걸린다 ──────────────────────────────────────

def test_고른_상품만_대기열에_들어간다(db, world):
    """🔴 전부가 아니라 **고른 것만**. 안 고른 상품이 들어가면 사장님이 안 시킨 일이 난다."""
    plan = CS.coupon_plan(db, world['policy_id'])
    골랐다 = [plan['will'][0]['channel_id']]
    out = CS.apply_coupon_plan(db, world['policy_id'], channel_ids=골랐다, now=_NOW)
    assert out['queued'] == 1
    ids = [c.id for c in CS.pending_requests(db)]
    assert ids == 골랐다, f'고른 것 말고 딴 게 들어갔다: {ids}'


def test_아무것도_안_고르면_아무것도_안_한다(db, world):
    out = CS.apply_coupon_plan(db, world['policy_id'], channel_ids=[], now=_NOW)
    assert out['queued'] == 0
    assert CS.pending_requests(db) == []


def test_비정책_상품을_골라도_안_건드린다(db, world):
    """🔴 목록에서 갈라 놨는데 골라서 보내면 그 방어가 무너진다."""
    plan = CS.coupon_plan(db, world['policy_id'])
    벗어남 = plan['skip'][0]['channel_id']
    out = CS.apply_coupon_plan(db, world['policy_id'], channel_ids=[벗어남], now=_NOW)
    assert out['queued'] == 0
    assert CS.pending_requests(db) == []
