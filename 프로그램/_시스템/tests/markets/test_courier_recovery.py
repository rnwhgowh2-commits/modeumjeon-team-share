# -*- coding: utf-8 -*-
"""택배사 회수 — 「주문내역에 각 마켓별 입력된 모든 택배사 정보를 정확히」(사장님 2026-07-25).

원천 3갈래(지도 전수정독 결과):
  ① 옥션·G마켓: 주문조회가 이름(TakbaeName) 을 준다 — 기존.
  ② 11번가: 배송중 조회가 코드(dlvEtprsCd) 를 준다 → 공식 코드표로 이름 변환.
  ③ 그 외(쿠팡·롯데온·스스): 주문조회가 택배사를 **안 준다** → 우리가 보낼 때 고른
     택배사를 원장에 남기고(remember_sent) 다음 조회에서 되채운다(fill_missing).
★모르면 빈칸 — 이름을 지어내지 않는다(무결성 1원칙).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def session():
    import lemouton.sourcing.models_v2  # noqa: F401 — 테이블 등록
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[Base.metadata.tables["invoice_ledger"]])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


# ── ② 11번가 코드 → 이름 ─────────────────────────────────────────────

def test_eleven11_courier_code_to_name():
    from shared.platforms.eleven11.orders import courier_name
    assert courier_name("00002") == "로젠택배"
    assert courier_name("00034") == "CJ대한통운"
    assert courier_name("00012") == "롯데택배"


def test_eleven11_courier_pads_lost_leading_zero():
    """파서가 '00002' 를 숫자 2 로 바꿔도 찾아낸다(선행 0 유실 실사고 방지)."""
    from shared.platforms.eleven11.orders import courier_name
    assert courier_name("2") == "로젠택배"
    assert courier_name(2) == "로젠택배"


def test_eleven11_unknown_code_is_blank_not_fabricated():
    """모르는 코드는 빈칸 — 그럴듯한 이름을 지어내지 않는다."""
    from shared.platforms.eleven11.orders import courier_name
    assert courier_name("99999") == ""
    assert courier_name("") == ""
    assert courier_name(None) == ""


# ── ③ 우리가 보낸 택배사 기억 → 되채움 ──────────────────────────────

def test_remember_sent_then_fill_courier(session):
    """쿠팡처럼 조회가 택배사를 안 주는 마켓도, 우리가 보낸 값으로 채워진다."""
    from lemouton.markets import invoice_ledger as led
    assert led.remember_sent("쿠팡", "70001", "123456789012", "CJ대한통운",
                             session=session) is True
    rows = [{"판매처": "쿠팡", "오픈마켓주문번호": "70001",
             "주문상태": "배송완료", "송장입력": "123456789012", "택배사": ""}]
    assert led.fill_missing(rows, session=session) == 1
    assert rows[0]["택배사"] == "CJ대한통운"


def test_fill_courier_even_when_invoice_already_present(session):
    """번호가 이미 있어도 택배사만 비면 채운다 — 둘은 다른 칸이다."""
    from lemouton.markets import invoice_ledger as led
    led.remember_sent("롯데온", "80001", "999888777", "한진택배", session=session)
    rows = [{"판매처": "롯데온", "오픈마켓주문번호": "80001",
             "주문상태": "배송완료", "송장입력": "999888777", "택배사": ""}]
    assert led.fill_missing(rows, session=session) == 1
    assert rows[0]["택배사"] == "한진택배"


def test_existing_courier_is_not_overwritten(session):
    """마켓이 준 실값(ESM)을 원장 값으로 덮지 않는다."""
    from lemouton.markets import invoice_ledger as led
    led.remember_sent("옥션", "90001", "111222333", "로젠택배", session=session)
    rows = [{"판매처": "옥션", "오픈마켓주문번호": "90001",
             "주문상태": "배송완료", "송장입력": "111222333", "택배사": "대한통운"}]
    led.fill_missing(rows, session=session)
    assert rows[0]["택배사"] == "대한통운"      # 마켓 실값 유지


def test_no_ledger_entry_leaves_courier_blank(session):
    """원장에 없으면 빈칸 — 이름 날조 금지."""
    from lemouton.markets import invoice_ledger as led
    rows = [{"판매처": "스마트스토어", "오픈마켓주문번호": "60001",
             "주문상태": "배송완료", "송장입력": "555444333", "택배사": ""}]
    assert led.fill_missing(rows, session=session) == 0
    assert rows[0]["택배사"] == ""


def test_remember_sent_blank_courier_does_not_erase(session):
    """빈 택배사로 다시 보내도 기존 실값을 지우지 않는다."""
    from lemouton.markets import invoice_ledger as led
    led.remember_sent("쿠팡", "70002", "123", "CJ대한통운", session=session)
    led.remember_sent("쿠팡", "70002", "123", "", session=session)
    rows = [{"판매처": "쿠팡", "오픈마켓주문번호": "70002",
             "주문상태": "배송완료", "송장입력": "123", "택배사": ""}]
    led.fill_missing(rows, session=session)
    assert rows[0]["택배사"] == "CJ대한통운"


def test_remember_sent_rejects_fake_invoice(session):
    """상태 문구('송장입력됨') 같은 가짜 번호는 원장에 넣지 않는다."""
    from lemouton.markets import invoice_ledger as led
    assert led.remember_sent("쿠팡", "70003", "송장입력됨", "한진택배",
                             session=session) is False
