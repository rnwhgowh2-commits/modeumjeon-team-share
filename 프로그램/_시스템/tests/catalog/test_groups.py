# -*- coding: utf-8 -*-
"""묶기 — 흩어진 마켓 상품을 한 상품으로.

확정 시안 ⑤ 「대표를 정하고 붙이기」: 기준 상품 하나를 세우고 나머지를 붙인다.
"""
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from lemouton.catalog import groups as G
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


def _add(s, pid, **kw):
    base = dict(market='lotteon', account_key='브랜드위시',
                market_product_id=pid, name=f'상품 {pid}',
                brand='아디다스', status='sale')
    base.update(kw)
    m = MarketProduct(**base)
    s.add(m); s.commit()
    return m


def test_대표를_정하면_묶음이_생기고_그_상품이_붙는다():
    s = _session()
    a = _add(s, 'LO1', name='아디다스골프 썬 햇 모자')
    g = G.create_group(s, leader_id=a.id)
    assert g['name'] == '아디다스골프 썬 햇 모자'
    assert g['brand'] == '아디다스'
    assert s.get(MarketProduct, a.id).group_id == g['id']


def test_이름을_직접_줄_수도_있다():
    s = _session()
    a = _add(s, 'LO1', name='<매장정품> 어쩌고')
    g = G.create_group(s, leader_id=a.id, name='아디다스 썬 햇')
    assert g['name'] == '아디다스 썬 햇'


def test_나머지를_붙인다():
    s = _session()
    a = _add(s, 'LO1'); b = _add(s, 'CP1', market='coupang')
    c = _add(s, 'E1', market='eleven11')
    g = G.create_group(s, leader_id=a.id)
    n = G.attach(s, g['id'], [b.id, c.id])
    assert n == 2
    assert G.get_group(s, g['id'])['member_count'] == 3


def test_뗄_수도_있다():
    s = _session()
    a = _add(s, 'LO1'); b = _add(s, 'CP1', market='coupang')
    g = G.create_group(s, leader_id=a.id)
    G.attach(s, g['id'], [b.id])
    assert G.detach(s, [b.id]) == 1
    assert s.get(MarketProduct, b.id).group_id is None
    assert G.get_group(s, g['id'])['member_count'] == 1


def test_이미_다른_묶음에_있으면_옮기고_알려준다():
    """★ 조용히 두 곳에 속하면 어느 쪽이 진짜인지 알 수 없다."""
    s = _session()
    a = _add(s, 'LO1'); b = _add(s, 'CP1', market='coupang')
    c = _add(s, 'E1', market='eleven11')
    g1 = G.create_group(s, leader_id=a.id)
    G.attach(s, g1['id'], [b.id])
    g2 = G.create_group(s, leader_id=c.id)
    r = G.attach(s, g2['id'], [b.id], detail=True)
    assert r['moved'] == [{'market_product_id': 'CP1', 'from_group_id': g1['id']}]
    assert s.get(MarketProduct, b.id).group_id == g2['id']


def test_같은_묶음에_다시_붙여도_옮겼다고_하지_않는다():
    s = _session()
    a = _add(s, 'LO1'); b = _add(s, 'CP1', market='coupang')
    g = G.create_group(s, leader_id=a.id)
    G.attach(s, g['id'], [b.id])
    r = G.attach(s, g['id'], [b.id], detail=True)
    assert r['moved'] == []


def test_없는_상품을_붙이려_하면_알려준다():
    s = _session()
    a = _add(s, 'LO1')
    g = G.create_group(s, leader_id=a.id)
    with pytest.raises(ValueError, match='없는 상품'):
        G.attach(s, g['id'], [99999])


def test_없는_묶음에_붙이려_하면_알려준다():
    s = _session()
    a = _add(s, 'LO1')
    with pytest.raises(ValueError, match='없는 묶음'):
        G.attach(s, 99999, [a.id])


