import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from shared.db import Base
# create_all 은 전체 FK 그래프가 등록돼야 성공 — 앱 부트와 동일한 모델 세트 등록.
import lemouton.sourcing.models  # noqa: F401
import lemouton.sourcing.models_pricing  # noqa: F401
import lemouton.uploader.models  # noqa: F401
import lemouton.templates.models  # noqa: F401
import lemouton.inventory.models  # noqa: F401
import lemouton.sets.models  # noqa: F401
import lemouton.sources.models  # noqa: F401
import lemouton.sourcing.models_v2  # noqa: F401
import lemouton.multitenancy.models  # noqa: F401
import lemouton.audit.models  # noqa: F401
import lemouton.mapping.models  # noqa: F401
from lemouton.sourcing.models_v2 import UploadAccount
from lemouton.pricing import settings as st
from lemouton.pricing.settings import AccountUploadPolicy  # noqa
from lemouton.uploader.throttle import seconds_to_hourly, market_hourly_total


@pytest.fixture
def db():
    eng = create_engine("sqlite://"); Base.metadata.create_all(eng)
    s = Session(eng); yield s; s.close()


def test_seconds_to_hourly():
    assert seconds_to_hourly(6) == 600
    assert seconds_to_hourly(4) == 900
    assert seconds_to_hourly(0) == 3600     # 0 → 1초로 방어
    assert seconds_to_hourly(3600) == 1


def test_market_total_sums_enabled_accounts(db):
    for nm, sec in [("본계정", 6), ("세컨", 6), ("아울렛", 8)]:
        a = UploadAccount(account_key=f"t_{nm}", display_name=nm,
                          market="smartstore", env_prefix=f"T_{nm}", is_active=True)
        db.add(a); db.flush()
        db.add(AccountUploadPolicy(account_id=a.id, seconds_per_item=sec, enabled=True))
    # 꺼진 계정은 합산 제외
    a2 = UploadAccount(account_key="t_정지계정", display_name="정지계정",
                       market="smartstore", env_prefix="T_STOP", is_active=True)
    db.add(a2); db.flush()
    db.add(AccountUploadPolicy(account_id=a2.id, seconds_per_item=6, enabled=False))
    db.flush()
    # 600 + 600 + 450 = 1650 (정지계정 600 제외)
    assert market_hourly_total(db, "smartstore") == 1650
    assert market_hourly_total(db, "coupang") == 0
