import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
from lemouton.pricing import settings as st
from lemouton.pricing.settings import MarketUploadPolicy  # noqa: F401 (등록용)


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def test_defaults_seeded_for_known_markets(db):
    pol = st.get_market_policies(db)
    db.commit()
    assert pol["coupang"]["per_minute"] == 10
    assert pol["coupang"]["enabled"] is True
    assert pol["smartstore"]["per_minute"] == 10


def test_set_updates_only_given_fields(db):
    st.get_market_policies(db)  # seed
    st.set_market_policy(db, "coupang", per_minute=3)
    db.commit()
    pol = st.get_market_policies(db)
    assert pol["coupang"]["per_minute"] == 3
    assert pol["coupang"]["enabled"] is True   # 안 건드린 값 유지


def test_set_validates_non_negative(db):
    st.get_market_policies(db)
    st.set_market_policy(db, "smartstore", per_minute=-5)
    db.commit()
    pol = st.get_market_policies(db)
    assert pol["smartstore"]["per_minute"] == 0   # 음수 → 0 클램프


def test_set_enabled_toggle(db):
    st.get_market_policies(db)
    st.set_market_policy(db, "coupang", enabled=False)
    db.commit()
    assert st.get_market_policies(db)["coupang"]["enabled"] is False