def test_지운_상품은_대표로_못_세운다():
    """마켓에서 사라진 것을 대표로 삼으면 빈 묶음이 된다."""
    from datetime import datetime, timezone
    s = _session()
    a = _add(s, 'LO1')
    a.deleted_at = datetime.now(timezone.utc); s.commit()
    with pytest.raises(ValueError, match='사라진 상품'):
        G.create_group(s, leader_id=a.id)


def test_묶음_목록은_붙은_상품과_마켓을_같이_준다():
    s = _session()
    a = _add(s, 'LO1'); b = _add(s, 'CP1', market='coupang')
    g = G.create_group(s, leader_id=a.id)
    G.attach(s, g['id'], [b.id])
    lst = G.list_groups(s)
    assert lst['total'] == 1
    row = lst['rows'][0]
    assert row['member_count'] == 2
    assert sorted(row['markets']) == ['coupang', 'lotteon']


def test_가격은_한_값으로_뭉개지_않고_범위로_준다():
    """★ 마켓마다 값이 다르다 — 하나로 합치면 어느 마켓 값인지 알 수 없다."""
    s = _session()
    a = _add(s, 'LO1', sale_price=31900)
    b = _add(s, 'CP1', market='coupang', sale_price=32900)
    g = G.create_group(s, leader_id=a.id)
    G.attach(s, g['id'], [b.id])
    row = G.list_groups(s)['rows'][0]
    assert row['price_min'] == 31900
    assert row['price_max'] == 32900


def test_가격을_모르면_범위도_비운다():
    s = _session()
    a = _add(s, 'LO1', sale_price=None)
    G.create_group(s, leader_id=a.id)
    row = G.list_groups(s)['rows'][0]
    assert row['price_min'] is None
    assert row['price_max'] is None


def test_품절이나_중지가_섞였으면_알려준다():
    s = _session()
    a = _add(s, 'LO1', status='sale')
    b = _add(s, 'CP1', market='coupang', status='soldout')
    g = G.create_group(s, leader_id=a.id)
    G.attach(s, g['id'], [b.id])
    row = G.list_groups(s)['rows'][0]
    assert row['has_soldout'] is True
    assert row['has_stopped'] is False


def test_묶음_상세는_마켓별_카드에_필요한_것을_준다():
    """확정 시안 ⑥ — 마켓마다 카드 한 장."""
    s = _session()
    a = _add(s, 'LO1', sale_price=31900)
    b = _add(s, 'CP1', market='coupang', sale_price=32900, status='stopped')
    g = G.create_group(s, leader_id=a.id)
    G.attach(s, g['id'], [b.id])
    d = G.get_group(s, g['id'])
    got = {m['market']: m for m in d['members']}
    assert got['lotteon']['sale_price'] == 31900
    assert got['coupang']['status'] == 'stopped'
    assert got['coupang']['market_product_id'] == 'CP1'


def test_묶음을_지우면_붙었던_상품이_풀린다():
    """★ 상품까지 지우면 안 된다 — 마켓엔 그대로 있다."""
    s = _session()
    a = _add(s, 'LO1')
    g = G.create_group(s, leader_id=a.id)
    G.delete_group(s, g['id'])
    assert s.get(MarketProduct, a.id).group_id is None
    assert s.query(MarketProduct).count() == 1


def test_지운_묶음은_목록에_안_나온다():
    s = _session()
    a = _add(s, 'LO1')
    g = G.create_group(s, leader_id=a.id)
    G.delete_group(s, g['id'])
    assert G.list_groups(s)['total'] == 0
    assert G.get_group(s, g['id']) is None


def test_묶음_이름으로_찾을_수_있다():
    s = _session()
    a = _add(s, 'LO1', name='아디다스 썬 햇')
    b = _add(s, 'CP1', market='coupang', name='나이키 팬츠')
    G.create_group(s, leader_id=a.id)
    G.create_group(s, leader_id=b.id)
    assert G.list_groups(s, q='아디다스')['total'] == 1
