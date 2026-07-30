# -*- coding: utf-8 -*-
"""매트릭스 옵션 — 원본(U) · 파생(P).

지켜야 할 것:
  · 모델 하나에 원본은 **하나뿐** (둘이면 어느 쪽이 진짜인지 알 수 없다)
  · 파생은 **원본의 옵션만** 담을 수 있다
  · 파생에서 또 파생을 만들 수 없다 (원본이 어디인지 잃는다)
  · 파생에서는 소싱처 URL·사입품번을 **못 고친다** — 원본으로 보내야 한다
"""
import pytest
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from shared import display_no as D
from lemouton.matrix import models as MM     # noqa: F401 — 테이블 등록
from lemouton.matrix.models import KIND_DERIVED, KIND_ORIGIN, MatrixOption
from lemouton.matrix.service import (
    MatrixError, create_derived, derived_of, edit_target, ensure_all_origins,
    ensure_origin, member_skus, origin_of,
)
from lemouton.sourcing.display_no_assign import assign_missing, pending_counts
from lemouton.sourcing.models import Model, Option

ON = date(2026, 7, 30)


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _model(s, code='르무통_메이트', n_opts=6, at=0):
    m = Model(model_code=code, model_name_raw='메이트', model_name_display='메이트',
              brand='르무통', created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
              + timedelta(minutes=at))
    s.add(m); s.flush()
    for i in range(n_opts):
        s.add(Option(canonical_sku=f'SKU-{code[-2:]}{i:06d}', model_code=code,
                     color_code='블랙' if i < 3 else '그레이', size_code=str(220 + i * 5)))
    s.flush()
    return m


# ── 원본 ──────────────────────────────────────────────────────────────────

def test_모델마다_원본이_하나_생긴다(db):
    m = _model(db)
    a = ensure_origin(db, m)
    assert a.kind == KIND_ORIGIN and a.model_code == m.model_code
    assert a.name == '메이트'


def test_원본은_두_번_만들어지지_않는다(db):
    m = _model(db)
    a = ensure_origin(db, m)
    b = ensure_origin(db, m)
    assert a.id == b.id
    assert db.query(MatrixOption).filter_by(kind=KIND_ORIGIN).count() == 1


def test_원본_멤버는_모델이_가진_옵션_전부다(db):
    m = _model(db, n_opts=6)
    o = ensure_origin(db, m)
    assert len(member_skus(db, o)) == 6


def test_원본_소급은_없는_모델에만_만든다(db):
    _model(db, '르무통_메이트', 3, at=0)
    _model(db, '르무통_버디', 2, at=1)
    assert ensure_all_origins(db, limit=None) == 2
    assert ensure_all_origins(db, limit=None) == 0      # 두 번째는 할 일 없음


# ── 파생 ──────────────────────────────────────────────────────────────────

def test_고른_옵션만_담긴다(db):
    m = _model(db, n_opts=6)
    org = ensure_origin(db, m)
    picked = member_skus(db, org)[:3]
    d = create_derived(db, origin=org, name='인기색만', skus=picked, on=ON)
    assert d.kind == KIND_DERIVED and d.origin_id == org.id
    assert member_skus(db, d) == picked
    assert len(member_skus(db, org)) == 6, '원본은 그대로여야 한다'


def test_파생은_만들자마자_P번호를_받는다(db):
    m = _model(db)
    org = ensure_origin(db, m)
    d = create_derived(db, origin=org, name='일부', skus=member_skus(db, org)[:2], on=ON)
    assert d.display_no == 'P20260730-000001'


def test_원본에_없는_옵션은_담을_수_없다(db):
    m1 = _model(db, '르무통_메이트', 3, at=0)
    m2 = _model(db, '르무통_버디', 3, at=1)
    org = ensure_origin(db, m1)
    남의것 = member_skus(db, ensure_origin(db, m2))[0]
    with pytest.raises(MatrixError, match='원본에 없는'):
        create_derived(db, origin=org, name='섞임',
                       skus=member_skus(db, org)[:1] + [남의것], on=ON)


