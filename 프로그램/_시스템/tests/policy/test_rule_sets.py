# -*- coding: utf-8 -*-
"""0층 규칙 저장소 — 상품명 규칙 · 상세 템플릿.

🔴 이 파일이 지키는 것: **규칙 한 벌을 여러 정책이 공유**한다. 정책이 값을 복사해
   갖고 있으면 규칙을 고쳐도 옛 정책은 옛 값 그대로다(삼바가 별도 저장소를 둔 이유).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM  # noqa: F401 — 테이블 등록
from lemouton.policy.models import DetailTemplate, MarketPolicy, NameRule


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_상품명_규칙을_저장하고_읽는다(db):
    r = NameRule(name='기본 조립',
                 token_order=['brand', 'origin_name', 'model_no'],
                 replacements=[{'from': '재킷', 'to': '자켓'}])
    db.add(r)
    db.commit()

    got = db.query(NameRule).one()
    assert got.token_order == ['brand', 'origin_name', 'model_no']
    assert got.replacements[0]['from'] == '재킷'
    assert got.max_len_mode == 'byte'


def test_마켓별_개별조합을_담는다(db):
    r = NameRule(name='기본', token_order=['brand', 'origin_name'],
                 market_overrides={'eleven11': {'token_order': ['brand']}})
    db.add(r)
    db.commit()

    got = db.query(NameRule).one()
    assert got.market_overrides['eleven11']['token_order'] == ['brand']


def test_규칙_한_벌을_정책_둘이_같이_쓴다(db):
    r = NameRule(name='공용 규칙', token_order=['brand'])
    db.add(r)
    db.commit()
    db.add_all([MarketPolicy(name='봄 신상', name_rule_id=r.id),
                MarketPolicy(name='가을 신상', name_rule_id=r.id)])
    db.commit()

    쓰는_정책 = db.query(MarketPolicy).filter_by(name_rule_id=r.id).all()
    assert len(쓰는_정책) == 2

    # 규칙을 고치면 두 정책 모두에 반영된다 — 값 복사가 아니라 참조이기 때문
    r.token_order = ['brand', 'origin_name']
    db.commit()
    for p in 쓰는_정책:
        assert db.get(NameRule, p.name_rule_id).token_order == ['brand', 'origin_name']


def test_규칙_없는_정책도_만들_수_있다(db):
    """🔴 회귀 방지 — 규칙을 안 고른 정책은 지금처럼 상품 원본 이름을 그대로 쓴다."""
    p = MarketPolicy(name='규칙 없음')
    db.add(p)
    db.commit()
    assert db.query(MarketPolicy).one().name_rule_id is None


def test_상세_템플릿을_저장하고_읽는다(db):
    t = DetailTemplate(name='기본 상세', top_html='<p>상단</p>',
                       bottom_html='<p>하단</p>',
                       market_overrides={'coupang': 7})
    db.add(t)
    db.commit()

    got = db.query(DetailTemplate).one()
    assert got.top_html == '<p>상단</p>'
    assert got.market_overrides['coupang'] == 7


def test_신규_컬럼이_마이그레이션_목록에_있다():
    """🔴 create_all 은 **기존 테이블의 신규 컬럼**을 추가하지 않는다.

    `market_policies` 는 라이브에 이미 있는 테이블이므로, name_rule_id /
    detail_template_id 는 `_apply_lightweight_migrations` 의 migrations 리스트에
    들어가야 라이브에 실제로 생긴다. 모델에만 적고 여기 안 넣으면 로컬(빈 DB)에서는
    되고 라이브에서는 「컬럼이 없습니다」로 터진다.
    """
    import inspect
    import shared.db as DB

    src = inspect.getsource(DB._apply_lightweight_migrations)
    assert '"market_policies", "name_rule_id"' in src.replace("'", '"')
    assert '"market_policies", "detail_template_id"' in src.replace("'", '"')
