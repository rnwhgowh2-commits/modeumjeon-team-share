# -*- coding: utf-8 -*-
"""[TEST] 가격 이력은 '값이 바뀔 때만' 쌓인다.

왜 필요한가:
  전에는 크롤할 때마다 값이 그대로여도 한 줄씩 넣었다.
  크롤이 60초 간격 연속 모드라 하루 수천 줄이 쌓여 DB 용량을 계속 먹었고,
  결국 Supabase 무료 한도를 넘겨 프로젝트가 멈췄다.

이 시험이 지키는 것:
  같은 가격·재고면 안 쌓는다 / 하나라도 바뀌면 쌓는다.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.db import Base                      # noqa: E402
import lemouton.sourcing.models                 # noqa: E402,F401
import lemouton.sources.models                  # noqa: E402,F401
from lemouton.sourcing.models import Model, Option   # noqa: E402
from lemouton.templates.models import PriceTrackHistory  # noqa: E402
from lemouton.sourcing.bulk_crawl import save_crawl_to_track  # noqa: E402


@pytest.fixture()
def s():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng)()
    sess.add(Model(model_code='M1', model_name_raw='시험모델'))
    sess.add(Option(model_code='M1', canonical_sku='SKU1',
                    color_code='블랙', size_code='270'))
    sess.commit()
    yield sess
    sess.close()


def crawl(price, stock):
    """크롤 결과 흉내 — 색상·사이즈가 우리 옵션과 맞는 1건."""
    return SimpleNamespace(source='musinsa', options=[
        {'color_text': '블랙', 'size_text': '270', 'price': price, 'stock': stock},
    ])


def rows(s):
    return s.query(PriceTrackHistory).count()


def test_first_crawl_saves(s):
    assert save_crawl_to_track(s, 'M1', crawl(10000, 5)) == 1
    assert rows(s) == 1


def test_same_value_is_not_saved(s):
    save_crawl_to_track(s, 'M1', crawl(10000, 5))
    # 값이 그대로 → 안 쌓여야 한다 (이게 없으면 크롤마다 한 줄씩 늘어난다)
    assert save_crawl_to_track(s, 'M1', crawl(10000, 5)) == 0
    assert rows(s) == 1


def test_repeated_same_value_stays_one_row(s):
    save_crawl_to_track(s, 'M1', crawl(10000, 5))
    for _ in range(20):
        save_crawl_to_track(s, 'M1', crawl(10000, 5))
    assert rows(s) == 1, '값이 그대로인데 줄이 늘었다 — 용량 폭증의 원인'


def test_price_change_is_saved(s):
    save_crawl_to_track(s, 'M1', crawl(10000, 5))
    assert save_crawl_to_track(s, 'M1', crawl(9500, 5)) == 1
    assert rows(s) == 2


def test_stock_change_is_saved(s):
    save_crawl_to_track(s, 'M1', crawl(10000, 5))
    assert save_crawl_to_track(s, 'M1', crawl(10000, 0)) == 1
    assert rows(s) == 2


def test_back_to_previous_value_is_saved(s):
    """값이 되돌아온 것도 '바뀐 것' 이다 (품절 → 재입고 같은 경우)."""
    save_crawl_to_track(s, 'M1', crawl(10000, 5))
    save_crawl_to_track(s, 'M1', crawl(10000, 0))
    assert save_crawl_to_track(s, 'M1', crawl(10000, 5)) == 1
    assert rows(s) == 3