def test_파생에서_또_파생을_만들_수_없다(db):
    m = _model(db)
    org = ensure_origin(db, m)
    d = create_derived(db, origin=org, name='일부', skus=member_skus(db, org)[:2], on=ON)
    with pytest.raises(MatrixError, match='원본에서만'):
        create_derived(db, origin=d, name='또', skus=member_skus(db, d)[:1], on=ON)


def test_하나도_안_고르면_막는다(db):
    m = _model(db)
    org = ensure_origin(db, m)
    with pytest.raises(MatrixError, match='하나도'):
        create_derived(db, origin=org, name='빈것', skus=[], on=ON)


def test_같은_옵션을_두_번_넣어도_한_번만_담긴다(db):
    m = _model(db)
    org = ensure_origin(db, m)
    sku = member_skus(db, org)[0]
    d = create_derived(db, origin=org, name='중복', skus=[sku, sku, sku], on=ON)
    assert member_skus(db, d) == [sku]


# ── 원본 ↔ 파생 ───────────────────────────────────────────────────────────

def test_파생에서_원본으로_갈_수_있다(db):
    m = _model(db)
    org = ensure_origin(db, m)
    d = create_derived(db, origin=org, name='일부', skus=member_skus(db, org)[:2], on=ON)
    assert origin_of(db, d).id == org.id
    assert origin_of(db, org).id == org.id, '원본의 원본은 자기 자신'
    assert [x.id for x in derived_of(db, org)] == [d.id]


def test_파생에서는_못_고치고_원본으로_보낸다(db):
    """소싱처 URL·사입품번은 원본에서만 — 파생에서 고치면 원본이 바뀐다."""
    m = _model(db)
    org = ensure_origin(db, m)
    d = create_derived(db, origin=org, name='일부', skus=member_skus(db, org)[:2], on=ON)

    t_org = edit_target(db, org)
    assert t_org['editable'] is True

    t_d = edit_target(db, d)
    assert t_d['editable'] is False
    assert t_d['origin'].id == org.id
    assert '원본' in t_d['reason']


# ── 번호 부여 ─────────────────────────────────────────────────────────────

def test_원본은_U_파생은_P를_받는다(db):
    m = _model(db)
    org = ensure_origin(db, m)
    d = create_derived(db, origin=org, name='일부', skus=member_skus(db, org)[:2], on=ON)
    assign_missing(db, on=ON, limit=None)
    db.refresh(org)
    assert org.display_no == 'U20260730-000001'
    assert d.display_no == 'P20260730-000001', '만들 때 이미 받았고 바뀌지 않는다'
    assert pending_counts(db)['matrix_options'] == 0


def test_번호_부여를_다시_돌려도_안_바뀐다(db):
    m = _model(db)
    ensure_origin(db, m)
    assign_missing(db, on=ON, limit=None)
    before = [x.display_no for x in db.query(MatrixOption).all()]
    assign_missing(db, on=date(2026, 8, 1), limit=None)
    assert [x.display_no for x in db.query(MatrixOption).all()] == before


def test_원본_파생_모상품_번호가_서로_안_겹친다(db):
    for i in range(3):
        _model(db, f'브랜드_모델{i}', 4, at=i)
    ensure_all_origins(db, limit=None)
    for org in db.query(MatrixOption).filter_by(kind=KIND_ORIGIN).all():
        create_derived(db, origin=org, name='일부',
                       skus=member_skus(db, org)[:2], on=ON)
    assign_missing(db, on=ON, limit=None)
    nos = ([x.display_no for x in db.query(MatrixOption).all()]
           + [x.display_no for x in db.query(Model).all()])
    assert all(D.is_valid(n) for n in nos)
    assert len(nos) == len(set(nos))
