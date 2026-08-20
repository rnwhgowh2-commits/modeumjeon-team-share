# -*- coding: utf-8 -*-
"""「한 상품에 여러 정책」 — 정책을 **구성(벌)** 에 붙인다.

사장님 확정 (2026-08-02): 같은 마켓에 여러 벌을 올리고, 재고는 연동한다.

🔴 이 파일이 지키는 두 가지
   ① **되받기** — 구성에 정책을 안 붙였으면 상품 정책, 그것도 없으면 쓰던 템플릿.
      이게 깨지면 정책을 안 붙인 구성의 가격이 조용히 바뀐다.
   ② **갈라짐** — 구성마다 정책이 다르면 마켓에 나가는 값도 갈려야 한다.
      안 갈리면 기능이 있는 척만 하는 것이다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base

MARKETS = ('ss', 'coupang', 'lotteon', 'eleven11', 'auction', 'gmarket')


@pytest.fixture()
def s():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng)()
    yield sess
    sess.close()


def _tpl(s, name='기본', rate=0.0945):
    from lemouton.templates.models import PriceTemplate
    t = PriceTemplate(name=name, pricing_policy='cheapest',
                      price_source_priority='template')
    for m in MARKETS:
        setattr(t, f'{m}_pricing_policy', 'cheapest')
        setattr(t, f'{m}_unify_rule', 'max')
        setattr(t, f'{m}_rate_sourcing', rate)
        setattr(t, f'{m}_fee_rate', 0.06)
        setattr(t, f'{m}_delivery_fee', 3000)
    s.add(t); s.flush()
    return t


def _model(s, code, tpl_id=None):
    from lemouton.sourcing.models import Model
    m = Model(model_code=code, model_name_raw=code, brand='르무통',
              price_template_id=tpl_id)
    s.add(m); s.flush()
    return m


def _set(s, code, name):
    from lemouton.sets.models import ProductSet
    ps = ProductSet(model_code=code, name=name)
    s.add(ps); s.flush()
    return ps


def _policy_with_rate(s, name, rate_pct):
    """판매가 마진율만 정한 정책 하나 (6마켓 전부)."""
    from lemouton.policy.service import create_policy, save_item
    p = create_policy(s, name=name)
    for market in ('smartstore', 'coupang', 'lotteon', 'eleven11',
                   'auction', 'gmarket'):
        save_item(s, policy=p, market=market, item_key='price',
                  config={'sourcing_mode': 'margin_rate', 'sourcing_rate': rate_pct})
    s.flush()
    return p


def _attach_set(s, set_id, policy_id):
    from lemouton.policy.models import SetPolicyLink
    s.add(SetPolicyLink(set_id=set_id, policy_id=policy_id))
    s.flush()


def _attach_model(s, code, policy_id):
    from lemouton.policy.models import BundlePolicyLink
    s.add(BundlePolicyLink(model_code=code, policy_id=policy_id))
    s.flush()


def _price(tpl, market='ss', purchase=100000):
    from lemouton.pricing.unified import compute_market_price
    return compute_market_price(tpl, market, 'sourcing', purchase).final_price


# ── ① 되받기 — 아무것도 안 붙이면 값이 그대로여야 한다 ────────────────────

def test_구성에도_상품에도_정책이_없으면_템플릿_그대로(s):
    from lemouton.policy.as_template import policy_template_for_set
    t = _tpl(s)
    _model(s, 'A', t.id)
    ps = _set(s, 'A', '기본 구성')

    assert policy_template_for_set(s, ps.id, fallback=t) is None, \
        '정책이 없는데 껍데기를 만들면 안 된다 — 쓰던 템플릿이 그대로여야 한다'


def test_구성에_정책이_없으면_상품_정책을_따른다(s):
    """★ 되받기의 핵심 — 여기서 None 을 돌려주면 상품 정책까지 잃는다."""
    from lemouton.policy.as_template import policy_template_for_set
    t = _tpl(s)
    _model(s, 'A', t.id)
    ps = _set(s, 'A', '기본 구성')
    _attach_model(s, 'A', _policy_with_rate(s, '상품 정책', 20.0).id)

    shim = policy_template_for_set(s, ps.id, fallback=t)

    assert shim is not None, '구성에 없다고 상품 정책까지 버리면 안 된다'
    assert _price(shim) == _price(_policy_shim(s, '상품 정책', t)), \
        '상품 정책 값이 그대로 나와야 한다'


def _policy_shim(s, name, fallback):
    from lemouton.policy.as_template import policy_as_template
    from lemouton.policy.models import MarketPolicy
    pid = s.query(MarketPolicy).filter_by(name=name).one().id
    return policy_as_template(s, pid, fallback=fallback)


# ── ② 갈라짐 — 구성마다 다른 값이 나가야 한다 ────────────────────────────

def test_구성마다_정책이_다르면_가격이_갈린다(s):
    from lemouton.policy.as_template import policy_template_for_set
    t = _tpl(s)
    _model(s, 'A', t.id)
    단품 = _set(s, 'A', '단품')
    세트 = _set(s, 'A', '세트')
    _attach_set(s, 단품.id, _policy_with_rate(s, '단품 정책', 10.0).id)
    _attach_set(s, 세트.id, _policy_with_rate(s, '세트 정책', 30.0).id)

    a = _price(policy_template_for_set(s, 단품.id, fallback=t))
    b = _price(policy_template_for_set(s, 세트.id, fallback=t))

    assert a != b, f'구성마다 정책이 다른데 같은 값이 나온다 ({a})'
    assert b > a, f'마진율이 높은 쪽이 비싸야 한다 (단품 {a} · 세트 {b})'


def test_구성_하나만_정책이_있으면_나머지는_상품_정책(s):
    from lemouton.policy.as_template import policy_template_for_set
    t = _tpl(s)
    _model(s, 'A', t.id)
    특가 = _set(s, 'A', '특가')
    보통 = _set(s, 'A', '보통')
    _attach_model(s, 'A', _policy_with_rate(s, '상품 정책', 20.0).id)
    _attach_set(s, 특가.id, _policy_with_rate(s, '특가 정책', 5.0).id)

    특가값 = _price(policy_template_for_set(s, 특가.id, fallback=t))
    보통값 = _price(policy_template_for_set(s, 보통.id, fallback=t))

    assert 특가값 < 보통값, f'특가 구성이 더 싸야 한다 (특가 {특가값} · 보통 {보통값})'


# ── ③ 돈이 나가는 길 — 대상마다 규칙을 다시 뽑나 ─────────────────────────

def test_가격규칙을_구성마다_다시_뽑는다(s):
    """🔴 전엔 sku 당 한 번만 뽑아, 구성이 둘이라도 같은 값이 두 벌에 나갔다."""
    from lemouton.uploader.reconcile import _price_template_for
    from lemouton.sourcing.models import Option
    t = _tpl(s)
    _model(s, 'A', t.id)
    단품 = _set(s, 'A', '단품')
    세트 = _set(s, 'A', '세트')
    s.add(Option(canonical_sku='SKU-1', model_code='A',
                 color_code='BK', size_code='M'))
    _attach_set(s, 단품.id, _policy_with_rate(s, '단품 정책', 10.0).id)
    _attach_set(s, 세트.id, _policy_with_rate(s, '세트 정책', 30.0).id)
    s.flush()

    a = _price(_price_template_for(s, 'SKU-1', set_id=단품.id))
    b = _price(_price_template_for(s, 'SKU-1', set_id=세트.id))

    assert a != b, f'구성을 줬는데도 같은 값이 나온다 ({a}) — 규칙을 대상마다 안 뽑는 것'


def test_구성을_안_주면_예전과_똑같다(s):
    """옛 호출부 보호 — set_id 없이 부르면 상품 정책만 본다."""
    from lemouton.uploader.reconcile import _price_template_for
    from lemouton.sourcing.models import Option
    t = _tpl(s)
    _model(s, 'A', t.id)
    s.add(Option(canonical_sku='SKU-1', model_code='A',
                 color_code='BK', size_code='M'))
    s.flush()

    got = _price_template_for(s, 'SKU-1')

    assert got is t, '정책이 없으면 쓰던 템플릿이 그대로 나와야 한다'


# ── ④ 기준선이 구성별로 갈리나 (같은 값을 계속 다시 보내지 않게) ──────────

def test_기준선이_구성별로_갈린다(s):
    from datetime import datetime, timezone
    from lemouton.uploader.models import PriceSnapshot
    from lemouton.uploader.reconcile import last_confirmed_snapshot

    now = datetime.now(timezone.utc)
    for sid, price in ((11, 50000), (22, 90000)):
        s.add(PriceSnapshot(canonical_sku='SKU-1', market='smartstore',
                            account_key='default', set_id=sid,
                            upload_price=price, action='upload', uploaded_at=now))
    s.flush()

    a = last_confirmed_snapshot(s, canonical_sku='SKU-1', market='smartstore',
                                account_key='default', set_id=11)
    b = last_confirmed_snapshot(s, canonical_sku='SKU-1', market='smartstore',
                                account_key='default', set_id=22)

    assert a.upload_price == 50000, '구성 11 의 기준선이 아니다'
    assert b.upload_price == 90000, '구성 22 의 기준선이 아니다'


def test_구성_생기기_전_옛_기록도_기준선이_된다(s):
    """🔴 옛 줄(set_id 없음)을 버리면 이미 올라간 값을 「처음」으로 오인해 다시 보낸다."""
    from datetime import datetime, timezone
    from lemouton.uploader.models import PriceSnapshot
    from lemouton.uploader.reconcile import last_confirmed_snapshot

    s.add(PriceSnapshot(canonical_sku='SKU-1', market='smartstore',
                        account_key='default', set_id=None,
                        upload_price=77000, action='upload',
                        uploaded_at=datetime.now(timezone.utc)))
    s.flush()

    got = last_confirmed_snapshot(s, canonical_sku='SKU-1', market='smartstore',
                                  account_key='default', set_id=99)

    assert got is not None and got.upload_price == 77000
