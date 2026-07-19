# -*- coding: utf-8 -*-
"""주문 시점 가격 차이(M4) — 올릴 때 vs 지금 매입가 3층 대조.

in-memory SQLite. 소싱 매트릭스(_option_matrix_data)와 breakdown 은 주입/패치해
네트워크·라이브 소싱처 접속 없이 돈다.
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.sets.models", "lemouton.multitenancy.models",
    "lemouton.audit.models", "lemouton.mapping.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import lemouton.sourcing.models as M
from lemouton.sets.models import ProductSet, SetChannel, SetChannelOption
from lemouton.uploader.models import PriceSnapshot
from lemouton.orders import price_diff as PD


SKU = "SKU-AAAA1111"
SKU2 = "SKU-BBBB2222"


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(M.Model(model_code="AF", model_name_raw="에어포스"))
    s.add(M.Option(canonical_sku=SKU, model_code="AF",
                   color_code="블랙", color_display="블랙",
                   size_code="260", size_display="260"))
    s.add(M.Option(canonical_sku=SKU2, model_code="AF",
                   color_code="블루", color_display="블루",
                   size_code="270", size_display="270"))
    ps = ProductSet(model_code="AF", name="테스트 모음전")
    s.add(ps)
    s.flush()
    ch = SetChannel(set_id=ps.id, market="coupang", account_key="본계",
                    market_product_id="P100")
    s.add(ch)
    s.flush()
    s.add(SetChannelOption(channel_id=ch.id, canonical_sku=SKU,
                           market_option_id="V777", status="matched"))
    s.add(SetChannelOption(channel_id=ch.id, canonical_sku=SKU2,
                           market_option_id="V888", status="matched"))
    s.commit()
    yield s
    s.close()


def _snap(s, *, sku=SKU, market="coupang", acct="본계", purchase=100000,
          uploaded=True, action="upload"):
    s.add(PriceSnapshot(canonical_sku=sku, market=market, account_key=acct,
                        final_purchase_price=purchase, action=action,
                        uploaded_at=dt.datetime(2026, 7, 1) if uploaded else None))
    s.commit()


def _row(*, sale=139000, opt="블랙 / 260", vid="V777", fee="10%"):
    return {"판매처": "쿠팡", "오픈마켓주문번호": "O1", "상품명": "운동화",
            "옵션": opt, "단가": sale, "배송비": 0, "수수료율": fee,
            "_pd_market_option_id": vid}


def _matrix(price):
    """지금 소싱처 표면가 = price 인 가짜 매트릭스 로더."""
    def loader(model_code):
        return {"ok": True, "options": [
            {"sku": SKU, "sources": [{"source_id": 1, "crawled_price": price,
                                      "source_product_id": 11}]},
            {"sku": SKU2, "sources": [{"source_id": 1, "crawled_price": price,
                                       "source_product_id": 11}]},
        ]}
    return loader


@pytest.fixture
def fake_breakdown(monkeypatch):
    """compute_breakdown = 표면가 그대로 최종매입가. 호출 횟수·캐시 재사용을 기록."""
    calls = {"cache": 0, "breakdown": 0}

    def _cache(session, items, sp_rows=None):
        calls["cache"] += 1
        return {"_fake": True}

    def _bd(session, *, sku, source_id, sale_price, _cache=None, **kw):
        calls["breakdown"] += 1
        assert _cache is not None, "breakdown 이 캐시 없이 불렸다 = N+1"
        return {"final_price": int(sale_price), "steps": []}

    import webapp.routes.api_benefits as AB
    monkeypatch.setattr(AB, "_build_breakdown_cache", _cache)
    monkeypatch.setattr(AB, "compute_breakdown", _bd)
    return calls


def _diff(db, rows, price):
    return PD.build_price_diffs(db, rows, matrix_loader=_matrix(price))


# ── ① 올릴 때 = 지금 → 회색, 차이 없음 ──────────────────────────────
def test_same_price_is_grey(db, fake_breakdown):
    _snap(db, purchase=100000)
    d = _diff(db, [_row()], 100000)[PD.row_key(_row())]
    assert d["upload_purchase"] == 100000
    assert d["current_purchase"] == 100000
    assert d["state"] == PD.STATE_SAME


# ── ② 올랐고 손해 전환 → 빨강 + 마진 음수 ───────────────────────────
def test_risen_into_loss_is_red_with_negative_margin(db, fake_breakdown):
    _snap(db, purchase=92400)
    # 판매가 98,000 · 수수료 10% → 손에 88,200. 지금 매입가 105,000 → −16,800
    d = _diff(db, [_row(sale=98000)], 105000)[PD.row_key(_row(sale=98000))]
    assert d["upload_purchase"] == 92400
    assert d["current_purchase"] == 105000
    assert d["margin"] < 0
    assert d["state"] == PD.STATE_LOSS


# ── ③ 올랐지만 남음 → 주황 ─────────────────────────────────────────
def test_risen_but_still_profitable_is_orange(db, fake_breakdown):
    _snap(db, purchase=108700)
    d = _diff(db, [_row(sale=139000)], 116900)[PD.row_key(_row())]
    assert d["current_purchase"] > d["upload_purchase"]
    assert d["margin"] > 0
    assert d["state"] == PD.STATE_WARN


# ── ④ 내림 → 초록 ─────────────────────────────────────────────────
def test_fallen_price_is_green(db, fake_breakdown):
    _snap(db, purchase=74000)
    d = _diff(db, [_row(sale=95000)], 69500)[PD.row_key(_row(sale=95000))]
    assert d["current_purchase"] < d["upload_purchase"]
    assert d["state"] == PD.STATE_GAIN


# ── ⑤ 스냅샷 없음 → 확인 불가 (0원 아님) ────────────────────────────
def test_missing_snapshot_is_unknown_not_zero(db, fake_breakdown):
    d = _diff(db, [_row()], 100000)[PD.row_key(_row())]
    assert d["upload_purchase"] is None      # ★ 0 으로 채우지 않는다
    assert d["state"] == PD.STATE_UNKNOWN
    assert d["reason"]


def test_failed_send_snapshot_is_not_a_baseline(db, fake_breakdown):
    """uploaded_at 이 비면 '마켓이 받은 값'이 아니므로 기준선이 못 된다."""
    _snap(db, purchase=99999, uploaded=False)
    d = _diff(db, [_row()], 100000)[PD.row_key(_row())]
    assert d["upload_purchase"] is None
    assert d["state"] == PD.STATE_UNKNOWN


# ── ⑥ 계산 실패 → 확인 불가 ────────────────────────────────────────
def test_breakdown_failure_is_unknown(db, monkeypatch):
    _snap(db, purchase=100000)

    def _boom(session, **kw):
        raise RuntimeError("혜택 계산 폭발")

    import webapp.routes.api_benefits as AB
    monkeypatch.setattr(AB, "_build_breakdown_cache", lambda s, i, sp_rows=None: {})
    monkeypatch.setattr(AB, "compute_breakdown", _boom)
    d = _diff(db, [_row()], 100000)[PD.row_key(_row())]
    assert d["current_purchase"] is None      # ★ 추정가로 메우지 않는다
    assert d["margin"] is None
    assert d["state"] == PD.STATE_UNKNOWN


def test_no_crawl_price_is_unknown(db, fake_breakdown):
    """크롤값이 아예 없으면 지금 매입가는 '확인 불가'."""
    _snap(db, purchase=100000)
    def loader(mc):
        return {"ok": True, "options": [{"sku": SKU, "sources": []}]}
    d = PD.build_price_diffs(db, [_row()], matrix_loader=loader)[PD.row_key(_row())]
    assert d["current_purchase"] is None
    assert d["state"] == PD.STATE_UNKNOWN


def test_unresolvable_row_is_unknown(db, fake_breakdown):
    """우리 SKU 에 연결 안 되는 주문(스마트스토어 등 식별자 없음) → 확인 불가."""
    r = {"판매처": "스마트스토어", "오픈마켓주문번호": "O9", "상품명": "x",
         "옵션": "블랙 / 260", "단가": 50000}
    d = PD.build_price_diffs(db, [r], matrix_loader=_matrix(100000))[PD.row_key(r)]
    assert d["upload_purchase"] is None and d["current_purchase"] is None
    assert d["state"] == PD.STATE_UNKNOWN


# ── ⑦ N+1 안 난다 — 캐시는 딱 1회 ───────────────────────────────────
def test_no_n_plus_one_cache_built_once(db, fake_breakdown):
    _snap(db, purchase=100000)
    _snap(db, sku=SKU2, purchase=100000)
    rows = []
    for i in range(20):
        rows.append({"판매처": "쿠팡", "오픈마켓주문번호": "O%d" % i,
                     "상품명": "운동화", "옵션": "블랙 / 260", "단가": 139000,
                     "배송비": 0, "수수료율": "10%", "_pd_market_option_id": "V777"})
        rows.append({"판매처": "쿠팡", "오픈마켓주문번호": "N%d" % i,
                     "상품명": "운동화", "옵션": "블루 / 270", "단가": 139000,
                     "배송비": 0, "수수료율": "10%", "_pd_market_option_id": "V888"})
    out = PD.build_price_diffs(db, rows, matrix_loader=_matrix(100000))
    assert len(out) == 40
    assert fake_breakdown["cache"] == 1, "행마다 캐시를 다시 만들면 N+1"
    # breakdown 은 sku 당 1회(40행 → 2회). 행마다 부르지 않는다.
    assert fake_breakdown["breakdown"] == 2


# ── ⑧ 마진이 기존 수수료·마진 함수를 탄다 ──────────────────────────
def test_margin_goes_through_existing_reconcile_function(db, fake_breakdown, monkeypatch):
    _snap(db, purchase=100000)
    seen = {}
    import lemouton.uploader.reconcile as RC
    real = RC.compute_margin_amount

    def spy(price_result, final_purchase_price):
        seen["fee_rate"] = price_result.breakdown["fee_rate"]
        seen["sale"] = price_result.final_price
        seen["cost"] = final_purchase_price
        return real(price_result, final_purchase_price)

    monkeypatch.setattr(RC, "compute_margin_amount", spy)
    d = _diff(db, [_row(sale=139000, fee="11.55%")], 108700)[PD.row_key(
        _row(sale=139000, fee="11.55%"))]
    assert seen["fee_rate"] == pytest.approx(0.1155)   # 행의 실수수료율 사용
    assert seen["sale"] == 139000 and seen["cost"] == 108700
    # (139000 − 0) × (1 − 0.1155) − 108700
    assert d["margin"] == int(round(139000 * (1 - 0.1155))) - 108700


def test_fee_falls_back_to_pricing_policy_when_row_has_none(db, fake_breakdown):
    """행에 실수수료율이 없으면 pricing.unified 의 정책 요율을 쓴다(새로 만들지 않음)."""
    from lemouton.pricing.unified import resolve_market_policy
    _snap(db, purchase=100000)
    expected = resolve_market_policy(None, "coupang", "sourcing")["fee_rate"]
    d = _diff(db, [_row(sale=139000, fee="")], 100000)[PD.row_key(
        _row(sale=139000, fee=""))]
    assert d["margin"] == int(round(139000 * (1 - expected))) - 100000


def test_unknown_fee_market_leaves_margin_unknown(db, fake_breakdown):
    """롯데온·11번가는 resolve_market_policy 가 조용히 'ss'(6%)로 폴백한다.
    수수료를 모르면 마진을 날조하지 않고 '확인 불가'로 남긴다."""
    from lemouton.sets.models import SetChannel, SetChannelOption
    ch = db.query(SetChannel).first()
    ch.market = "lotteon"
    db.commit()
    r = {"판매처": "롯데온", "오픈마켓주문번호": "L1", "상품명": "운동화",
         "옵션": "블랙 / 260", "단가": 95000, "배송비": 0, "수수료율": "",
         "_pd_market_option_id": "V777"}
    _snap(db, market="lotteon", purchase=74000)
    d = PD.build_price_diffs(db, [r], matrix_loader=_matrix(69500))[PD.row_key(r)]
    assert d["current_purchase"] == 69500      # 가격은 보여주되
    assert d["margin"] is None                 # 마진은 확인 불가
    assert d["state"] == PD.STATE_GAIN


# ── 매칭 규율: 애매하면 연결하지 않는다 ─────────────────────────────
def test_ambiguous_product_match_is_not_guessed(db, fake_breakdown):
    """마켓상품ID 만 있고 옵션 텍스트로 좁혀지지 않으면 연결하지 않는다."""
    r = {"판매처": "쿠팡", "오픈마켓주문번호": "A1", "상품명": "운동화",
         "옵션": "단일", "단가": 139000, "_lo_spdno": "P100"}
    d = PD.build_price_diffs(db, [r], matrix_loader=_matrix(100000))[PD.row_key(r)]
    assert d["canonical_sku"] is None
    assert d["state"] == PD.STATE_UNKNOWN
