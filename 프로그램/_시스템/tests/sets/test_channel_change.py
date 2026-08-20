"""판매처 현재값 컬럼 + 변동이력 테이블 테스트 (in-memory SQLite)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

# FK 타겟 모델 전체 등록 (test_channel_service.py 패턴 동일)
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

from lemouton.sets.models import SetChannelOption, ChannelChangeEvent


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


# ── Task 1: SetChannelOption 현재값 컬럼 ─────────────────────────────────────

def test_set_channel_option_market_columns(db):
    """mkt_stock / mkt_price / mkt_fetched_at 컬럼 저장·조회."""
    obj = SetChannelOption(
        channel_id=1,
        canonical_sku="X",
        status="matched",
        mkt_stock=5,
        mkt_price=133900,
    )
    db.add(obj)
    db.commit()
    db.expire(obj)

    assert obj.mkt_stock == 5
    assert obj.mkt_price == 133900
    assert obj.mkt_fetched_at is None


# ── Task 2: ChannelChangeEvent 변동이력 테이블 ─────────────────────────────────

def test_channel_change_event_insert(db):
    """ChannelChangeEvent 저장 후 id 부여·field·next_value 검증."""
    evt = ChannelChangeEvent(
        set_id=6,
        market="coupang",
        canonical_sku="X",
        field="stock",
        source="market",
        prev_value=8,
        next_value=0,
    )
    db.add(evt)
    db.commit()
    db.expire(evt)

    assert evt.id is not None
    assert evt.field == "stock"
    assert evt.next_value == 0
