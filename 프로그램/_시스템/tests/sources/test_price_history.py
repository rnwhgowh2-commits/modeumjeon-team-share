# -*- coding: utf-8 -*-
"""[TEST] 소싱처 가격·재고 이력 — 노션 ④「가격변동은 그래프」의 데이터.

사장님 확정 (2026-07-31):
  · 바뀌면 **항상** 남긴다
  · 안 바뀌면 **하루 2회까지만** 남긴다

여기서 못 박는 것:
  · 값이 하나도 없는 크롤은 남기지 않는다 — 빈 점이 「그날 0원」으로 읽힌다
  · 재고 0(품절)과 None(확인 불가)은 다른 값이라 둘 다 남는다
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
from lemouton.sources import price_history as PH
from lemouton.sources.models import SourcePriceHistory as H, SourceProduct

DAY = dt.datetime(2026, 7, 31, 9, 0, tzinfo=dt.timezone.utc)


@pytest.fixture()
def db():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    s = Session(eng)
    sp = SourceProduct(site='musinsa', url='https://m.example/1')
    s.add(sp)
    s.commit()
    yield s, sp
    s.close()


def _snap(price=10000, stock=5):
    return [{'color_text': '블랙', 'size_text': '260', 'price': price, 'stock': stock}]


def test_바뀌면_언제나_남긴다(db):
    s, sp = db
    for i in range(5):
        n = PH.record(s, source_product=sp, snapshot=_snap(10000 + i), changed=True,
                      now=DAY + dt.timedelta(hours=i))
        assert n == 1
    s.commit()
    assert s.query(H).count() == 5


def test_안_바뀌면_하루_두_번까지만(db):
    s, sp = db
    got = [PH.record(s, source_product=sp, snapshot=_snap(), changed=False,
                     now=DAY + dt.timedelta(hours=i)) or 0 for i in range(5)]
    s.commit()
    assert got == [1, 1, 0, 0, 0], '세 번째부터는 안 남겨야 한다'
    assert s.query(H).count() == 2


def test_날이_바뀌면_다시_두_번(db):
    s, sp = db
    for i in range(3):
        PH.record(s, source_product=sp, snapshot=_snap(), changed=False,
                  now=DAY + dt.timedelta(hours=i))
    s.commit()
    PH.record(s, source_product=sp, snapshot=_snap(), changed=False,
              now=DAY + dt.timedelta(days=1))
    s.commit()
    assert s.query(H).count() == 3


def test_안_바뀐_한도는_바뀐_기록을_막지_않는다(db):
    """가격이 실제로 움직인 날은 몇 번이든 남아야 한다 — 그게 그래프의 핵심이다."""
    s, sp = db
    for i in range(2):
        PH.record(s, source_product=sp, snapshot=_snap(), changed=False,
                  now=DAY + dt.timedelta(hours=i))
    s.commit()
    n = PH.record(s, source_product=sp, snapshot=_snap(9000), changed=True,
                  now=DAY + dt.timedelta(hours=3))
    s.commit()
    assert n == 1
    assert s.query(H).filter(H.changed.is_(True)).count() == 1


def test_값이_하나도_없으면_남기지_않는다(db):
    """빈 점이 찍히면 「그날 0원이었다」로 읽힌다."""
    s, sp = db
    n = PH.record(s, source_product=sp,
                  snapshot=[{'color_text': '블랙', 'size_text': '260',
                             'price': None, 'stock': None}],
                  changed=False, now=DAY)
    s.commit()
    assert n == 0
    assert s.query(H).count() == 0


def test_품절과_확인불가는_둘_다_남는다(db):
    """0(품절)과 None(확인 불가)은 다른 뜻이라 뭉개지 않는다."""
    s, sp = db
    PH.record(s, source_product=sp,
              snapshot=[{'color_text': '블랙', 'size_text': '260',
                         'price': 10000, 'stock': 0},
                        {'color_text': '블랙', 'size_text': '270',
                         'price': 10000, 'stock': None}],
              changed=True, now=DAY)
    s.commit()
    stocks = sorted([h.stock for h in s.query(H).all()], key=lambda x: (x is None, x))
    assert stocks == [0, None]


def test_소싱처_이름을_함께_남긴다(db):
    """그래프는 소싱처별로 선을 나눈다 — 매번 조인하지 않게 site 를 같이 적는다."""
    s, sp = db
    PH.record(s, source_product=sp, snapshot=_snap(), changed=True, now=DAY)
    s.commit()
    assert s.query(H).first().site == 'musinsa'


def test_그래프용_점을_시간_순서로_준다(db):
    s, sp = db
    for i in range(3):
        PH.record(s, source_product=sp, snapshot=_snap(10000 + i * 100), changed=True,
                  now=DAY + dt.timedelta(hours=i))
    s.commit()
    pts = PH.series_for(s, source_product_ids=[sp.id], days=30,
                        now=DAY + dt.timedelta(hours=4))
    assert [p['surface_price'] for p in pts] == [10000, 10100, 10200]
    assert all(p['site'] == 'musinsa' for p in pts)


def test_옵션을_주면_그_옵션만_준다(db):
    s, sp = db
    PH.record(s, source_product=sp,
              snapshot=[{'color_text': '블랙', 'size_text': '260',
                         'price': 10000, 'stock': 1},
                        {'color_text': '화이트', 'size_text': '260',
                         'price': 20000, 'stock': 1}],
              changed=True, now=DAY)
    s.commit()
    pts = PH.series_for(s, source_product_ids=[sp.id], color='화이트', size='260',
                        now=DAY + dt.timedelta(hours=1))
    assert [p['surface_price'] for p in pts] == [20000]
