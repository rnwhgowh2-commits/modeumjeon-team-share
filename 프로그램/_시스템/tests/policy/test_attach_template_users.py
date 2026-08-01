# -*- coding: utf-8 -*-
"""옮긴 정책을 「그 템플릿을 쓰던 상품」에 붙이기.

🔴 왜 이 규칙인가:
   옮기기만 하면 정책은 아무 상품에도 안 붙어 **아무 일도 안 한다**.
   그렇다고 아무 상품에나 붙이면, 그 상품이 쓰던 템플릿과 값이 달라 가격이 흔들린다.
   **같은 템플릿을 쓰던 상품에만** 붙여야 값이 같아 가격이 안 바뀐다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base


@pytest.fixture()
def s():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng)()
    yield sess
    sess.close()


def _model(s, code, tpl_id):
    from lemouton.sourcing.models import Model
    m = Model(model_code=code, model_name_raw=code, brand='르무통',
              price_template_id=tpl_id)
    s.add(m)
    return m


def _policy(s, name):
    from lemouton.policy.service import create_policy
    p = create_policy(s, name=name)
    s.flush()
    return p


def test_템플릿_쓰던_상품에만_붙는다(s):
    from lemouton.policy.migrate_from_template import attach_to_template_users
    _model(s, 'A', 7); _model(s, 'B', 7)
    _model(s, 'C', 9)                       # 다른 템플릿 — 붙으면 안 된다
    p = _policy(s, '옮긴 정책')
    s.flush()

    got = attach_to_template_users(s, template_id=7, policy_id=p.id)

    assert got['attached'] == 2
    assert sorted(got['codes']) == ['A', 'B']
    from lemouton.policy.models import BundlePolicyLink
    assert s.query(BundlePolicyLink).filter_by(model_code='C').first() is None


def test_이미_다른_정책이_붙었으면_안_건드린다(s):
    """사장님이 손으로 붙인 것을 말없이 갈아 끼우면 안 된다."""
    from lemouton.policy.migrate_from_template import attach_to_template_users
    from lemouton.policy.models import BundlePolicyLink
    _model(s, 'A', 7); _model(s, 'B', 7)
    mine, other = _policy(s, '옮긴 정책'), _policy(s, '손으로 만든 정책')
    s.add(BundlePolicyLink(model_code='B', policy_id=other.id))
    s.flush()

    got = attach_to_template_users(s, template_id=7, policy_id=mine.id)

    assert got['attached'] == 1 and got['skipped'] == 1
    kept = s.query(BundlePolicyLink).filter_by(model_code='B').one()
    assert kept.policy_id == other.id       # 그대로 남아 있다


def test_두_번_해도_하나만_붙는다(s):
    """멱등 — 실수로 두 번 눌러도 탈이 없어야 한다."""
    from lemouton.policy.migrate_from_template import attach_to_template_users
    from lemouton.policy.models import BundlePolicyLink
    _model(s, 'A', 7)
    p = _policy(s, '옮긴 정책')
    s.flush()

    attach_to_template_users(s, template_id=7, policy_id=p.id)
    s.commit()
    got = attach_to_template_users(s, template_id=7, policy_id=p.id)

    assert got['attached'] == 1 and got['skipped'] == 0
    assert s.query(BundlePolicyLink).count() == 1


def test_쓰는_상품이_없으면_아무것도_안_한다(s):
    from lemouton.policy.migrate_from_template import attach_to_template_users
    p = _policy(s, '옮긴 정책')
    s.flush()
    assert attach_to_template_users(s, template_id=7, policy_id=p.id) == {
        'attached': 0, 'skipped': 0, 'codes': []}


def test_붙인_뒤_가격이_그대로다(s):
    """★핵심 — 붙였을 때 그 상품의 판매가가 템플릿 때와 한 원도 다르지 않아야 한다."""
    from lemouton.policy.as_template import policy_template_for_model
    from lemouton.policy.migrate_from_template import attach_to_template_users, migrate_template
    from lemouton.pricing.unified import compute_market_price
    from lemouton.templates.models import PriceTemplate

    tpl = PriceTemplate(name='기본', pricing_policy='cheapest',
                        price_source_priority='template')
    for m in ('ss', 'coupang', 'lotteon', 'eleven11', 'auction', 'gmarket'):
        setattr(tpl, f'{m}_pricing_policy', 'cheapest')
        setattr(tpl, f'{m}_unify_rule', 'max')
        setattr(tpl, f'{m}_rate_sourcing', 0.0945)
        setattr(tpl, f'{m}_fee_rate', 0.06)
        setattr(tpl, f'{m}_delivery_fee', 3000)
    s.add(tpl); s.flush()

    _model(s, 'A', tpl.id)
    got = migrate_template(s, tpl=tpl)
    attach_to_template_users(s, template_id=tpl.id, policy_id=got['policy_id'])
    s.commit()

    shim = policy_template_for_model(s, 'A', fallback=tpl)
    assert shim is not None, '붙였는데 정책이 안 잡힌다'
    for prefix in ('ss', 'coupang', 'lotteon', 'eleven11', 'auction', 'gmarket'):
        for purchase in (50000, 92400, 150000):
            a = compute_market_price(tpl, prefix, 'sourcing', purchase).final_price
            b = compute_market_price(shim, prefix, 'sourcing', purchase).final_price
            assert a == b, f'{prefix} 매입가 {purchase}: {a} → {b} 로 바뀐다'
