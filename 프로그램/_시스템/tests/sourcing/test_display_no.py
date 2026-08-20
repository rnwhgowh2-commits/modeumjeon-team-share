# -*- coding: utf-8 -*-
"""표시번호 — 겹치지 않고, 한 번 붙은 번호는 바뀌지 않는다.

번호가 겹치면 사장님이 적어둔 번호가 딴 상품을 가리킨다. 그게 이 테스트의 목적.
규칙: shared/display_no.py · 부여: lemouton/sourcing/display_no_assign.py
"""
import pytest
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from shared import display_no as D
from lemouton.sourcing.display_no_assign import assign_missing, pending_counts
from lemouton.sourcing.models import Model
from lemouton.sources.models import SourceOption, SourceProduct

ON = date(2026, 7, 30)


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _t(n):
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=n)


def _seed(s, *, models=0, prods=(), opts_per_prod=0):
    for i in range(models):
        s.add(Model(model_code=f'브랜드_모델{i}', model_name_raw=f'모델{i}', created_at=_t(i)))
    made = []
    for i, site in enumerate(prods):
        p = SourceProduct(site=site, url=f'https://x/{site}/{i}', created_at=_t(i))
        s.add(p); s.flush(); made.append(p)
        for j in range(opts_per_prod):
            s.add(SourceOption(source_product_id=p.id, color_text='블랙',
                               size_text=str(220 + j * 5), created_at=_t(i * 100 + j)))
    s.flush()
    return made


# ── 형식 ──────────────────────────────────────────────────────────────────

def test_형식이_규칙대로다():
    assert D.format_no('M', 1, on=ON) == 'M20260730-000001'
    assert D.format_no('U', 42, on=ON) == 'U20260730-000042'
    assert D.format_no('MU', 1, band=D.BAND_OPTION, on=ON) == 'MU20260730-000001'
    assert D.format_no('MU', 1, band=D.BAND_PRODUCT, on=ON) == 'MU20260730-100001'


def test_원본_매트릭스는_알파벳_U다():
    """숫자 0 과 헷갈리는 O 를 쓰지 않기로 확정."""
    assert D.PREFIX_MATRIX_ORIGIN == 'U'
    assert not D.format_no(D.PREFIX_MATRIX_ORIGIN, 1, on=ON).startswith('O')


def test_대량등록은_D로_시작한다():
    assert D.is_bulk(D.format_no(D.PREFIX_BULK_SET, 1, on=ON))
    assert D.is_bulk(D.format_no(D.PREFIX_BULK_UNIT, 1, on=ON))
    assert not D.is_bulk(D.format_no('M', 1, on=ON))


def test_소싱처_여덟곳_접두가_다_다르다():
    p = list(D.PREFIX_BY_SITE.values())
    assert len(p) == len(set(p)) == 8


def test_자리수를_넘으면_조용히_자르지_않고_멈춘다():
    """잘라 쓰면 번호가 겹친다 — 차라리 터져야 한다."""
    with pytest.raises(ValueError):
        D.format_no('M', 100_000, on=ON)
    with pytest.raises(ValueError):
        D.format_no('M', 0, on=ON)


def test_상품과_옵션은_같은_접두라도_안_겹친다():
    prods = {D.format_no('MU', i, band=D.BAND_PRODUCT, on=ON) for i in range(1, 500)}
    opts = {D.format_no('MU', i, band=D.BAND_OPTION, on=ON) for i in range(1, 500)}
    assert not (prods & opts)


# ── 순번 예약 ─────────────────────────────────────────────────────────────

def test_예약은_이어서_나간다(db):
    assert D.reserve(db, 'M', count=3) == 1
    assert D.reserve(db, 'M', count=2) == 4
    assert D.reserve(db, 'M') == 6


def test_접두와_구간마다_순번이_따로다(db):
    assert D.reserve(db, 'MU', band=D.BAND_PRODUCT) == 1
    assert D.reserve(db, 'MU', band=D.BAND_OPTION) == 1
    assert D.reserve(db, 'LE', band=D.BAND_PRODUCT) == 1


