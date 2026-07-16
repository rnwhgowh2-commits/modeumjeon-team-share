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
    scope_c_output_to_markets, build_explicit_c_output, run_explicit,
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


# ── scope_c_output_to_markets (순수) — 실제 전송도 선택 마켓으로 스코프 ──────────
def test_scope_c_output_keeps_only_selected_markets():
    c = {"smartstore": {"M": {}}, "coupang": {"M": {}}, "alerts": [1]}
    out = scope_c_output_to_markets(c, ["smartstore"])
    assert out["smartstore"] == {"M": {}}   # 선택 마켓 payload 유지
    assert out["coupang"] == {}             # 미선택 마켓 → 빈 dict(그 마켓 미전송)
    assert out["alerts"] == [1]             # alerts 는 보존
    # 원본 불변(부작용 없음)
    assert c["coupang"] == {"M": {}}


def test_scope_c_output_empty_or_none_returns_original():
    c = {"smartstore": {"M": {}}, "coupang": {"M": {}}, "alerts": [1]}
    assert scope_c_output_to_markets(c, []) == c
    assert scope_c_output_to_markets(c, None) == c


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


# ── 직접 값 지정: 합성 c_output (순수) ────────────────────────────────────────
def test_build_explicit_c_output_smartstore_uses_base_plus_add():
    c = build_explicit_c_output(market="smartstore", model_code_key="SKU_A",
                                product_id="P1", option_id="opt1",
                                price=12000, stock=7)
    # 스마트스토어 = base_price + add_price(0) 형태 → _extract_uploads 가 12000 계산
    assert list(c.keys()) == ["smartstore", "alerts"]
    payload = c["smartstore"]["SKU_A"]
    assert payload["product_id"] == "P1"
    assert payload["base_price"] == 12000
    assert payload["options"] == [{"option_id": "opt1", "add_price": 0, "stock": 7}]


def test_build_explicit_c_output_coupang_flat_price():
    c = build_explicit_c_output(market="coupang", model_code_key="SKU_B",
                                product_id="P2", option_id="v99",
                                price=9000, stock=0)
    payload = c["coupang"]["SKU_B"]
    assert payload["options"] == [{"option_id": "v99", "price": 9000, "stock": 0}]
    # 지정 마켓만 존재 — 다른 마켓 키 절대 미포함
    assert "smartstore" not in c and "lotteon" not in c


def test_build_explicit_c_output_contains_only_one_option():
    from lemouton.uploader.orchestrator import _extract_uploads
    c = build_explicit_c_output(market="lotteon", model_code_key="SKU_C",
                                product_id="P3", option_id="sitm7",
                                price=5000, stock=3)
    sku_by_option = {("lotteon", "sitm7"): "SKU_C",
                     ("coupang", "other"): "SKU_X"}   # 다른 옵션도 매핑엔 있음
    uploads = _extract_uploads(c, sku_by_option)
    # 합성 페이로드에 그 옵션만 있으므로 정확히 1건, 다른 옵션 0
    assert len(uploads) == 1
    assert uploads[0]["market"] == "lotteon"
    assert uploads[0]["market_option_id"] == "sitm7"
    assert uploads[0]["new_price"] == 5000
    assert uploads[0]["new_stock"] == 3


# ── run_explicit: price_guard · 미매칭 · force(동일값 전송) ─────────────────────
def test_run_explicit_price_guard_blocks_zero(monkeypatch):
    monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
    # 0원 → price_guard 가 페이로드 만들기 전에 차단(session 은 건드리지 않음)
    out = run_explicit(None, canonical_sku="SKU_A", market="smartstore",
                       market_product_id="P1", market_option_id="opt1",
                       new_price=0, new_stock=5, want_live=True, confirmed=True)
    assert out["price_error"] and out["result"] is None


def test_run_explicit_unmatched_option_surfaced(session, monkeypatch):
    monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
    # 등록(matched)된 옵션이 없으면 정직히 실패(전송 0)
    out = run_explicit(session, canonical_sku="SKU_A", market="smartstore",
                       market_product_id="P1", market_option_id="opt1",
                       new_price=10000, new_stock=5, want_live=True, confirmed=True)
    assert out["result"] is None
    assert "matched" in out["error"]


@pytest.fixture
def matched_session():
    from lemouton.sets.models import (ProductSet, SetChannel, SetChannelOption)
    from lemouton.uploader.models import MarketRegistration   # 테이블 생성 위해 import
    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    s = S()
    s.add_all([
        ProductSet(id=1, model_code="M1", name="세트1"),
        SetChannel(id=5, set_id=1, market="smartstore",
                   account_key="default", market_product_id="P1"),
        SetChannelOption(channel_id=5, canonical_sku="SKU_A",
                         market_option_id="opt1", status="matched"),
        # 직전 동기화값 = 명시값과 동일 → force 없으면 변동 없음(skip)
        MarketRegistration(canonical_sku="SKU_A", market="smartstore",
                           last_synced_price=10000, last_synced_stock=5),
    ])
    s.commit()
    try:
        yield s
    finally:
        s.close()


def test_run_explicit_force_sends_even_when_unchanged(matched_session, monkeypatch):
    # 서버키 off → use_real False(드라이런). force=True 라 동일값도 전송 대상이 되어야 함.
    monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
    out = run_explicit(matched_session, canonical_sku="SKU_A", market="smartstore",
                       market_product_id="P1", market_option_id="opt1",
                       new_price=10000, new_stock=5, want_live=True, confirmed=True)
    assert out["use_real"] is False          # 서버키 off → 드라이런
    assert out["price_error"] is None
    res = out["result"]
    # 동일값이어도 force 로 전송 대상(드라이런 어댑터 성공) → uploaded 1, skipped 0
    assert res["uploaded"] == 1
    assert res["skipped"] == 0
    assert res["failed"] == 0
