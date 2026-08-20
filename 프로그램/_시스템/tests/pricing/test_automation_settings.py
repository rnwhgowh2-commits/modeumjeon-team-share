import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from shared.db import Base
import lemouton.pricing.settings as st


@pytest.fixture
def db():
    eng = create_engine("sqlite://"); Base.metadata.create_all(eng)
    s = Session(eng); yield s; s.close()


def test_automation_defaults(db):
    a = st.get_automation(db)
    assert a["autosend_mode"] == "preview"        # 안전 기본
    assert a["autosend_stock_threshold"] == 4
    assert a["crawl_auto_enabled"] is False


def test_automation_save_roundtrip(db):
    st.save_automation(db, {"crawl_auto_enabled": True, "crawl_interval_hours": 2,
                            "crawl_interval_minutes": 30, "autosend_mode": "real",
                            "autosend_stock_threshold": 6}); db.commit()
    a = st.get_automation(db)
    assert a["crawl_auto_enabled"] is True and a["crawl_interval_hours"] == 2
    assert a["crawl_interval_minutes"] == 30 and a["autosend_mode"] == "real"
    assert a["autosend_stock_threshold"] == 6


def test_automation_validation(db):
    # 분 60 -> 59 클램프, mode 이상값 -> preview, 음수 -> 0
    st.save_automation(db, {"crawl_interval_minutes": 90, "autosend_mode": "xxx",
                            "autosend_stock_threshold": -3}); db.commit()
    a = st.get_automation(db)
    assert a["crawl_interval_minutes"] == 59 and a["autosend_mode"] == "preview"
    assert a["autosend_stock_threshold"] == 0
