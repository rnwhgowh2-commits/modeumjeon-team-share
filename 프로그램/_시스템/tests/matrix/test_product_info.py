# -*- coding: utf-8 -*-
"""[TEST] 노션 ④ 상품 관리 —「적용된 정책 보기」·「카테고리 맵핑 보기」.

🔴 값을 지어내지 않는다. 정책이 안 붙었으면 None, 맵핑이 없으면 빈 목록이고
   화면이 「아직 없다」고 말한다.
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM      # noqa: F401 — 테이블 등록
from lemouton.policy.models import BundlePolicyLink, MarketPolicy, MarketPolicyValue
from lemouton.policy.service import policy_of, readiness, values_for
from lemouton.registration.models import CategoryMapRow
from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
from lemouton.sourcing.models import Model, Option

CODE = '르무통_메이트'


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    s.add(Model(model_code=CODE, model_name_raw='메이트'))
    s.add(Option(canonical_sku='SKU-1', model_code=CODE,
                 color_code='블랙', size_code='260'))
    s.commit()
    yield s
    s.close()


def _link_source(s, site='musinsa', path='신발>스니커즈'):
    sp = SourceProduct(site=site, url=f'https://{site}/x', category_path=path)
    s.add(sp)
    s.flush()
    so = SourceOption(source_product_id=sp.id, color_text='블랙', size_text='260')
    s.add(so)
    s.flush()
    s.add(OptionSourceLink(canonical_sku='SKU-1', source_option_id=so.id))
    s.commit()
    return sp


# ── 적용된 정책 ─────────────────────────────────────────────────────────────

def test_정책이_안_붙었으면_없다고_한다(db):
    assert policy_of(db, CODE) is None


def test_붙은_정책과_마켓별_채움을_읽는다(db):
    p = MarketPolicy(name='테스트 정책')
    db.add(p)
    db.flush()
    db.add(BundlePolicyLink(model_code=CODE, policy_id=p.id))
    db.add(MarketPolicyValue(policy_id=p.id, market='smartstore',
                             field_key='price', value='{"margin_rate": 25}'))
    db.commit()

    assert policy_of(db, CODE).name == '테스트 정책'
    rd = readiness(db, p.id)
    assert rd['smartstore']['filled'] == 1
    assert rd['smartstore']['price_ready'] is True
    assert rd['coupang']['price_ready'] is False, '안 정한 마켓은 가격을 쓸 수 없다'
    assert list(values_for(db, p.id, 'smartstore').keys()) == ['price']


# ── 카테고리 맵핑 ───────────────────────────────────────────────────────────

def _sources_of(s, code):
    """라우트가 쓰는 것과 같은 조회 — 소싱처 카테고리 경로."""
    skus = [o.canonical_sku for o in s.query(Option).filter(Option.model_code == code)]
    return (s.query(SourceProduct.site, SourceProduct.category_path)
            .join(SourceOption, SourceOption.source_product_id == SourceProduct.id)
            .join(OptionSourceLink,
                  OptionSourceLink.source_option_id == SourceOption.id)
            .filter(OptionSourceLink.canonical_sku.in_(skus)).distinct().all())


def test_소싱처_카테고리를_읽는다(db):
    _link_source(db)
    assert _sources_of(db, CODE) == [('musinsa', '신발>스니커즈')]


def test_카테고리를_못_읽은_소싱처는_비어_있다(db):
    _link_source(db, path=None)
    assert [p for _s, p in _sources_of(db, CODE) if p] == []


def test_맵핑_상태를_그대로_보여준다(db):
    """제안·재확인은 확정이 아니다 — 확정처럼 보이면 안 된다."""
    _link_source(db)
    db.add(CategoryMapRow(source_id='musinsa', source_path='신발>스니커즈',
                          market='smartstore', market_cat_code='123',
                          market_cat_path='패션>신발', status='suggested',
                          updated_at=dt.datetime(2026, 7, 31)))
    db.commit()
    r = db.query(CategoryMapRow).one()
    assert r.status == 'suggested'
    assert r.market_cat_path == '패션>신발'
