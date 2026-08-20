# -*- coding: utf-8 -*-
"""「벌」 만들기·붙이기 — 「한 상품에 여러 정책」의 화면 뒤편.

🔴 이 파일이 지키는 것
   ① 벌을 하나 더 만들면 **옵션이 그대로 베껴진다** — 안 베끼면 빈 벌이라 마켓에 못 올라간다
   ② 벌 이름을 안 적으면 **정책 이름**으로 부른다 (벌을 가르는 건 정책이지 단품/세트가 아니다)
   ③ 「단품, 단품」 처럼 **구성 이름이 같아도** 벌이 둘로 선다
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


def _model(s, code='A'):
    from lemouton.sourcing.models import Model, Option
    s.add(Model(model_code=code, model_name_raw=code, brand='르무통'))
    for sku in ('SKU-1', 'SKU-2'):
        s.add(Option(canonical_sku=sku, model_code=code,
                     color_code='BK', size_code=sku[-1]))
    s.flush()


def _set_with_options(s, code='A', name='단품'):
    from lemouton.sets.models import ProductSet, SetProduct, SetOption
    ps = ProductSet(model_code=code, name=name)
    s.add(ps); s.flush()
    sp = SetProduct(set_id=ps.id, model_code=code, quantity=1)
    s.add(sp); s.flush()
    for i, sku in enumerate(('SKU-1', 'SKU-2')):
        s.add(SetOption(set_product_id=sp.id, canonical_sku=sku, sort_order=i))
    s.flush()
    return ps


def _policy(s, name):
    from lemouton.policy.service import create_policy
    p = create_policy(s, name=name)
    s.flush()
    return p


def test_벌을_더_만들면_옵션이_그대로_베껴진다(s):
    """🔴 안 베끼면 빈 벌이라 마켓에 못 올라간다 — 화면 기본값이 「똑같이」인 이유."""
    from lemouton.policy.bundles import add_bundle
    from lemouton.sets.models import SetOption, SetProduct
    _model(s)
    _set_with_options(s)
    p2 = _policy(s, '여름 특가')

    got = add_bundle(s, model_code='A', policy_id=p2.id)

    assert got['copied_options'] == 2, '옵션을 안 베꼈다 — 빈 벌이 된다'
    sp = s.query(SetProduct).filter_by(set_id=got['set_id']).one()
    skus = {o.canonical_sku for o in s.query(SetOption).filter_by(set_product_id=sp.id)}
    assert skus == {'SKU-1', 'SKU-2'}


def test_이름을_안_적으면_정책_이름으로_부른다(s):
    from lemouton.policy.bundles import add_bundle
    _model(s)
    _set_with_options(s)
    got = add_bundle(s, model_code='A', policy_id=_policy(s, '여름 특가').id)
    assert got['name'] == '여름 특가'


def test_이름을_적으면_그_이름을_쓴다(s):
    from lemouton.policy.bundles import add_bundle
    _model(s)
    _set_with_options(s)
    got = add_bundle(s, model_code='A', policy_id=_policy(s, '여름 특가').id,
                     name='세트B')
    assert got['name'] == '세트B'


def test_구성_이름이_같아도_벌이_둘로_선다(s):
    """★사장님 지적 — 「단품, 단품」 도 된다. 벌을 가르는 건 정책이다."""
    from lemouton.policy.bundles import add_bundle, bundles_of
    _model(s)
    first = _set_with_options(s, name='단품')
    from lemouton.policy.models import SetPolicyLink
    p1, p2 = _policy(s, '기본'), _policy(s, '메이트')
    s.add(SetPolicyLink(set_id=first.id, policy_id=p1.id)); s.flush()

    add_bundle(s, model_code='A', policy_id=p2.id, name='단품')
    s.flush()

    got = bundles_of(s, ['A'])['A']
    assert len(got) == 2
    assert [b['name'] for b in got] == ['단품', '단품'], '구성 이름이 같아도 둘이어야 한다'
    assert {b['policy'] for b in got} == {'기본', '메이트'}, '정책으로 갈린다'


def test_벌이_없는_상품은_빈_목록(s):
    from lemouton.policy.bundles import bundles_of
    _model(s)
    assert bundles_of(s, ['A']) == {}


def test_고른_벌에만_정책이_붙는다(s):
    from lemouton.policy.bundles import attach_to_sets, bundles_of
    _model(s)
    a = _set_with_options(s, name='단품')
    b = _set_with_options(s, name='세트')
    pol = _policy(s, '기본')

    n = attach_to_sets(s, policy_id=pol.id, set_ids=[a.id])
    s.flush()

    assert n == 1
    got = {x['set_id']: x['policy'] for x in bundles_of(s, ['A'])['A']}
    assert got[a.id] == '기본'
    assert got[b.id] is None, '안 고른 벌에 붙으면 안 된다'


def test_이미_붙어_있으면_갈아_끼운다(s):
    from lemouton.policy.bundles import attach_to_sets, bundles_of
    _model(s)
    a = _set_with_options(s)
    old, new = _policy(s, '옛것'), _policy(s, '새것')
    attach_to_sets(s, policy_id=old.id, set_ids=[a.id])
    attach_to_sets(s, policy_id=new.id, set_ids=[a.id])
    s.flush()
    assert bundles_of(s, ['A'])['A'][0]['policy'] == '새것'


def test_없는_벌은_막는다(s):
    from lemouton.policy.bundles import attach_to_sets
    from lemouton.policy.service import PolicyError
    _model(s)
    pol = _policy(s, '기본')
    with pytest.raises(PolicyError):
        attach_to_sets(s, policy_id=pol.id, set_ids=[99999])


def test_없는_정책으로_벌을_못_만든다(s):
    from lemouton.policy.bundles import add_bundle
    from lemouton.policy.service import PolicyError
    _model(s)
    _set_with_options(s)
    with pytest.raises(PolicyError):
        add_bundle(s, model_code='A', policy_id=99999)


def test_벌이_하나도_없어도_만들어진다(s):
    """구성이 0개인 상품(라이브 89개)에서 처음 벌을 만드는 경우."""
    from lemouton.policy.bundles import add_bundle
    _model(s)
    got = add_bundle(s, model_code='A', policy_id=_policy(s, '기본').id)
    assert got['copied_options'] == 0 and got['copied_from'] is None
    assert got['set_id']


def test_만든_벌이_그_정책으로_값을_낸다(s):
    """★끝까지 이어지나 — 벌을 만들면 그 벌의 가격이 새 정책으로 계산돼야 한다."""
    from lemouton.policy.as_template import policy_template_for_set
    from lemouton.policy.bundles import add_bundle
    from lemouton.policy.service import save_item
    from lemouton.pricing.unified import compute_market_price
    from lemouton.templates.models import PriceTemplate

    tpl = PriceTemplate(name='기본', pricing_policy='cheapest',
                        price_source_priority='template')
    for m in ('ss', 'coupang', 'lotteon', 'eleven11', 'auction', 'gmarket'):
        setattr(tpl, f'{m}_pricing_policy', 'cheapest')
        setattr(tpl, f'{m}_unify_rule', 'max')
        setattr(tpl, f'{m}_rate_sourcing', 0.0945)
        setattr(tpl, f'{m}_fee_rate', 0.06)
    s.add(tpl); s.flush()
    _model(s)
    _set_with_options(s)

    pol = _policy(s, '여름 특가')
    save_item(s, policy=pol, market='smartstore', item_key='price',
              config={'sourcing_mode': 'margin_rate', 'sourcing_rate': 30.0})
    got = add_bundle(s, model_code='A', policy_id=pol.id)
    s.flush()

    shim = policy_template_for_set(s, got['set_id'], fallback=tpl)
    새값 = compute_market_price(shim, 'ss', 'sourcing', 100000).final_price
    옛값 = compute_market_price(tpl, 'ss', 'sourcing', 100000).final_price
    assert 새값 > 옛값, f'새 벌이 새 정책 값을 안 쓴다 ({옛값} → {새값})'


def test_정책이_없는_벌도_화면에_남는다(s, monkeypatch):
    """🔴 라이브가 잡아낸 결함 — 「벌 2개·정책 0개」 상품이 예전 모드로 빠져
       벌 하나만 보였다. 정책 유무로 거르면 사장님이 「벌이 하나뿐」으로 오해한다.
    """
    from lemouton.policy.bundles import bundles_of
    _model(s)
    a = _set_with_options(s, name='구성A')
    b = _set_with_options(s, name='구성B')

    got = bundles_of(s, ['A'])['A']

    assert len(got) == 2, '정책이 없어도 벌은 둘 다 나와야 한다'
    assert {x['policy_id'] for x in got} == {None}
    assert sorted(x['name'] for x in got) == ['구성A', '구성B']
