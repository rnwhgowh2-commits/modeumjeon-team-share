# -*- coding: utf-8 -*-
"""정규 카테고리 씨앗 붓기 + 기존 매핑 옮기기 (Phase 7-2a).

🔴 이 파일이 막는 사고
  ① 씨앗을 두 번 부어 같은 가지가 두 벌 생기는 것(멱등해야 한다).
  ② **제안까지 옮겨서** 「사장님이 확정한 것」으로 둔갑하는 것.
  ③ 마켓 경로를 모르는데 정규 카테고리를 **지어내는** 것.
  ④ 한 소싱처 경로가 정규 카테고리 **둘**을 가리키는 것(어느 쪽인지 못 정한다).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.policy import category_bootstrap as CB
from lemouton.policy import models as PM  # noqa: F401 — 테이블 등록
from lemouton.policy import normalized_category as NC
from lemouton.registration.models import CategoryMapRow, MarketCategory
from shared.db import Base


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _마켓칸(db, market, path, code, depth=1, leaf=True):
    import datetime
    db.add(MarketCategory(market=market, code=code, name=path.split('>')[-1],
                          full_path=path, depth=depth, is_leaf=leaf,
                          harvested_at=datetime.datetime(2026, 8, 25)))
    db.commit()


def _확정(db, source_id, source_path, market, code, market_path, status='confirmed'):
    db.add(CategoryMapRow(source_id=source_id, source_path=source_path,
                          market=market, market_cat_code=code,
                          market_cat_path=market_path, status=status))
    db.commit()


# ── 경로 쪼개기 ───────────────────────────────────────────────────────────

def test_조상까지_같이_만든다(db):
    """'여성>원피스>미니' 를 넣으면 '여성'·'여성>원피스' 도 생겨야 트리가 된다."""
    CB.ensure_path(db, '여성>원피스>미니')
    db.commit()
    경로들 = sorted(r.path for r in db.query(NC.NormalizedCategory).all())
    assert 경로들 == ['여성', '여성>원피스', '여성>원피스>미니']


def test_깊이와_부모가_이어진다(db):
    막내 = CB.ensure_path(db, '여성>원피스>미니')
    db.commit()
    assert 막내.depth == 2
    부모 = db.get(NC.NormalizedCategory, 막내.parent_id)
    assert 부모.path == '여성>원피스' and 부모.depth == 1


def test_두_번_넣어도_한_벌이다(db):
    CB.ensure_path(db, '여성>원피스')
    CB.ensure_path(db, '여성>원피스')
    db.commit()
    assert db.query(NC.NormalizedCategory).count() == 2   # 여성 · 여성>원피스


def test_이미_있으면_유래를_안_덮는다(db):
    """🔴 나중에 부은 마켓이 먼저 부은 마켓의 유래를 덮으면 출처를 못 쫓는다."""
    CB.ensure_path(db, '여성>원피스', source_market='lotteon')
    CB.ensure_path(db, '여성>원피스', source_market='coupang')
    db.commit()
    row = db.query(NC.NormalizedCategory).filter_by(path='여성>원피스').one()
    assert row.source_market == 'lotteon'


# ── 씨앗 붓기 ─────────────────────────────────────────────────────────────

def test_우선순위_앞선_마켓이_바닥이_된다(db):
    """롯데온이 먼저다 — 뒤 마켓은 **없는 가지만** 더한다."""
    _마켓칸(db, 'lotteon', '여성>원피스', 'L1')
    _마켓칸(db, 'coupang', '여성>원피스', 'C1')       # 같은 가지 — 안 늘어야 한다
    _마켓칸(db, 'coupang', '여성>코트', 'C2')          # 롱테일 — 늘어야 한다
    got = CB.bootstrap(db)
    db.commit()

    경로들 = sorted(r.path for r in db.query(NC.NormalizedCategory).all())
    assert 경로들 == ['여성', '여성>원피스', '여성>코트']
    assert db.query(NC.NormalizedCategory).filter_by(
        path='여성>원피스').one().source_market == 'lotteon'
    assert db.query(NC.NormalizedCategory).filter_by(
        path='여성>코트').one().source_market == 'coupang'
    assert got['coupang'] == 1, '쿠팡이 새로 더한 것은 롱테일 1칸뿐'


def test_두_번_부어도_안_늘어난다(db):
    """🔴 멱등 — 두 번 부으면 같은 가지가 두 벌 생긴다."""
    _마켓칸(db, 'lotteon', '여성>원피스', 'L1')
    CB.bootstrap(db)
    db.commit()
    n = db.query(NC.NormalizedCategory).count()
    CB.bootstrap(db)
    db.commit()
    assert db.query(NC.NormalizedCategory).count() == n


def test_빈_경로는_건너뛴다(db):
    _마켓칸(db, 'lotteon', '   ', 'L0')
    CB.bootstrap(db)
    db.commit()
    assert db.query(NC.NormalizedCategory).count() == 0


# ── 기존 매핑 옮기기 ──────────────────────────────────────────────────────

def test_확정된_것만_옮긴다(db):
    """🔴 제안까지 옮기면 「사장님이 확정한 것」으로 둔갑한다."""
    _확정(db, 'musinsa', '여성의류>원피스', 'coupang', 'C1', '여성>원피스')
    _확정(db, 'musinsa', '여성의류>코트', 'coupang', 'C2', '여성>코트',
          status='suggested')
    got = CB.migrate_confirmed(db)
    db.commit()

    이은것 = [r.source_path for r in db.query(NC.SourceCategoryLink).all()]
    assert 이은것 == ['여성의류>원피스']
    assert got['sources'] == 1


def test_마켓_경로를_모르면_지어내지_않는다(db):
    """🔴 정규 카테고리를 지어내면 그 분류로 상품이 올라간다."""
    _확정(db, 'musinsa', '여성의류>원피스', 'coupang', 'C1', '')
    got = CB.migrate_confirmed(db)
    db.commit()
    assert got['skipped'] == 1
    assert db.query(NC.SourceCategoryLink).count() == 0


def test_한_소싱처_경로는_우선순위_앞선_마켓을_따른다(db):
    """🔴 정규 카테고리 둘을 가리키면 어느 쪽인지 못 정한다."""
    _확정(db, 'musinsa', '여성의류>원피스', 'coupang', 'C1', '여성>원피스')
    _확정(db, 'musinsa', '여성의류>원피스', 'lotteon', 'L1', '여성>드레스')
    CB.migrate_confirmed(db)
    db.commit()

    링크 = db.query(NC.SourceCategoryLink).one()
    정규 = db.get(NC.NormalizedCategory, 링크.normalized_category_id)
    assert 정규.path == '여성>드레스', '롯데온이 쿠팡보다 앞선다'


def test_마켓_연결은_확정_행_전부에서_거둔다(db):
    """소싱처 대표는 하나여도, 마켓 연결은 마켓마다 다 남아야 한다."""
    _확정(db, 'musinsa', '여성의류>원피스', 'coupang', 'C1', '여성>원피스')
    _확정(db, 'musinsa', '여성의류>원피스', 'lotteon', 'L1', '여성>드레스')
    got = CB.migrate_confirmed(db)
    db.commit()
    assert got['markets'] == 2
    마켓들 = sorted(r.market for r in db.query(NC.MarketCategoryLink).all())
    assert 마켓들 == ['coupang', 'lotteon']
    for r in db.query(NC.MarketCategoryLink).all():
        assert r.status == NC.MAPPED


def test_두_번_옮겨도_안_늘어난다(db):
    _확정(db, 'musinsa', '여성의류>원피스', 'coupang', 'C1', '여성>원피스')
    CB.migrate_confirmed(db)
    db.commit()
    두번째 = CB.migrate_confirmed(db)
    db.commit()
    assert 두번째 == {'sources': 0, 'markets': 0, 'skipped': 0}
    assert db.query(NC.SourceCategoryLink).count() == 1
    assert db.query(NC.MarketCategoryLink).count() == 1


def test_안_이은_행이_있으면_채워_준다(db):
    """크롤이 만들어 둔 보류 행을, 옮기기가 채운다."""
    db.add(NC.SourceCategoryLink(source_id='musinsa', source_path='여성의류>원피스'))
    db.commit()
    _확정(db, 'musinsa', '여성의류>원피스', 'coupang', 'C1', '여성>원피스')
    got = CB.migrate_confirmed(db)
    db.commit()
    assert got['sources'] == 1
    assert db.query(NC.SourceCategoryLink).one().normalized_category_id is not None


# ── 보류함 ────────────────────────────────────────────────────────────────

def test_보류함은_안_이은_행만_준다(db):
    정규 = CB.ensure_path(db, '여성>원피스')
    db.add(NC.SourceCategoryLink(source_id='musinsa', source_path='이었음',
                                 normalized_category_id=정규.id))
    db.add(NC.SourceCategoryLink(source_id='musinsa', source_path='아직'))
    db.add(NC.SourceCategoryLink(source_id='ssf', source_path='다른소싱처'))
    db.commit()

    assert [r.source_path for r in CB.pending(db)] == ['아직', '다른소싱처']
    assert [r.source_path for r in CB.pending(db, source_id='musinsa')] == ['아직']


# ── 아직 전송 경로엔 안 붙었다 ────────────────────────────────────────────

def test_전송_경로는_아직_새_표를_안_본다():
    """🔴 Phase 7-2a 는 표를 채우기만 한다. 여기서 배선하면 카테고리가 잘못 나가
    등록이 통째로 막힐 수 있다."""
    import pathlib
    뿌리 = pathlib.Path(__file__).resolve().parents[2]
    for 파일 in ('lemouton/registration/process_apply.py',
                'webapp/routes/bulk/drafts.py'):
        소스 = (뿌리 / 파일).read_text(encoding='utf-8')
        assert 'normalized_category' not in 소스
        assert 'category_bootstrap' not in 소스
