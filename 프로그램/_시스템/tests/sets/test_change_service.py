"""변동 기록 서비스 record_change 테스트 (in-memory SQLite)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models", "lemouton.sets.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

from lemouton.sets.models import ChannelChangeEvent
from lemouton.sets import change_service


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def test_record_change_creates_event(db):
    """8→0 변동: True 반환, 이벤트 1행 저장, next_value==0."""
    result = change_service.record_change(
        db,
        set_id=6,
        market="coupang",
        canonical_sku="X",
        field="stock",
        source="market",
        prev_value=8,
        next_value=0,
    )
    db.commit()

    assert result is True
    events = db.query(ChannelChangeEvent).all()
    assert len(events) == 1
    assert events[0].next_value == 0


def test_record_change_same_value_no_event(db):
    """0→0 동일값: False 반환, 이벤트 0행."""
    result = change_service.record_change(
        db,
        set_id=6,
        market="coupang",
        canonical_sku="X",
        field="stock",
        source="market",
        prev_value=0,
        next_value=0,
    )
    db.commit()

    assert result is False
    events = db.query(ChannelChangeEvent).all()
    assert len(events) == 0
