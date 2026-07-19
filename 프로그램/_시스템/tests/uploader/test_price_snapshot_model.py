# -*- coding: utf-8 -*-
"""[TEST] Phase 1B M3-1 — PriceSnapshot 스키마 + 역마진 설정값.

Alembic 이 없으므로 이 테스트가 스키마의 유일한 방어선이다:
  · Base 등록(= create_all 이 만든다) / app.py import(= 안 하면 조용히 테이블 없음)
  · 컬럼 집합 못 박기 — create_all 은 **기존 테이블에 컬럼을 못 붙인다**
  · 문자열 폭 — 개발기 SQLite 는 길이를 무시하지만 라이브 Supabase PostgreSQL 은 안 그렇다
"""
import pytest

from shared.db import Base
from lemouton.uploader.models import PriceSnapshot


@pytest.fixture
def session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.uploader.models  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    Base.metadata.create_all(
        engine, tables=[Base.metadata.tables["price_snapshots"]])
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = Session()
    yield s
    s.close()


# ── 스키마 ──────────────────────────────────────────────────────────────────

def test_model_registered_on_base():
    assert "price_snapshots" in Base.metadata.tables


def test_app_imports_uploader_models():
    """모델을 app.py 가 import 하지 않으면 테이블이 조용히 안 생긴다."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[2] / "app.py"
    assert "import lemouton.uploader.models" in src.read_text(encoding="utf-8")


def test_columns():
    cols = {c.name for c in PriceSnapshot.__table__.columns}
    assert cols == {
        "id",
        "canonical_sku", "market", "account_key", "source_key",
        "surface_price", "final_purchase_price", "upload_price",
        "margin_amount", "stock",
        "steps_json", "action", "priority", "reason_code", "reason",
        "warnings_json",
        "uploaded_at", "created_at",
    }


def test_string_widths_match_house_definitions():
    """라이브(PostgreSQL)에서만 깨지는 폭 초과를 막는다.

    canonical_sku 128 = market_registrations·inventory·multitenancy 와 동일.
    source_key 64 = sources/models.py:211 의 가장 넓은 정의.
    account_key 64 = registration/models.py:ProductDraftMarket 와 동일.
    """
    w = {c.name: getattr(c.type, "length", None)
         for c in PriceSnapshot.__table__.columns}
    assert w["canonical_sku"] == 128
    assert w["market"] == 32
    assert w["account_key"] == 64
    assert w["source_key"] == 64
    assert w["reason_code"] == 32
    assert w["reason"] == 200
    assert w["action"] == 16
    assert w["priority"] == 2


def test_real_reason_sentences_fit_the_column():
    """게이트가 실제로 만드는 한국어 사유가 VARCHAR(200) 안에 들어가는가.

    reason 은 게이트가 만든 문장을 그대로 담는 자리다. 여기서 잘리면
    라이브에서만 StringDataRightTruncation 이 난다(SQLite 는 통과).
    """
    from lemouton.uploader.upload_gate import decide_upload, STOCK_UNKNOWN
    cases = [
        dict(prev_price=1234567, prev_stock=999, new_price=7654321, new_stock=3),
        dict(prev_price=1234567, prev_stock=999, new_price=1234567, new_stock=0),
        dict(prev_price=1234567, prev_stock=5, new_price=1234567, new_stock=4),
        dict(prev_price=1234567, prev_stock=STOCK_UNKNOWN,
             new_price=1234567, new_stock=5),
        dict(prev_price=1234567, prev_stock=5, new_price=None, new_stock=None),
        dict(prev_price=1234567, prev_stock=5, new_price=9999999, new_stock=5,
             margin_amount=-1234567, min_margin_amount=1000000),
    ]
    for kw in cases:
        d = decide_upload(**kw)
        assert len(d.reason) <= 200, (len(d.reason), d.reason)
        assert len(d.reason_code) <= 32


def test_priority_codes_fit_two_chars():
    from lemouton.uploader.upload_gate import PRIORITIES
    assert all(len(p) == 2 for p in PRIORITIES)


# ── 이력 테이블이다 (M4 주문 시점 대조의 근거) ───────────────────────────────

def test_same_target_can_have_many_rows(session):
    """(sku, market, account_key) 에 UNIQUE 를 걸지 않았다 — 걸면 이력이 뭉개진다."""
    for price in (10000, 11000, 12000):
        session.add(PriceSnapshot(
            canonical_sku="SKU-1", market="smartstore", account_key="default",
            upload_price=price, stock=5, action="upload"))
    session.commit()
    assert session.query(PriceSnapshot).count() == 3


def test_latest_snapshot_lookup_by_id(session):
    """「직전 스냅샷」 = 같은 대상의 최신 id. append-only 라 id 순 = 시간 순."""
    for price in (10000, 11000, 12000):
        session.add(PriceSnapshot(canonical_sku="SKU-1", market="smartstore",
                                  account_key="default", upload_price=price))
    session.add(PriceSnapshot(canonical_sku="SKU-1", market="coupang",
                              account_key="default", upload_price=99999))
    session.commit()
    latest = (session.query(PriceSnapshot)
              .filter_by(canonical_sku="SKU-1", market="smartstore",
                         account_key="default")
              .order_by(PriceSnapshot.id.desc()).first())
    assert latest.upload_price == 12000


def test_steps_json_roundtrip(session):
    """계산근거는 compute_final_price 의 steps 를 요약 없이 그대로 담는다."""
    steps = [{"name": "네이버페이", "type": "rate", "value": 0.02,
              "deduct": 2000, "base_after": 98000},
             {"name": "카드 청구할인", "type": "amount", "value": 5000,
              "deduct": 5000, "base_after": 93000}]
    session.add(PriceSnapshot(canonical_sku="SKU-1", market="smartstore",
                              steps_json=steps,
                              warnings_json=["역마진 경고 — 마진 -500원"]))
    session.commit()
    row = session.query(PriceSnapshot).one()
    assert row.steps_json == steps
    assert row.warnings_json[0].startswith("역마진 경고")


def test_unknown_values_stay_null_not_zero(session):
    """'모름' 과 '0원' 은 다르다. 폴백 금지 원칙이 스키마에서도 성립하는가."""
    session.add(PriceSnapshot(canonical_sku="SKU-1", market="smartstore"))
    session.commit()
    row = session.query(PriceSnapshot).one()
    assert row.surface_price is None
    assert row.final_purchase_price is None
    assert row.upload_price is None
    assert row.stock is None
    assert row.uploaded_at is None       # 스킵/보류는 '올린 시각'이 없다
    assert row.account_key == "default"  # NULL 센티넬 금지
    assert row.action == "upload"


# ── 역마진 설정값 ───────────────────────────────────────────────────────────

def test_min_margin_amount_is_a_global_settings_column():
    from lemouton.pricing.settings import GlobalSettings, _DEFAULTS
    assert "min_margin_amount" in {c.name for c in GlobalSettings.__table__.columns}
    assert _DEFAULTS["min_margin_amount"] == 0   # 기본 0 = 오늘 동작과 동일


def test_min_margin_amount_registered_in_lightweight_migrations():
    """global_settings 는 라이브에 이미 있는 테이블 → create_all 이 컬럼을 못 붙인다.

    shared/db.py 의 ADD COLUMN 목록에 없으면 라이브에서만 컬럼이 없어 500 이 난다.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "shared" / "db.py").read_text(encoding="utf-8")
    assert '("global_settings", "min_margin_amount"' in src


def test_get_and_save_min_margin_amount(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from lemouton.pricing import settings as S

    engine = create_engine(f"sqlite:///{tmp_path/'s.db'}", future=True)
    Base.metadata.create_all(engine,
                             tables=[Base.metadata.tables["global_settings"]])
    s = sessionmaker(bind=engine, future=True, expire_on_commit=False)()
    try:
        assert S.get_min_margin_amount(s) == 0
        assert S.save_min_margin_amount(s, 1500) == 1500
        assert S.get_min_margin_amount(s) == 1500
        # 음수 = "이만큼까지는 손해 봐도 올린다" — 사용자의 유효한 선택
        assert S.save_min_margin_amount(s, -200) == -200
        # 숫자가 아니면 조용히 0 으로 뭉개지 않는다 (가드가 꺼진 줄 모르면 사고)
        with pytest.raises(ValueError):
            S.save_min_margin_amount(s, "아무거나")
    finally:
        s.close()
