# -*- coding: utf-8 -*-
"""0층 상품명 규칙이 **실제로 상품명을 만드는 데 쓰이나**.

🔴 이 파일이 막는 사고: Phase 1 이 `market_policies.name_rule_id` 칸을 만들었지만
   **읽는 곳이 한 곳도 없었다.** 표만 생기고 배선이 없으면 화면에서 규칙을 골라도
   나가는 상품명은 하나도 안 바뀐다 — 이 저장소가 반복해 겪은 형태다
   (직전에도 상품명 바이트 상한이 같은 이유로 안 먹고 있었다).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.policy import models as PM  # noqa: F401 — 테이블 등록
from lemouton.policy.models import MarketPolicy, NameRule
from shared.db import Base


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _정책(db, **kw):
    p = MarketPolicy(name='시험 정책', **kw)
    db.add(p)
    db.commit()
    return p


def _규칙(db, **kw):
    kw.setdefault('name', '시험 규칙')
    kw.setdefault('token_order', ['brand', 'origin_name'])
    r = NameRule(**kw)
    db.add(r)
    db.commit()
    return r


# ── 규칙을 안 고른 정책은 지금까지처럼 ─────────────────────────────────────

def test_규칙을_안_고르면_정책_값을_그대로_쓴다(db):
    """🔴 이 칸이 생겼다고 달라지는 정책이 하나도 없어야 한다."""
    from lemouton.policy import name_rules as NR

    p = _정책(db)
    원래 = {'name': {'token_order': ['origin_name'], 'max_len': 30}}
    나온것 = NR.apply_to_rules(db, policy=p, market='coupang', rules=원래)
    assert 나온것['name'] == {'token_order': ['origin_name'], 'max_len': 30}


def test_규칙_번호가_가리키는_규칙이_없어도_안_터진다(db):
    """지워진 규칙을 가리키면 **정책 값으로 돌아간다** — 이름을 지어내지 않는다."""
    from lemouton.policy import name_rules as NR

    p = _정책(db, name_rule_id=99999)
    원래 = {'name': {'token_order': ['origin_name']}}
    나온것 = NR.apply_to_rules(db, policy=p, market='coupang', rules=원래)
    assert 나온것['name']['token_order'] == ['origin_name']


# ── 규칙을 고르면 그 규칙이 이긴다 ─────────────────────────────────────────

def test_규칙을_고르면_조립_순서가_규칙을_따른다(db):
    from lemouton.policy import name_rules as NR

    r = _규칙(db, token_order=['origin_name', 'brand'])
    p = _정책(db, name_rule_id=r.id)
    나온것 = NR.apply_to_rules(
        db, policy=p, market='coupang',
        rules={'name': {'token_order': ['brand', 'origin_name']}})
    assert 나온것['name']['token_order'] == ['origin_name', 'brand']


def test_규칙의_치환표를_따른다(db):
    from lemouton.policy import name_rules as NR

    r = _규칙(db, replacements=[{'from': '재킷', 'to': '자켓'}])
    p = _정책(db, name_rule_id=r.id)
    나온것 = NR.apply_to_rules(db, policy=p, market='coupang', rules={'name': {}})
    assert 나온것['name']['replacements'] == [{'from': '재킷', 'to': '자켓'}]


def test_규칙이_안_가진_칸은_정책_값이_남는다(db):
    """규칙은 조립 순서·치환표만 갖는다. 글자수 상한 같은 건 정책 것이 그대로다."""
    from lemouton.policy import name_rules as NR

    r = _규칙(db, token_order=['brand'])
    p = _정책(db, name_rule_id=r.id)
    나온것 = NR.apply_to_rules(
        db, policy=p, market='coupang',
        rules={'name': {'max_len': 40, 'separator': '_', 'dedupe_words': True}})
    assert 나온것['name']['max_len'] == 40
    assert 나온것['name']['separator'] == '_'
    assert 나온것['name']['dedupe_words'] is True


def test_마켓별_개별조합이_있으면_그_마켓만_다르게(db):
    from lemouton.policy import name_rules as NR

    r = _규칙(db, token_order=['brand', 'origin_name'],
              market_overrides={'eleven11': {'token_order': ['origin_name']}})
    p = _정책(db, name_rule_id=r.id)

    십일번가 = NR.apply_to_rules(db, policy=p, market='eleven11', rules={'name': {}})
    쿠팡 = NR.apply_to_rules(db, policy=p, market='coupang', rules={'name': {}})
    assert 십일번가['name']['token_order'] == ['origin_name']
    assert 쿠팡['name']['token_order'] == ['brand', 'origin_name']


def test_원본_규칙_묶음을_건드리지_않는다(db):
    """🔴 호출자가 넘긴 dict 를 그 자리에서 고치면, 한 마켓 처리가 다음 마켓에 샌다."""
    from lemouton.policy import name_rules as NR

    r = _규칙(db, token_order=['brand'])
    p = _정책(db, name_rule_id=r.id)
    원래 = {'name': {'token_order': ['origin_name']}, 'price': {'x': 1}}
    NR.apply_to_rules(db, policy=p, market='coupang', rules=원래)
    assert 원래['name']['token_order'] == ['origin_name'], '원본이 바뀌었다'


def test_다른_항목은_그대로_넘어간다(db):
    from lemouton.policy import name_rules as NR

    r = _규칙(db)
    p = _정책(db, name_rule_id=r.id)
    나온것 = NR.apply_to_rules(db, policy=p, market='coupang',
                             rules={'name': {}, 'price': {'margin': 30}})
    assert 나온것['price'] == {'margin': 30}


def test_한_규칙을_여러_정책이_같이_쓴다(db):
    """🔴 이게 0층을 만든 이유다 — 규칙을 한 번 고치면 쓰는 정책 전부에 반영된다."""
    from lemouton.policy import name_rules as NR

    r = _규칙(db, token_order=['brand'])
    갑 = _정책(db, name_rule_id=r.id)
    을 = _정책(db, name_rule_id=r.id)

    r.token_order = ['origin_name', 'brand']
    db.commit()

    for p in (갑, 을):
        나온것 = NR.apply_to_rules(db, policy=p, market='coupang', rules={'name': {}})
        assert 나온것['name']['token_order'] == ['origin_name', 'brand']
