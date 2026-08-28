# -*- coding: utf-8 -*-
"""[TEST] 마켓별 업로드 불가 카테고리 검사 — 노션 「(5) ※마켓별 업로드 불가 카테고리 검사」.

마켓에 물어보지 않는다. 이미 전수 수집해 둔 카테고리 사전과 대조해 **미리** 막는다.

🔴 사전이 없으면 「불가」라고 하지 않는다 — 「모른다」를 「안 된다」로 바꾸면
   올릴 수 있는 상품이 통째로 멈춘다.
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
from lemouton.registration import category_check as CC
from lemouton.registration.models import MarketCategory

NOW = dt.datetime(2026, 7, 31)


@pytest.fixture()
def db():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _cat(s, market='smartstore', code='100', path='패션>신발>운동화',
         leaf=True, removed=None):
    s.add(MarketCategory(market=market, code=code, name=path.split('>')[-1],
                         full_path=path, depth=path.count('>') + 1, is_leaf=leaf,
                         harvested_at=NOW, removed_at=removed))
    s.commit()


def test_사전에_있는_끝_카테고리는_통과한다(db):
    _cat(db)
    r = CC.check(db, market='smartstore', code='100')
    assert r['state'] == CC.OK
    assert CC.as_skip(r) is None


def test_사전에_없는_코드는_막는다(db):
    _cat(db, code='100')
    r = CC.check(db, market='smartstore', code='999')
    assert r['state'] == CC.NOT_FOUND
    assert CC.as_skip(r)['blocking'] is True


def test_마켓에서_사라진_카테고리는_막는다(db):
    _cat(db, code='100', removed=NOW)
    r = CC.check(db, market='smartstore', code='100')
    assert r['state'] == CC.REMOVED
    assert CC.as_skip(r)['blocking'] is True


def test_끝_카테고리가_아니면_막는다(db):
    _cat(db, code='100', leaf=False)
    r = CC.check(db, market='smartstore', code='100')
    assert r['state'] == CC.NOT_LEAF
    assert CC.as_skip(r)['blocking'] is True


def test_사전이_아직_없으면_막지_않는다(db):
    """수집 안 한 마켓의 상품을 전부 세우면 안 된다 — 검사 못 했다고만 말한다."""
    r = CC.check(db, market='lotteon', code='100')
    assert r['state'] == CC.NO_DICT
    s = CC.as_skip(r)
    assert s['blocking'] is False
    assert s['gap'] is True, '기능 공백이지 이 상품의 문제가 아니다'


def test_ESM_짝코드도_찾는다(db):
    """ESM 맵핑은 'sd코드/site코드' 로 저장된다 — 둘 중 하나만 사전에 있을 수 있다."""
    _cat(db, market='auction', code='site77')
    r = CC.check(db, market='auction', code='sd11/site77')
    assert r['state'] == CC.OK


def test_사라진_코드와_살아있는_짝이_함께_잡히면_살아있는_쪽을_본다(db):
    _cat(db, market='auction', code='sd11', removed=NOW)
    _cat(db, market='auction', code='site77')
    r = CC.check(db, market='auction', code='sd11/site77')
    assert r['state'] == CC.OK


def test_카테고리를_안_정했으면_여기서_또_말하지_않는다(db):
    """미정 안내는 crosscheck_delegated 가 이미 한다 — 같은 말을 두 번 하지 않는다."""
    r = CC.check(db, market='smartstore', code='')
    assert r['state'] == CC.NO_CODE
    assert CC.as_skip(r) is None


def test_롯데온은_사전에_엉뚱한_행이_있어도_service_단계에서_막지_않는다(db):
    """[2026-08-20 재현] 롯데온의 '카테고리 칸'은 본보기 상품번호(spdNo)다 — 진짜
    카테고리 코드가 아니다(category_suggest.py::SUGGESTION_MARKETS 와 같은 이유로
    market_categories 사전을 아예 쓰지 않는다). 그런데 다른 수집 작업 등으로
    market_categories 에 market='lotteon' 행이 우연히 생기면, check() 혼자서는
    이 spdNo 를 못 찾아 NOT_FOUND(막힘)로 오판한다 — 실제로 라이브에서 이렇게
    막혀 있었다(정상 spdNo 를 넣어도 '이 마켓에 없는 카테고리입니다'로 매번 거부).
    service.prepare_compile_draft 가 market='lotteon' 이면 이 검사 자체를
    아예 타지 않아야 한다."""
    _cat(db, market='lotteon', code='엉뚱한코드')   # 우연히 생긴 무관한 행

    from lemouton.registration.models import ProductDraft
    from lemouton.registration.service import prepare_compile_draft

    draft = ProductDraft(name='테스트 상품', sale_price=10000)
    db.add(draft)
    db.commit()

    _, info = prepare_compile_draft(db, draft, 'lotteon', category_code='LO2751529664')
    blocking = [s for s in info['skipped'] if s.get('blocking')]
    assert not blocking, f'롯데온 본보기 상품번호가 카테고리 사전 검사로 막혔다: {blocking}'
