# -*- coding: utf-8 -*-
"""「마켓 공통」 — 넣기 · 불러오기 · 값 출처 판정.

🔴 이 파일이 지키는 것:
  ① 공통은 **한 번 넣으면 끝**이다. 그 뒤 마켓에서 고치면 공통이 다시 덮지 않는다.
  ② 「공통에서 받았나 / 직접 고쳤나」는 **값 비교로 판정하지 않는다** —
     공통이 나중에 바뀌면 값 비교는 「직접 고침」이라는 틀린 답을 낸다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM     # noqa: F401 — 테이블 등록
from lemouton.policy.fields import COMMON_KEY, MARKET_KEYS, item_keys_for
from lemouton.policy.service import create_policy, save_item, values_for


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_공통은_마켓_목록에_섞이지_않는다():
    """「마켓 공통」은 진짜 마켓이 아니다 — 마켓 목록에 들어가면 전송 대상이 된다."""
    assert COMMON_KEY == 'common'
    assert COMMON_KEY not in MARKET_KEYS


def test_공통에도_항목을_저장할_수_있다(db):
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    assert values_for(db, p.id, COMMON_KEY) == {'price': {'sourcing_rate': 25}}


def test_공통_항목표는_마켓_전용을_빼고_준다():
    """공통에는 「쿠팡만 있는 항목」을 둘 수 없다 — 어느 마켓에 넣을지 정해지지 않는다."""
    common_keys = item_keys_for(COMMON_KEY)
    coupang_only = set(item_keys_for('coupang')) - set(item_keys_for('smartstore'))
    assert coupang_only, '쿠팡 전용 항목이 하나도 없다면 이 테스트는 의미가 없다'
    assert not (coupang_only & set(common_keys))


# ── 「공통에서 받은 시각」 ────────────────────────────────────────────────

def test_받은_시각_칸이_있다(db):
    """값 비교로 출처를 판정하면 공통이 바뀔 때 틀린 답이 나온다 — 시각을 남긴다."""
    from lemouton.policy.models import MarketPolicyValue
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market='smartstore', item_key='price',
              config={'sourcing_rate': 25})
    row = db.query(MarketPolicyValue).filter_by(
        policy_id=p.id, market='smartstore', field_key='price').one()
    assert row.from_common_at is None, '직접 저장한 값은 공통에서 온 게 아니다'


# ── 넣기 (공통 → 고른 마켓) ──────────────────────────────────────────────

def test_넣으면_고른_마켓에만_들어간다(db):
    from lemouton.policy.common_sync import push_to_markets
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})

    n = push_to_markets(db, policy=p, markets=['smartstore', 'coupang'])

    assert n == 2
    assert values_for(db, p.id, 'smartstore') == {'price': {'sourcing_rate': 25}}
    assert values_for(db, p.id, 'coupang') == {'price': {'sourcing_rate': 25}}
    assert values_for(db, p.id, 'gmarket') == {}, '안 고른 마켓은 그대로여야 한다'


def test_넣은_뒤_마켓에서_고치면_공통이_다시_덮지_않는다(db):
    """사장님 확정 — 「한 번 넣으면 끝, 그 뒤 고치면 고친 대로」."""
    from lemouton.policy.common_sync import push_to_markets
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    push_to_markets(db, policy=p, markets=['coupang'])

    save_item(db, policy=p, market='coupang', item_key='price',
              config={'sourcing_rate': 32})
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 10})

    assert values_for(db, p.id, 'coupang') == {'price': {'sourcing_rate': 32}}


def test_항목을_골라_넣을_수_있다(db):
    from lemouton.policy.common_sync import push_to_markets
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    save_item(db, policy=p, market=COMMON_KEY, item_key='name',
              config={'max_len': 100})

    push_to_markets(db, policy=p, markets=['coupang'], item_keys=['price'])

    assert values_for(db, p.id, 'coupang') == {'price': {'sourcing_rate': 25}}


def test_모르는_마켓에는_못_넣는다(db):
    from lemouton.policy.common_sync import push_to_markets
    from lemouton.policy.service import PolicyError
    p = create_policy(db, name='르무통 기본')
    with pytest.raises(PolicyError):
        push_to_markets(db, policy=p, markets=['gmarket', '없는마켓'])


# ── 불러오기 (마켓 ← 공통) ──────────────────────────────────────────────

def test_전체_불러오기(db):
    from lemouton.policy.common_sync import pull_from_common
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    save_item(db, policy=p, market=COMMON_KEY, item_key='name',
              config={'max_len': 100})
    save_item(db, policy=p, market='coupang', item_key='price',
              config={'sourcing_rate': 32})

    n = pull_from_common(db, policy=p, market='coupang')

    assert n == 2
    assert values_for(db, p.id, 'coupang') == {
        'price': {'sourcing_rate': 25}, 'name': {'max_len': 100}}


def test_항목_하나만_불러오기(db):
    from lemouton.policy.common_sync import pull_from_common
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    save_item(db, policy=p, market=COMMON_KEY, item_key='name',
              config={'max_len': 100})
    save_item(db, policy=p, market='coupang', item_key='name',
              config={'max_len': 50})

    n = pull_from_common(db, policy=p, market='coupang', item_keys=['price'])

    assert n == 1
    assert values_for(db, p.id, 'coupang') == {
        'price': {'sourcing_rate': 25}, 'name': {'max_len': 50}}


def test_공통이_비었으면_불러오기는_막는다(db):
    from lemouton.policy.common_sync import pull_from_common
    from lemouton.policy.service import PolicyError
    p = create_policy(db, name='르무통 기본')
    with pytest.raises(PolicyError):
        pull_from_common(db, policy=p, market='coupang')


def test_공통_자신은_불러올_수_없다(db):
    from lemouton.policy.common_sync import pull_from_common
    from lemouton.policy.service import PolicyError
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    with pytest.raises(PolicyError):
        pull_from_common(db, policy=p, market=COMMON_KEY)


# ── 값 출처 판정 ────────────────────────────────────────────────────────

def test_출처_판정_세_가지(db):
    from lemouton.policy.common_sync import origin_of, push_to_markets
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    push_to_markets(db, policy=p, markets=['smartstore'])
    save_item(db, policy=p, market='coupang', item_key='price',
              config={'sourcing_rate': 32})

    assert origin_of(db, p.id, 'smartstore')['price'] == 'common'
    assert origin_of(db, p.id, 'coupang')['price'] == 'own'
    assert origin_of(db, p.id, 'gmarket').get('price', 'none') == 'none'


def test_공통이_바뀌어도_받은_마켓은_계속_공통이다(db):
    """값 비교로 판정했다면 여기서 「직접 고침」이라는 틀린 답이 나온다."""
    from lemouton.policy.common_sync import origin_of, push_to_markets
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    push_to_markets(db, policy=p, markets=['smartstore'])

    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 10})

    assert origin_of(db, p.id, 'smartstore')['price'] == 'common'


def test_마켓_요약은_한_단어로_말한다(db):
    from lemouton.policy.common_sync import market_summary, push_to_markets
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    push_to_markets(db, policy=p, markets=['smartstore'])
    save_item(db, policy=p, market='coupang', item_key='price',
              config={'sourcing_rate': 32})

    s = market_summary(db, p.id)
    assert s['smartstore']['state'] == 'common'
    assert s['coupang']['state'] == 'own'
    assert s['gmarket']['state'] == 'none'
    assert s['smartstore']['at'] is not None, '받은 날짜를 화면에 보여줘야 한다'


def test_공통_줄은_마켓_요약에_안_섞인다(db):
    """공통은 마켓이 아니다 — 요약에 끼면 없는 마켓이 화면에 뜬다."""
    from lemouton.policy.common_sync import market_summary
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})

    s = market_summary(db, p.id)
    assert COMMON_KEY not in s
    assert set(s) == set(MARKET_KEYS)
    assert all(v['state'] == 'none' for v in s.values()), \
        '공통에만 넣었으면 어느 마켓도 아직 못 받은 것이다'


def test_전체_불러오기는_공통에_없는_항목을_안_건드린다(db):
    """화면이 「공통에 없는 항목은 그대로 둡니다」라고 말한다 — 실제로 그런지 본다."""
    from lemouton.policy.common_sync import pull_from_common
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    save_item(db, policy=p, market='coupang', item_key='tags',
              config={'max_count': 7})

    pull_from_common(db, policy=p, market='coupang')

    got = values_for(db, p.id, 'coupang')
    assert got['price'] == {'sourcing_rate': 25}
    assert got['tags'] == {'max_count': 7}, '공통에 없는 항목은 남아 있어야 한다'


def test_한_마켓에_공통과_직접이_섞이면_직접으로_본다(db):
    """「공통 따름」이라 말했다가 실제로 다르면 그게 더 나쁘다."""
    from lemouton.policy.common_sync import market_summary, push_to_markets
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'sourcing_rate': 25})
    push_to_markets(db, policy=p, markets=['smartstore'])
    save_item(db, policy=p, market='smartstore', item_key='name',
              config={'max_len': 50})

    assert market_summary(db, p.id)['smartstore']['state'] == 'own'
