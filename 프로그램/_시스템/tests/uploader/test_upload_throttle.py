import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
from lemouton.pricing import settings as st
from lemouton.pricing.settings import MarketUploadPolicy  # noqa: F401
from lemouton.uploader.throttle import (
    upload_allowance, throttle_take, market_send_allowance,
)


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def test_allowance_basic():
    assert upload_allowance(10, 0) == 10
    assert upload_allowance(10, 7) == 3
    assert upload_allowance(10, 10) == 0
    assert upload_allowance(10, 15) == 0   # 이미 초과 → 0 (음수 아님)
    assert upload_allowance(0, 0) == 0      # 상한 0 = 안 보냄


def test_throttle_take_splits():
    items = [1, 2, 3, 4, 5]
    now, later = throttle_take(items, 2)
    assert now == [1, 2] and later == [3, 4, 5]
    now, later = throttle_take(items, 0)
    assert now == [] and later == [1, 2, 3, 4, 5]
    now, later = throttle_take(items, 99)
    assert now == [1, 2, 3, 4, 5] and later == []


def test_market_send_allowance_reads_policy(db):
    st.get_market_policies(db)                       # 기본 coupang per_minute 10
    st.set_market_policy(db, "coupang", per_minute=5)
    db.commit()
    assert market_send_allowance(db, "coupang", sent_last_minute=2) == 3


def test_disabled_market_allows_nothing(db):
    st.get_market_policies(db)
    st.set_market_policy(db, "coupang", enabled=False)
    db.commit()
    assert market_send_allowance(db, "coupang", sent_last_minute=0) == 0


def test_unknown_market_defaults_to_zero(db):
    # 정책 없는 낯선 마켓 → 안전하게 0 (함부로 보내지 않음)
    assert market_send_allowance(db, "elevenst", sent_last_minute=0) == 0
