import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
# create_all 은 전체 FK 그래프가 등록돼야 성공 — 앱 부트와 동일한 모델 세트 등록.
# (multitenancy.models 만 임포트하면 bundle_account_registrations→models→size_templates
#  FK 타겟이 없어 NoReferencedTableError. 앱은 app.py 에서 아래 모듈을 모두 임포트한다.)
import lemouton.sourcing.models  # noqa: F401
import lemouton.sourcing.models_pricing  # noqa: F401
import lemouton.uploader.models  # noqa: F401
import lemouton.templates.models  # noqa: F401
import lemouton.inventory.models  # noqa: F401
import lemouton.sets.models  # noqa: F401
import lemouton.sources.models  # noqa: F401
import lemouton.sourcing.models_v2  # noqa: F401
import lemouton.multitenancy.models  # noqa: F401  # market_accounts 등록
import lemouton.audit.models  # noqa: F401
import lemouton.mapping.models  # noqa: F401
from lemouton.sourcing.models_v2 import UploadAccount
from lemouton.pricing import settings as st
from lemouton.pricing.settings import AccountUploadPolicy  # noqa: F401


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng); yield s; s.close()


def _acc(db, market, name, active=True):
    a = UploadAccount(account_key=f"{market}_{name}", display_name=name,
                      market=market, env_prefix=f"{market}_{name}".upper(),
                      is_active=active)
    db.add(a); db.flush(); return a


def test_default_seeded_per_active_account(db):
    a = _acc(db, "smartstore", "본계정")
    pol = st.get_account_policies(db); db.commit()
    row = [p for p in pol if p["account_id"] == a.id][0]
    assert row["seconds_per_item"] == 6
    assert row["enabled"] is True
    assert row["per_hour"] == 600            # 3600/6
    assert row["market"] == "smartstore" and row["account_name"] == "본계정"


def test_inactive_account_excluded(db):
    _acc(db, "coupang", "죽은계정", active=False)
    pol = st.get_account_policies(db)
    assert all(p["account_name"] != "죽은계정" for p in pol)


def test_set_updates_and_clamps_min_1(db):
    a = _acc(db, "coupang", "메인")
    st.get_account_policies(db)                    # seed
    st.set_account_policy(db, a.id, seconds_per_item=4); db.commit()
    row = [p for p in st.get_account_policies(db) if p["account_id"] == a.id][0]
    assert row["seconds_per_item"] == 4 and row["per_hour"] == 900
    st.set_account_policy(db, a.id, seconds_per_item=0); db.commit()   # 0 → 1로 클램프
    row = [p for p in st.get_account_policies(db) if p["account_id"] == a.id][0]
    assert row["seconds_per_item"] == 1


def test_set_enabled_toggle(db):
    a = _acc(db, "smartstore", "세컨")
    st.get_account_policies(db)
    st.set_account_policy(db, a.id, enabled=False); db.commit()
    row = [p for p in st.get_account_policies(db) if p["account_id"] == a.id][0]
    assert row["enabled"] is False