def test_발급된_번호는_서로_다르다(db):
    got = D.issue(db, 'LE', band=D.BAND_OPTION, count=250, on=ON)
    got += D.issue(db, 'LE', band=D.BAND_OPTION, count=250, on=ON)
    assert len(got) == len(set(got)) == 500


# ── 부여 ──────────────────────────────────────────────────────────────────

def test_등록된_순서대로_번호가_붙는다(db):
    _seed(db, models=5)
    assign_missing(db, on=ON, limit=None)
    got = [(m.created_at, m.display_no) for m in db.query(Model).all()]
    got.sort()
    assert [n for _c, n in got] == [f'M20260730-{i:06d}' for i in range(1, 6)]


def test_소싱처마다_1번부터_따로_붙는다(db):
    _seed(db, prods=['musinsa', 'lemouton', 'musinsa'])
    assign_missing(db, on=ON, limit=None)
    got = sorted(p.display_no for p in db.query(SourceProduct).all())
    assert got == ['LE20260730-100001', 'MU20260730-100001', 'MU20260730-100002']


def test_옵션은_부모_소싱처_접두를_따른다(db):
    _seed(db, prods=['ssf'], opts_per_prod=3)
    assign_missing(db, on=ON, limit=None)
    got = sorted(o.display_no for o in db.query(SourceOption).all())
    assert got == ['SF20260730-000001', 'SF20260730-000002', 'SF20260730-000003']


def test_두_번_돌려도_번호가_안_바뀐다(db):
    """이미 적어둔 번호가 딴 상품을 가리키면 안 된다."""
    _seed(db, models=3, prods=['musinsa'], opts_per_prod=2)
    assign_missing(db, on=ON, limit=None)
    before = ([m.display_no for m in db.query(Model).all()],
              [p.display_no for p in db.query(SourceProduct).all()],
              [o.display_no for o in db.query(SourceOption).all()])
    res = assign_missing(db, on=date(2026, 8, 1), limit=None)
    after = ([m.display_no for m in db.query(Model).all()],
             [p.display_no for p in db.query(SourceProduct).all()],
             [o.display_no for o in db.query(SourceOption).all()])
    assert before == after
    assert all(v == 0 for v in res.values()), f'다시 붙인 것이 있다: {res}'


def test_나중에_들어온_것은_뒤_번호를_받는다(db):
    _seed(db, models=2)
    assign_missing(db, on=ON, limit=None)
    db.add(Model(model_code='브랜드_나중', model_name_raw='나중', created_at=_t(999)))
    db.flush()
    assign_missing(db, on=ON, limit=None)
    got = db.query(Model).filter_by(model_code='브랜드_나중').one()
    assert got.display_no == 'M20260730-000003'


def test_모르는_소싱처는_번호를_지어내지_않는다(db):
    _seed(db, prods=['musinsa', '처음보는곳'])
    res = assign_missing(db, on=ON, limit=None)
    assert res['source_products'] == 1 and res['skipped'] == 1
    unknown = db.query(SourceProduct).filter_by(site='처음보는곳').one()
    assert unknown.display_no is None


def test_한번에_처리할_양을_제한할_수_있다(db):
    _seed(db, models=10)
    assign_missing(db, on=ON, limit=4)
    assert pending_counts(db)['models'] == 6
    assign_missing(db, on=ON, limit=None)
    assert pending_counts(db)['models'] == 0


def test_전부_붙이면_번호가_하나도_안_겹친다(db):
    _seed(db, models=30, prods=['musinsa', 'lemouton', 'ssf', 'lotteon'], opts_per_prod=12)
    assign_missing(db, on=ON, limit=None)
    nos = ([m.display_no for m in db.query(Model).all()]
           + [p.display_no for p in db.query(SourceProduct).all()]
           + [o.display_no for o in db.query(SourceOption).all()])
    assert all(D.is_valid(n) for n in nos)
    assert len(nos) == len(set(nos))
