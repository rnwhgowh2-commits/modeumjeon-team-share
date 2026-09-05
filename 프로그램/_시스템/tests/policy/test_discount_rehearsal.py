# -*- coding: utf-8 -*-
"""할인 반영 리허설 — **아무것도 바꾸지 않고** 무엇이 어떻게 될지만 본다.

🔴 판매가가 바뀌는 변경은 사장님 승인 없이 마켓에 나가면 안 된다.
  그런데 승인하려면 **무엇이 얼마나 바뀌는지**를 볼 수 있어야 한다.

🔴 계산을 스크립트와 화면이 각자 하면 두 숫자가 갈린다 — 승인용 표가
  실제와 다르면 승인 자체가 무의미하다. 그래서 여기 한 곳에서만 만든다.
"""
import pytest

from lemouton.policy.discount_rehearsal import rehearse


class _가짜세션:
    """정책 목록·값을 흉내 낸다 — DB 없이 계산 규칙만 검사한다."""

    def __init__(self, policies):
        self._p = policies


@pytest.fixture
def db(tmp_path):
    from shared.db import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import lemouton.policy.models  # noqa: F401
    eng = create_engine(f'sqlite:///{tmp_path}/t.db')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _정책(s, name, **price):
    from lemouton.policy.service import create_policy, save_item
    p = create_policy(s, name=name)
    save_item(s, policy=p, market='smartstore', item_key='price', config={
        'sourcing_mode': 'margin_rate', 'sourcing_rate': 9.45,
        'fee_rate': 6, 'rounding_unit': 100, **price})
    s.flush()
    return p


def test_할인을_안_건_정책은_표에_안_나온다(db):
    """🔴 안 바뀌는 것을 표에 넣으면 사장님이 「다 바뀌는구나」로 읽는다."""
    _정책(db, '할인없음')
    got = rehearse(db)
    assert got['rows'] == []
    assert got['policies_total'] == 1
    assert got['policies_with_discount'] == 0


def test_판매자_부담이면_판매가가_오르고_고객가는_그대로(db):
    _정책(db, '스스20', discount_unit='PERCENT', discount_value=20,
          discount_burden='seller')
    r = next(x for x in rehearse(db)['rows'] if x['purchase'] == 50000)
    assert r['price_after'] > r['price_before'], '판매가가 안 올랐다'
    assert abs(r['customer_after'] - r['price_before']) <= 100, \
        f"고객이 내는 값이 달라졌다: {r['customer_after']} vs {r['price_before']}"


def test_적자였다가_흑자가_된다(db):
    _정책(db, '스스20', discount_unit='PERCENT', discount_value=20)
    r = next(x for x in rehearse(db)['rows'] if x['purchase'] == 50000)
    assert r['margin_before'] < 0, '고치기 전이 적자가 아니면 이 시험의 전제가 깨졌다'
    assert r['margin_after'] > 0


def test_마켓이_부담하면_한_원도_안_바뀐다(db):
    """🔴 마켓이 내는 몫까지 우리 손해로 세면 멀쩡한 정책을 적자로 오보한다."""
    _정책(db, '마켓부담', discount_unit='PERCENT', discount_value=20,
          discount_burden='market')
    r = next(x for x in rehearse(db)['rows'] if x['purchase'] == 50000)
    assert r['price_after'] == r['price_before']
    assert r['margin_after'] == r['margin_before']
    assert r['margin_before'] > 0, '마켓이 부담하는데 적자로 잡혔다'


def test_고객가는_전체_할인_기준이다(db):
    """마켓이 부담해도 **고객은** 전체 할인만큼 싸게 산다."""
    _정책(db, '마켓부담', discount_unit='PERCENT', discount_value=20,
          discount_burden='market')
    r = next(x for x in rehearse(db)['rows'] if x['purchase'] == 50000)
    assert r['customer_after'] < r['price_after'], '고객가가 판매가와 같다'


def test_역마진에_새로_걸리는_것을_센다(db):
    _정책(db, '스스20', discount_unit='PERCENT', discount_value=20)
    got = rehearse(db, min_margin=99_999_999)     # 전부 미달로 만든다
    assert got['newly_held'] == 0, '고치기 전에도 미달이면 「새로」가 아니다'


def test_붙은_상품_수를_같이_준다(db):
    """🔴 「정책 1건」과 「상품 300개」는 사장님에게 전혀 다른 무게다."""
    _정책(db, '스스20', discount_unit='PERCENT', discount_value=20)
    got = rehearse(db)
    assert 'products' in got['rows'][0]


def test_아무것도_안_바꾼다(db):
    """🔴 리허설이 자료를 건드리면 그건 리허설이 아니다."""
    from lemouton.policy.models import MarketPolicyValue
    _정책(db, '스스20', discount_unit='PERCENT', discount_value=20)
    db.commit()
    before = [(v.policy_id, v.market, v.field_key, v.value)
              for v in db.query(MarketPolicyValue).all()]
    rehearse(db)
    after = [(v.policy_id, v.market, v.field_key, v.value)
             for v in db.query(MarketPolicyValue).all()]
    assert before == after
