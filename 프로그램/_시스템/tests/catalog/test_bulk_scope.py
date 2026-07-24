# -*- coding: utf-8 -*-
"""대량등록 탭 — 우리가 대량등록으로 올린 상품 현황.

★ [2026-07-24 라이브에서 발견] 탭을 눌러도 내용이 하나도 안 바뀌었다(거짓 기능).
  파란 표시만 옮겨가고 같은 숫자를 보여줬다 — 눌러도 아무 일 없는 버튼은 만들면 안 된다.
"""
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from lemouton.catalog.bulk_scope import bulk_counts
from lemouton.registration.models import ProductDraft, ProductDraftMarket
from shared.db import Base


def _session():
    engine = sa.create_engine('sqlite://')
    Base.metadata.create_all(engine, tables=[
        ProductDraft.__table__, ProductDraftMarket.__table__,
    ])
    return sessionmaker(bind=engine)()


def _draft(s, name='상품'):
    d = ProductDraft(name=name, sale_price=1000)
    s.add(d); s.commit()
    return d


def _mk(s, draft, market, account_key='default', status='ok', pid='P1'):
    m = ProductDraftMarket(draft_id=draft.id, market=market,
                           account_key=account_key, status=status,
                           market_product_id=pid)
    s.add(m); s.commit()
    return m


def test_마켓_계정별로_센다():
    s = _session()
    d = _draft(s)
    _mk(s, d, 'coupang', '브랜드마켓쿠팡', 'ok', 'C1')
    _mk(s, d, 'lotteon', '브랜드위시', 'ok', 'L1')
    out = bulk_counts(s)
    assert out['coupang']['브랜드마켓쿠팡']['sale'] == 1
    assert out['lotteon']['브랜드위시']['sale'] == 1


def test_등록된_것만_판매중으로_센다():
    """★ 아직 못 올린 것을 '판매중'이라 하면 거짓말이다.

    같은 상품×마켓×계정은 한 줄뿐이라(유니크 제약) 상품 3개로 만든다.
    """
    s = _session()
    _mk(s, _draft(s, '올라간 상품'), 'coupang', 'A', 'ok', 'C1')
    _mk(s, _draft(s, '아직 안 올린 상품'), 'coupang', 'A', 'pending', None)
    _mk(s, _draft(s, '실패한 상품'), 'coupang', 'A', 'failed', None)
    got = bulk_counts(s)['coupang']['A']
    assert got['sale'] == 1
    assert got['waiting'] == 1          # 아직 안 올림
    assert got['unknown'] == 1          # 실패 — 마켓에 있는지 모른다


def test_확인_전_잠금은_모름으로_센다():
    """★ uncertain = 마켓에 있을 수도 없을 수도. '판매중'으로 세면 안 된다."""
    s = _session()
    d = _draft(s)
    _mk(s, d, 'coupang', 'A', 'uncertain', None)
    assert bulk_counts(s)['coupang']['A']['unknown'] == 1


def test_막힌_것은_아직_안_올린_것으로():
    s = _session()
    d = _draft(s)
    _mk(s, d, 'coupang', 'A', 'blocked', None)
    assert bulk_counts(s)['coupang']['A']['waiting'] == 1


def test_아무것도_없으면_빈_결과():
    assert bulk_counts(_session()) == {}


def test_지운_드래프트는_빼고_센다():
    from datetime import datetime, timezone
    s = _session()
    d = _draft(s)
    _mk(s, d, 'coupang', 'A', 'ok', 'C1')
    d.deleted_at = datetime.now(timezone.utc); s.commit()
    assert bulk_counts(s) == {}
