# -*- coding: utf-8 -*-
"""정규 카테고리 — 소싱처와 마켓 사이의 가운데 층 (Phase 7-1 데이터 바닥).

■ 사장님 확정 (2026-08-25)
  ① 「삼바것 따라가기」 — 소싱처→마켓 직접 매핑 대신 **정규 카테고리를 가운데** 둔다.
  ② 「지금대로 자동 확정 안 함」 — 확신도가 얼마든 사람이 눌러야 이어진다.

🔴 이 파일이 지키는 것
  · **보류함은 별도 표가 아니다** — `normalized_category_id` 가 비어 있는 행이다.
    별도 표를 만들면 원천이 두 벌이 되고, 한쪽에서 이어도 다른 쪽은 모른다.
  · 「못 올림」·「인증 필요」를 **「아직 안 이음」과 구분**한다. 셋을 뭉치면 왜
    안 올라가는지 화면이 말해 주지 못한다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.policy import models as PM  # noqa: F401 — 테이블 등록
from lemouton.policy import normalized_category as NC
from shared.db import Base


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _정규(db, path, parent=None, depth=0, market=None):
    row = NC.NormalizedCategory(path=path, depth=depth, source_market=market,
                                parent_id=parent.id if parent else None)
    db.add(row)
    db.commit()
    return row


# ── 가운데 층이 실제로 한 벌인가 ─────────────────────────────────────────

def test_소싱처가_여럿이어도_정규는_한_벌이다(db):
    """🔴 이게 가운데 층을 둔 이유다 — 「여성>원피스」를 소싱처마다 다시 안 잇는다."""
    정규 = _정규(db, '여성>원피스')
    for src in ('musinsa', 'ssf', 'lotteon'):
        db.add(NC.SourceCategoryLink(source_id=src, source_path='여성의류>원피스',
                                     normalized_category_id=정규.id))
    db.commit()
    붙은것 = db.query(NC.SourceCategoryLink).filter_by(
        normalized_category_id=정규.id).count()
    assert 붙은것 == 3
    assert db.query(NC.NormalizedCategory).count() == 1


def test_정규_하나를_마켓마다_한_번씩_잇는다(db):
    정규 = _정규(db, '여성>원피스')
    for mk, code in [('coupang', '1001'), ('smartstore', '5002')]:
        db.add(NC.MarketCategoryLink(normalized_category_id=정규.id, market=mk,
                                     market_cat_code=code, status=NC.MAPPED))
    db.commit()
    assert db.query(NC.MarketCategoryLink).count() == 2


def test_같은_마켓에_두_번_못_잇는다(db):
    """한 정규 카테고리가 같은 마켓의 두 분류를 가리키면 어느 쪽인지 못 정한다."""
    from sqlalchemy.exc import IntegrityError
    정규 = _정규(db, '여성>원피스')
    db.add(NC.MarketCategoryLink(normalized_category_id=정규.id, market='coupang',
                                 market_cat_code='1001'))
    db.commit()
    db.add(NC.MarketCategoryLink(normalized_category_id=정규.id, market='coupang',
                                 market_cat_code='9999'))
    with pytest.raises(IntegrityError):
        db.commit()


def test_같은_소싱처_같은_경로를_두_번_못_넣는다(db):
    from sqlalchemy.exc import IntegrityError
    db.add(NC.SourceCategoryLink(source_id='musinsa', source_path='여성>원피스'))
    db.commit()
    db.add(NC.SourceCategoryLink(source_id='musinsa', source_path='여성>원피스'))
    with pytest.raises(IntegrityError):
        db.commit()


# ── 보류함 = 안 이은 행 ───────────────────────────────────────────────────

def test_보류함은_별도_표가_아니라_안_이은_행이다(db):
    """🔴 별도 표를 만들면 원천이 두 벌 — 한쪽에서 이어도 다른 쪽은 모른다."""
    정규 = _정규(db, '여성>원피스')
    db.add(NC.SourceCategoryLink(source_id='musinsa', source_path='여성>원피스',
                                 normalized_category_id=정규.id))
    db.add(NC.SourceCategoryLink(source_id='musinsa', source_path='여성>가방'))
    db.commit()

    보류 = db.query(NC.SourceCategoryLink).filter(
        NC.SourceCategoryLink.normalized_category_id.is_(None)).all()
    assert [r.source_path for r in 보류] == ['여성>가방']


def test_새_소싱처_카테고리는_안_이은_채로_쌓인다(db):
    """크롤이 처음 보는 분류를 만나면 여기 NULL 로 쌓인다 — 「없다」가 아니다."""
    r = NC.SourceCategoryLink(source_id='musinsa', source_path='여성>새분류')
    db.add(r)
    db.commit()
    assert r.normalized_category_id is None


# ── 자동 확정 안 함 ───────────────────────────────────────────────────────

def test_점수가_높아도_저절로_이어지지_않는다(db):
    """🔴 사장님 확정 — 확신도가 얼마든 사람이 눌러야 이어진다.

    카테고리가 틀리면 마켓이 등록을 거부하거나 엉뚱한 분류로 올라간다.
    """
    _정규(db, '여성>원피스')
    r = NC.SourceCategoryLink(source_id='musinsa', source_path='여성의류>원피스',
                              confidence=99,
                              candidates_json='[{"id": 1, "path": "여성>원피스"}]')
    db.add(r)
    db.commit()
    assert r.normalized_category_id is None, '점수만으로 이어졌다'


# ── 상태 구분 ─────────────────────────────────────────────────────────────

def test_못_올림과_안_이음을_구분한다(db):
    """🔴 뭉치면 왜 안 올라가는지 화면이 말해 주지 못한다."""
    정규 = _정규(db, '여성>원피스')
    db.add(NC.MarketCategoryLink(normalized_category_id=정규.id, market='coupang',
                                 status=NC.BLOCKED, note='계정 권한상 못 쓰는 분류'))
    db.add(NC.MarketCategoryLink(normalized_category_id=정규.id, market='lotteon'))
    db.commit()
    쿠팡 = db.query(NC.MarketCategoryLink).filter_by(market='coupang').one()
    롯데 = db.query(NC.MarketCategoryLink).filter_by(market='lotteon').one()
    assert 쿠팡.status == NC.BLOCKED and 쿠팡.note
    assert 롯데.status == NC.UNMAPPED, '기본값은 「아직 안 이음」이다'


def test_상태마다_사람이_읽는_말이_있다():
    """영문 코드를 화면에 내보내지 않는다."""
    for st in NC.STATUSES:
        assert NC.STATUS_LABEL.get(st), f'{st} 에 한글 이름이 없다'


# ── 표가 실제로 만들어지나 ────────────────────────────────────────────────

def test_앱이_이_표들을_등록한다():
    """🔴 `create_all` 은 **등록된 모델만** 만든다 — app.py 에서 안 부르면
    표가 조용히 안 생기고 화면은 「불러오지 못했습니다」만 띄운다."""
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2] / 'app.py').read_text(
        encoding='utf-8')
    assert 'import lemouton.policy.normalized_category' in 소스


def test_전송은_옛_방식을_먼저_본다():
    """🔴 [2026-08-26 Phase 7-2c 에서 갱신] 이제 전송도 새 표를 본다.

    Phase 7-1·7-2 동안에는 「아직 안 붙었다」를 여기서 못 박아 뒀다. 배선이 끝난 지금은
    **순서**를 못 박는다 — 옛 방식(`CategoryMapRow` confirmed)을 **먼저** 보고,
    거기 없을 때만 새 방식으로 간다. 그래야 지금까지 잘 나가던 상품의 카테고리가
    한 개도 안 바뀐다.
    """
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'webapp' / 'routes' / 'bulk' / 'drafts.py').read_text(encoding='utf-8')
    블록 = 소스.split('def _mapped_category')[1].split('def _normalized_category')[0]
    assert 'CategoryMapRow' in 블록, '옛 방식을 안 본다'
    assert 블록.index('CategoryMapRow') < 블록.index('_normalized_category'), (
        '새 방식을 먼저 본다 — 잘 나가던 상품의 카테고리가 바뀐다')


def test_가공_엔진은_카테고리_표를_직접_안_본다():
    """판정은 `_mapped_category` 한 곳이다 — 두 곳이면 답이 갈린다."""
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'lemouton' / 'registration' / 'process_apply.py').read_text(
        encoding='utf-8')
    코드만 = chr(10).join(l for l in 소스.splitlines()
                        if not l.lstrip().startswith('#'))
    assert 'normalized_category' not in 코드만


def test_중복_보류함_표가_사라졌다():
    """🔴 원천 두 벌 금지 — 한쪽에서 이어도 다른 쪽은 모른다.

    Phase 1 이 만든 `CategoryMappingReview` 는 읽는 곳이 0곳이었고, 같은 일을 하는
    체계가 이미 둘이나 있었다(`CategoryMapRow` + 대량등록 설정 화면).
    사장님 확정 「삼바것 따라가기」 — 삼바에서 보류함은 **별도 표가 아니라
    「아직 안 이은 행」**이다.
    """
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'lemouton' / 'policy' / 'models.py').read_text(encoding='utf-8')
    코드만 = chr(10).join(l for l in 소스.splitlines()
                        if not l.lstrip().startswith('#'))
    assert 'class CategoryMappingReview' not in 코드만
    assert 'category_mapping_reviews' not in 코드만
