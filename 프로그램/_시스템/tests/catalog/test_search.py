# -*- coding: utf-8 -*-
"""캐시 검색 — 이름·브랜드·상품번호. 마켓에 묻지 않고 우리 DB 에서만.

★ 6마켓 중 4곳이 상품명 검색을 못 한다(스마트스토어·롯데온 불가, 옥션·G마켓 무시).
  그래서 캐시에서 찾는 이 길이 유일하다.
"""
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from lemouton.catalog import search as S
from lemouton.catalog.models import (
    MarketProduct, MarketProductCount, MarketProductGroup,
)
from shared.db import Base


def _session():
    engine = sa.create_engine('sqlite://')
    Base.metadata.create_all(engine, tables=[
        MarketProduct.__table__, MarketProductCount.__table__,
        MarketProductGroup.__table__,
    ])
    return sessionmaker(bind=engine)()


def _add(s, **kw):
    base = dict(market='lotteon', account_key='브랜드위시',
                market_product_id='LO1', name='아디다스골프 썬 햇 모자',
                brand='아디다스', status='sale', sale_price=31900)
    base.update(kw)
    s.add(MarketProduct(**base))
    s.commit()


def test_상품명_일부로_찾는다():
    s = _session()
    _add(s, market_product_id='LO1', name='아디다스골프 썬 햇 모자')
    _add(s, market_product_id='LO2', name='나이키 조던 팬츠', brand='나이키')
    out = S.search(s, '썬 햇')
    assert [r['market_product_id'] for r in out['rows']] == ['LO1']
    assert out['total'] == 1


def test_대소문자_상관없이_찾는다():
    s = _session()
    _add(s, market_product_id='LO1', name='FILA 페이토 샌들')
    assert S.search(s, 'fila')['total'] == 1


def test_브랜드로도_찾는다():
    s = _session()
    _add(s, market_product_id='LO1', name='썬 햇', brand='아디다스')
    assert S.search(s, '아디다스')['total'] == 1


def test_상품번호로_정확히_찾는다():
    s = _session()
    _add(s, market_product_id='LO2727575855', name='썬 햇')
    assert S.search(s, 'LO2727575855')['total'] == 1


def test_사이트_상품번호로도_찾는다():
    """옥션·G마켓은 사장님이 사이트 번호를 보신다."""
    s = _session()
    _add(s, market='auction', market_product_id='5806568636',
         site_product_id='F292819719', name='필라 샌들')
    assert S.search(s, 'F292819719')['total'] == 1


def test_지운_상품은_안_나온다():
    """마켓에서 사라진 것을 담으라고 보여주면 안 된다."""
    from datetime import datetime, timezone
    s = _session()
    _add(s, market_product_id='LO1', name='썬 햇')
    r = s.query(MarketProduct).one()
    r.deleted_at = datetime.now(timezone.utc)
    s.commit()
    assert S.search(s, '썬 햇')['total'] == 0


def test_마켓으로_좁힐_수_있다():
    s = _session()
    _add(s, market='lotteon', market_product_id='LO1', name='썬 햇')
    _add(s, market='coupang', market_product_id='CP1', name='썬 햇')
    assert S.search(s, '썬 햇', market='coupang')['total'] == 1


def test_상태로_좁힐_수_있다():
    s = _session()
    _add(s, market_product_id='LO1', name='썬 햇', status='sale')
    _add(s, market_product_id='LO2', name='썬 햇 둘', status='soldout')
    assert S.search(s, '썬 햇', status='soldout')['total'] == 1


def test_이미_담은_것만_또는_아직_안_담은_것만():
    s = _session()
    g = MarketProductGroup(name='묶음'); s.add(g); s.commit()
    _add(s, market_product_id='LO1', name='썬 햇', group_id=g.id)
    _add(s, market_product_id='LO2', name='썬 햇 둘')
    assert S.search(s, '썬 햇', picked=True)['total'] == 1
    assert S.search(s, '썬 햇', picked=False)['total'] == 1


def test_검색어가_없으면_최근_것을_보여준다():
    """빈 화면 대신 뭐라도 보여야 사장님이 시작할 수 있다."""
    s = _session()
    _add(s, market_product_id='LO1', name='가')
    _add(s, market_product_id='LO2', name='나')
    out = S.search(s, '')
    assert out['total'] == 2


def test_한_번에_너무_많이_돌려주지_않는다():
    """28만 건을 통째로 보내면 화면이 멈춘다."""
    s = _session()
    for i in range(120):
        _add(s, market_product_id=f'LO{i}', name=f'상품 {i}')
    out = S.search(s, '상품', limit=50)
    assert len(out['rows']) == 50
    assert out['total'] == 120          # 총 몇 건인지는 알려준다


def test_다음_쪽을_볼_수_있다():
    s = _session()
    for i in range(30):
        _add(s, market_product_id=f'LO{i}', name=f'상품 {i}')
    first = S.search(s, '상품', limit=10)
    second = S.search(s, '상품', limit=10, offset=10)
    ids1 = {r['market_product_id'] for r in first['rows']}
    ids2 = {r['market_product_id'] for r in second['rows']}
    assert not (ids1 & ids2), '같은 상품이 두 쪽에 겹쳐 나온다'


def test_결과에_화면이_필요한_것이_다_들어있다():
    s = _session()
    _add(s, market_product_id='LO1', name='썬 햇', brand='아디다스',
         status='sale', sale_price=31900)
    r = S.search(s, '썬 햇')['rows'][0]
    for k in ('id', 'market', 'account_key', 'market_product_id', 'name',
              'brand', 'status', 'sale_price', 'group_id'):
        assert k in r, k


def test_퍼센트_기호를_넣어도_전체가_안_나온다():
    """★ '%' 는 SQL 에서 '아무거나'다 — 그대로 넘기면 전체가 나온다."""
    s = _session()
    _add(s, market_product_id='LO1', name='썬 햇')
    _add(s, market_product_id='LO2', name='조던 팬츠')
    assert S.search(s, '%')['total'] == 0
