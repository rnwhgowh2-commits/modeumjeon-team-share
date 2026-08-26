# -*- coding: utf-8 -*-
"""새 카테고리 방식이 **실제 전송에도 쓰이나** (Phase 7-2c).

🔴 이 단계가 가장 조심할 자리다 — 카테고리가 잘못 나가면 마켓이 등록을 거부하거나
   엉뚱한 분류로 올라가서, **등록이 통째로 막힌다.**

■ 순서를 못 박는다
    ① 옛 방식(`CategoryMapRow` confirmed) 을 **먼저** 본다.
       지금까지 잘 나가던 상품의 카테고리가 한 개도 안 바뀌게 하기 위해서다.
    ② 옛 방식에 없을 때만 새 방식(소싱처 → 정규 → 마켓)을 본다.
  🔴 새 방식이 옛 방식을 **덮지 않는다.**

■ 「못 올림」·「인증 필요」는 코드를 안 돌려준다
  그 분류로 올리면 마켓이 거부한다. 「아직 안 이음」과 같은 자리로 떨어져 전송이 막히되,
  **사유는 따로 말한다** — 안 말하면 사장님은 이으러 갔다가 「이미 이었는데?」 하고 헤맨다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.policy import models as PM  # noqa: F401 — 테이블 등록
from lemouton.policy import normalized_category as NC
from lemouton.registration.models import CategoryMapRow
from shared.db import Base
from webapp.routes.bulk.drafts import _mapped_category, blocked_category_reason


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


class _Draft:
    source_site = 'musinsa'
    source_category_path = '여성의류>원피스'


def _옛방식(db, code='OLD-1', market='coupang', status='confirmed'):
    db.add(CategoryMapRow(source_id='musinsa', source_path='여성의류>원피스',
                          market=market, market_cat_code=code,
                          market_cat_path='여성>원피스', status=status))
    db.commit()


def _새방식(db, code='NEW-1', market='coupang', status=NC.MAPPED, note=None,
          이어둠=True):
    정규 = NC.NormalizedCategory(path='여성>원피스', depth=1)
    db.add(정규)
    db.commit()
    db.add(NC.SourceCategoryLink(
        source_id='musinsa', source_path='여성의류>원피스',
        normalized_category_id=정규.id if 이어둠 else None))
    db.add(NC.MarketCategoryLink(normalized_category_id=정규.id, market=market,
                                 market_cat_code=code, status=status, note=note))
    db.commit()
    return 정규


# ── 옛 방식이 이긴다 ──────────────────────────────────────────────────────

def test_옛_방식이_있으면_그대로_나간다(db):
    """🔴 지금까지 잘 나가던 상품의 카테고리가 **한 개도 안 바뀌어야** 한다."""
    _옛방식(db, code='OLD-1')
    _새방식(db, code='NEW-1')
    assert _mapped_category(db, _Draft(), 'coupang') == 'OLD-1'


def test_옛_방식만_있어도_나간다(db):
    _옛방식(db, code='OLD-1')
    assert _mapped_category(db, _Draft(), 'coupang') == 'OLD-1'


def test_옛_방식이_확정이_아니면_안_쓴다(db):
    """제안은 제안일 뿐이다 — 확정된 것만 나간다."""
    _옛방식(db, code='OLD-1', status='suggested')
    assert _mapped_category(db, _Draft(), 'coupang') is None


# ── 새 방식이 빈자리를 채운다 ─────────────────────────────────────────────

def test_옛_방식이_없으면_새_방식을_쓴다(db):
    _새방식(db, code='NEW-1')
    assert _mapped_category(db, _Draft(), 'coupang') == 'NEW-1'


def test_아직_안_이었으면_안_나간다(db):
    """보류함에 있는 것은 카테고리가 없는 것이다 — 지어내지 않는다."""
    _새방식(db, code='NEW-1', 이어둠=False)
    assert _mapped_category(db, _Draft(), 'coupang') is None


def test_다른_마켓_연결은_안_쓴다(db):
    """🔴 쿠팡 코드를 롯데온에 보내면 등록이 거부된다."""
    _새방식(db, code='NEW-1', market='coupang')
    assert _mapped_category(db, _Draft(), 'lotteon') is None


def test_소싱처_정보가_없으면_안_찾는다(db):
    class _빈:
        source_site = ''
        source_category_path = ''
    assert _mapped_category(db, _빈(), 'coupang') is None


# ── 못 올리는 분류 ────────────────────────────────────────────────────────

def test_못_올림이면_코드를_안_돌려준다(db):
    """🔴 그 분류로 올리면 마켓이 거부한다."""
    _새방식(db, code='NEW-1', status=NC.BLOCKED, note='계정 권한상 못 쓰는 분류')
    assert _mapped_category(db, _Draft(), 'coupang') is None


def test_인증_필요도_코드를_안_돌려준다(db):
    _새방식(db, code='NEW-1', status=NC.REQUIRES_CERT, note='KC인증 필요')
    assert _mapped_category(db, _Draft(), 'coupang') is None


def test_왜_못_올리는지_사유를_말한다(db):
    """🔴 「카테고리가 없습니다」로만 끝내면 「이미 이었는데?」 하고 헤맨다."""
    _새방식(db, code='NEW-1', status=NC.BLOCKED, note='계정 권한상 못 쓰는 분류')
    사유 = blocked_category_reason(db, _Draft(), 'coupang')
    assert 사유 and '못 올림' in 사유
    assert '계정 권한상' in 사유


def test_잘_이어진_것엔_사유가_없다(db):
    _새방식(db, code='NEW-1')
    assert blocked_category_reason(db, _Draft(), 'coupang') is None


def test_아직_안_이은_것도_사유가_없다(db):
    """「아직 안 이음」은 원래 안내가 따로 있다 — 두 번 말하지 않는다."""
    _새방식(db, code='NEW-1', 이어둠=False)
    assert blocked_category_reason(db, _Draft(), 'coupang') is None


# ── 읽다 실패해도 전송이 안 멈춘다 ───────────────────────────────────────

def test_새_표가_없어도_옛_방식은_돈다():
    """🔴 읽기 실패로 전송을 멈추면 잘 나가던 상품이 조용히 죽는다."""
    eng = create_engine('sqlite:///:memory:')
    CategoryMapRow.__table__.create(bind=eng)     # 옛 표만 만든다
    s = sessionmaker(bind=eng)()
    try:
        s.add(CategoryMapRow(source_id='musinsa', source_path='여성의류>원피스',
                             market='coupang', market_cat_code='OLD-1',
                             market_cat_path='여성>원피스', status='confirmed'))
        s.commit()
        assert _mapped_category(s, _Draft(), 'coupang') == 'OLD-1'
        assert blocked_category_reason(s, _Draft(), 'coupang') is None
    finally:
        s.close()


# ── 화면이 사유를 실제로 보여주나 ────────────────────────────────────────

def test_전송_점검이_막힌_사유를_쓴다():
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'webapp' / 'routes' / 'bulk' / 'drafts.py').read_text(encoding='utf-8')
    assert 'blocked_category_reason(session, draft, market)' in 소스
    assert '다른 분류로 이어 주세요' in 소스
