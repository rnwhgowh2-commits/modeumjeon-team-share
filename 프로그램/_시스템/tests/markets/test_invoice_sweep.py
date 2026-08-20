# -*- coding: utf-8 -*-
"""송장 스윕 — 증분이 놓친 과거 발송건의 송장·택배사를 채운다(2026-07-30 사장님 지시).

🔴 왜 필요한가(라이브 실측): 저장분 송장 보유율 G마켓 34/190 · 옥션 25/47 · 11번가 109/743.
  같은 G마켓을 **라이브**로 20일 조회하면 23/23(100%) — 마켓은 정상으로 준다.
  문제는 창고에 안 담긴 것이고 원인은 둘:
    ① ESM 증분은 주문일 기준 21일 창만 본다 → 21일 지나 발송하면 영영 못 받음.
    ② 11번가는 배송중·배송완료만 invcNo 를 주고 구매확정은 안 준다.
★마켓이 안 주면 그대로 둔다(날조 금지). 이미 있는 번호는 안 덮는다.
"""
from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.markets import line_uid as L
from lemouton.markets import order_ingest as OI
from lemouton.markets import order_store as OS

KST = _dt.timezone(_dt.timedelta(hours=9))


@pytest.fixture
def session():
    import lemouton.markets.models_orders  # noqa: F401
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


def _row(uid="gmarket|G1", ono="G1", **kw):
    row = {L.FIELD: uid, "판매처": "G마켓", "오픈마켓주문번호": ono,
           "주문일": "2026-03-01 10:00:00", "주문상태": "배송완료",
           "상품명": "샘플", "단가": 30000, "수량": 1,
           "송장입력": "확인 불가", "택배사": ""}
    row.update(kw)
    return row


def _patch(monkeypatch, rows, market="gmarket"):
    """마켓이 돌려줄 (주문번호, 송장, 택배사) 목록을 심는다."""
    monkeypatch.setattr(OI, "_esm_settlement_clients", lambda m: [("대표", object())])
    monkeypatch.setattr(OI, "_invoice_rows_for",
                        lambda m, s, u, *, client: list(rows))


def test_blank_invoice_is_filled(session, monkeypatch):
    """21일 창을 벗어나 '확인 불가'로 굳은 건이 채워진다."""
    OS.save([_row()], session=session)
    _patch(monkeypatch, [("G1", "123456789012", "대한통운")])

    stat = OI.refresh_invoices("gmarket", session=session)

    assert stat["updated"] == 1
    stored = OS.load(["gmarket"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["송장입력"] == "123456789012"
    assert stored["택배사"] == "대한통운"


def test_existing_invoice_is_not_overwritten(session, monkeypatch):
    """이미 진짜 번호가 있으면 건드리지 않는다."""
    OS.save([_row(송장입력="999888777", 택배사="한진택배")], session=session)
    _patch(monkeypatch, [("G1", "111", "로젠택배")])

    stat = OI.refresh_invoices("gmarket", session=session)

    assert stat["updated"] == 0
    stored = OS.load(["gmarket"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["송장입력"] == "999888777"
    assert stored["택배사"] == "한진택배"


def test_courier_filled_even_when_invoice_present(session, monkeypatch):
    """번호는 있고 택배사만 비면 택배사만 채운다."""
    OS.save([_row(송장입력="555444333", 택배사="")], session=session)
    _patch(monkeypatch, [("G1", "555444333", "롯데택배")])

    stat = OI.refresh_invoices("gmarket", session=session)

    assert stat["updated"] == 1
    stored = OS.load(["gmarket"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["송장입력"] == "555444333"
    assert stored["택배사"] == "롯데택배"


def test_market_without_data_leaves_row_untouched(session, monkeypatch):
    """마켓이 안 주면 그대로 둔다 — 없는 번호를 지어내지 않는다."""
    OS.save([_row()], session=session)
    _patch(monkeypatch, [("다른주문", "123", "대한통운")])

    stat = OI.refresh_invoices("gmarket", session=session)

    assert stat["updated"] == 0
    stored = OS.load(["gmarket"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["송장입력"] == "확인 불가"


def test_not_shipped_row_is_skipped(session, monkeypatch):
    """발송 전 주문은 대상이 아니다(송장이 없는 게 정상)."""
    OS.save([_row(주문상태="결제완료", 송장입력="송장미입력")], session=session)
    _patch(monkeypatch, [("G1", "123456789012", "대한통운")])

    stat = OI.refresh_invoices("gmarket", session=session)
    assert stat["updated"] == 0


def test_claim_row_is_skipped(session, monkeypatch):
    """클레임 행은 원배송 송장을 따로 다룬다 — 여기서 안 건드린다."""
    OS.save([_row(주문상태="반품완료", _kind="change", _change_date="2026-03-05")],
            session=session)
    _patch(monkeypatch, [("G1", "123456789012", "대한통운")])

    stat = OI.refresh_invoices("gmarket", session=session)
    assert stat["updated"] == 0


def test_fake_invoice_from_market_is_rejected(session, monkeypatch):
    """마켓이 상태 문구('송장입력됨')를 줘도 번호로 받지 않는다."""
    OS.save([_row()], session=session)
    _patch(monkeypatch, [("G1", "송장입력됨", "대한통운")])

    stat = OI.refresh_invoices("gmarket", session=session)
    assert stat["updated"] == 0


def test_unsupported_market_raises():
    """쿠팡·스스·롯데온은 주문조회가 송장을 늘 줘서 대상이 아니다(실측 99%+)."""
    for m in ("coupang", "smartstore", "lotteon"):
        with pytest.raises(ValueError):
            OI.refresh_invoices(m)


def test_blank_invoice_detector():
    """'확인 불가'·'송장미입력'·빈칸은 전부 '없음'으로 본다."""
    assert OI._is_blank_invoice("") is True
    assert OI._is_blank_invoice("확인 불가") is True
    assert OI._is_blank_invoice("송장미입력") is True
    assert OI._is_blank_invoice("송장입력됨") is True      # 상태 문구도 번호가 아니다
    assert OI._is_blank_invoice("123456789012") is False
