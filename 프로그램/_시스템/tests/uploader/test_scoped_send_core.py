# -*- coding: utf-8 -*-
"""scoped_send 코어 — 3중 게이트(실전송 조건) + markets 필터·preview 형태(순수).

DB 없는 순수부는 결정적으로 검증하고, DB 필요한 skus_for_set 은 인메모리로 얇게.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.sets.models import ProductSet, SetProduct, SetOption
from lemouton.uploader.scoped_send import (
    resolve_send_mode, skus_for_set, _keep_market, _preview_row,
)


# ── 3중 게이트 (기존 test_live_send_gate 와 동일 로직 — 이관 후에도 보존) ──────────
def test_dryrun_when_not_requested():
    use_real, reason = resolve_send_mode(want_live=False, confirmed=False, server_key_on=False)
    assert use_real is False
    assert reason is None


def test_refuse_live_without_confirm():
    use_real, reason = resolve_send_mode(want_live=True, confirmed=False, server_key_on=True)
    assert use_real is False
    assert reason and "확인" in reason


def test_refuse_live_without_server_key():
    use_real, reason = resolve_send_mode(want_live=True, confirmed=True, server_key_on=False)
    assert use_real is False
    assert reason and "MOUM_LIVE_UPLOAD" in reason


def test_real_only_when_all_three():
    use_real, reason = resolve_send_mode(want_live=True, confirmed=True, server_key_on=True)
    assert use_real is True
    assert reason is None


# ── markets 필터 (순수) ──────────────────────────────────────────────────────
def test_keep_market_empty_or_none_keeps_all():
    assert _keep_market("smartstore", []) is True
    assert _keep_market("coupang", None) is True


def test_keep_market_filters_out_unselected():
    assert _keep_market("smartstore", ["smartstore"]) is True
    assert _keep_market("coupang", ["smartstore"]) is False


# ── preview row 형태·changed 판정 (순수) ─────────────────────────────────────
def test_preview_row_shape_and_changed():
    u = {"market": "smartstore", "canonical_sku": "SKU_A", "market_option_id": "opt1"}
    row = _preview_row(u, old_price=10000, old_stock=5, new_price=12000, new_stock=5)
    assert row == {
        "market": "smartstore", "canonical_sku": "SKU_A", "market_option_id": "opt1",
        "old_price": 10000, "new_price": 12000, "old_stock": 5, "new_stock": 5,
        "changed": True,
    }


def test_preview_row_new_registration_counts_as_changed():
    u = {"market": "coupang", "canonical_sku": "SKU_B", "market_option_id": "opt2"}
    # 이전 없음(None) → 0 도 변동으로 표면화 (detect_change 신규 등록 의미)
    row = _preview_row(u, old_price=None, old_stock=None, new_price=0, new_stock=0)
    assert row["changed"] is True


def test_preview_row_unchanged_when_equal():
    u = {"market": "coupang", "canonical_sku": "SKU_B", "market_option_id": "opt2"}
    row = _preview_row(u, old_price=5000, old_stock=3, new_price=5000, new_stock=3)
    assert row["changed"] is False


# ── skus_for_set (얇은 DB) ───────────────────────────────────────────────────
@pytest.fixture
def session():
    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    s = S()
    try:
        yield s
    finally:
        s.close()


def test_skus_for_set_distinct(session):
    session.add_all([
        ProductSet(id=1, model_code="M1", name="세트1"),
        SetProduct(id=10, set_id=1, model_code="M1"),
        SetOption(set_product_id=10, canonical_sku="SKU_A"),
        SetOption(set_product_id=10, canonical_sku="SKU_B"),
    ])
    session.commit()
    assert set(skus_for_set(session, 1)) == {"SKU_A", "SKU_B"}


def test_skus_for_set_empty_for_unknown(session):
    assert skus_for_set(session, 999) == []
