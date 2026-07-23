# -*- coding: utf-8 -*-
"""롯데온 셀러오피스 크롤분 — 업서트·채움·누락 취소라인 추가·철회 잔존 교정.

배경(2026-07-23 샵마인 387건 대조): OpenAPI 가 구조적으로 못 주는 3종 —
①부분취소의 취소 라인(018057538·018074798) ②취소건 구매자(2218436713 등)
③철회 취소 후 정상 복귀 신호(1917781423). 셀러오피스 화면이 유일 원천.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.markets import lotteon_so as SO


@pytest.fixture
def session():
    from shared.db import Base
    import lemouton.markets.models_shopmine  # noqa: F401 — lotteon_so_orders 등록
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[Base.metadata.tables["lotteon_so_order_lines"]])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


def _so(od_no, **kw):
    base = {"od_no": od_no, "od_seq": "1", "proc_seq": "1", "status": "취소완료",
            "status_code": "21", "od_typ": "취소(주문취소)", "ch_no": "100195",
            "ordered_at": "2026-07-20 10:00:00", "product_name": "<매장정품> 잔스포츠",
            "option1": "블랙", "qty": "1", "unit_price": "24000",
            "paid_amount": "24000", "buyer": "김구매", "recipient": "김수령",
            "phone": "010-1111-2222", "address": "서울", "tr_no": "LO10161082"}
    base.update(kw)
    return base


# ── 업서트 ──────────────────────────────────────────────────────────────

def test_업서트는_멱등_같은키는_갱신(session):
    st = SO.upsert_rows([_so("2026070100000001"), _so("2026070100000002")], session=session)
    assert st == {"new": 2, "updated": 0, "skipped_no_odno": 0}
    st2 = SO.upsert_rows([_so("2026070100000001", buyer="박구매")], session=session)
    assert st2["updated"] == 1 and st2["new"] == 0
    from lemouton.markets.models_shopmine import LotteonSoOrder
    assert session.get(LotteonSoOrder, ("2026070100000001", "1", "1")).buyer == "박구매"


def test_od_no_없는_라인은_스킵_보고(session):
    st = SO.upsert_rows([_so(""), _so("2026070100000003")], session=session)
    assert st["skipped_no_odno"] == 1 and st["new"] == 1


def test_HTML_이스케이프_정규화(session):
    SO.upsert_rows([_so("2026070100000004", product_name="&lt;매장정품&gt; 커버낫")], session=session)
    from lemouton.markets.models_shopmine import LotteonSoOrder
    assert session.get(LotteonSoOrder, ("2026070100000004", "1", "1")).product_name == "<매장정품> 커버낫"


# ── 채움(빈칸만) ────────────────────────────────────────────────────────

def test_취소행_구매자_빈칸을_채운다(session):
    SO.upsert_rows([_so("2026070100000005")], session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000005", "주문상태": "취소완료",
         "구매자": "", "수령자": "", "단가": "", "실결제금액": "", "옵션": ""}
    SO.fill_from_so(session, [r])
    assert r["구매자"] == "김구매" and r["수령자"] == "김수령"
    assert r["단가"] == "24000"            # 단일 라인 — 금액도 채움
    assert "_so_filled" in r


def test_기존_값은_덮지_않는다(session):
    SO.upsert_rows([_so("2026070100000006")], session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000006", "주문상태": "취소완료",
         "구매자": "원래구매자", "단가": 999}
    SO.fill_from_so(session, [r])
    assert r["구매자"] == "원래구매자" and r["단가"] == 999


def test_다품_주문은_옵션_일치_라인만_금액을_채운다(session):
    SO.upsert_rows([_so("2026070100000007", od_seq="1", option1="블랙", unit_price="10000"),
                    _so("2026070100000007", od_seq="2", option1="화이트", unit_price="20000")],
                   session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000007", "주문상태": "취소완료",
         "옵션": "화이트", "단가": "", "구매자": ""}
    SO.fill_from_so(session, [r])
    assert r["단가"] == "20000"            # 옵션 일치 라인
    assert r["구매자"] == "김구매"          # 주문 단위는 어느 라인이든 동일
    r2 = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000007", "주문상태": "취소완료",
          "옵션": "", "단가": "", "구매자": ""}
    SO.fill_from_so(session, [r2])
    assert r2["단가"] == ""                # 라인 미특정 — 금액 안 붙임(날조 금지)
    assert r2["구매자"] == "김구매"


# ── 철회 잔존 교정 (실측 1917781423: 우리 철회 vs 셀러오피스 수취완료) ────────────

def test_철회_잔존을_SO_수취완료로_교정(session):
    SO.upsert_rows([_so("2026070100000008", status="수취완료")], session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000008", "주문상태": "철회",
         "_kind": "change", "_change_date": "2026-07-21", "옵션": "블랙"}
    SO.fill_from_so(session, [r])
    assert r["주문상태"] == "수취완료"
    assert "_kind" not in r                # 정상 행 복귀 → K=원금 강제 해제
    assert r["_so_status_fixed"] == "1"


def test_SO도_클레임이면_교정하지_않는다(session):
    SO.upsert_rows([_so("2026070100000009", status="철회(배송)")], session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000009", "주문상태": "철회",
         "_kind": "change", "옵션": "블랙"}
    SO.fill_from_so(session, [r])
    assert r["주문상태"] == "철회" and r.get("_kind") == "change"


# ── 누락 취소 라인 추가 (부분취소 — 실측 018057538: 수취완료만 있고 취소 라인 없음) ──

def test_우리에_없는_SO_취소라인을_추가한다(session):
    SO.upsert_rows([_so("2026070100000010", od_seq="2", proc_seq="2", status="취소완료")],
                   session=session)
    rows = [{"판매처": "롯데온", "오픈마켓주문번호": "2026070100000010", "주문상태": "수취완료",
             "상품명": "다른상품"}]
    out = SO.add_missing_claims(rows, session)
    assert len(out) == 2
    add = out[1]
    assert add["주문상태"] == "취소완료" and add["_kind"] == "change"
    assert add["단가"] == "24000" and add["구매자"] == "김구매"
    assert add["_so_added"] == "1"


def test_이미_취소행이_있으면_추가하지_않는다(session):
    SO.upsert_rows([_so("2026070100000011", proc_seq="2", status="취소완료")], session=session)
    rows = [{"판매처": "롯데온", "오픈마켓주문번호": "2026070100000011", "주문상태": "취소완료"}]
    assert len(SO.add_missing_claims(rows, session)) == 1


def test_취소완료가_아닌_SO라인은_추가하지_않는다(session):
    SO.upsert_rows([_so("2026070100000012", status="수취완료")], session=session)
    rows = [{"판매처": "롯데온", "오픈마켓주문번호": "2026070100000012", "주문상태": "수취완료"}]
    assert len(SO.add_missing_claims(rows, session)) == 1


# ── 라인 단위 최신 상태(odSeq 고정·procSeq 최대) 로 철회 교정 ────────────────────

def test_같은_라인의_최신_procSeq_가_정상완료면_철회를_교정(session):
    """실측 1917781423: 철회 접수(procSeq 1) 뒤 철회가 취소돼 같은 라인이 수취완료
    (procSeq 2)로 복귀. 옵션만 보면 두 라인이 같아 특정 실패 → 우리 상태(철회)와
    같은 라인을 골라 교정이 안 걸렸다. **같은 odSeq 안에서 procSeq 최대 = 현재 상태**."""
    SO.upsert_rows([_so("2026070100000013", od_seq="1", proc_seq="1", status="철회", status_code="22"),
                    _so("2026070100000013", od_seq="1", proc_seq="2", status="수취완료", status_code="15")],
                   session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000013", "주문상태": "철회",
         "_kind": "change", "_odseq": "1", "옵션": "블랙"}
    SO.fill_from_so(session, [r])
    assert r["주문상태"] == "수취완료"
    assert "_kind" not in r
    assert r["_so_status_fixed"] == "1"


def test_부분취소는_교정하지_않는다_다른_odSeq(session):
    """odSeq 가 다르면 '다른 상품 라인' — 한쪽이 수취완료라고 취소 라인을 되살리면 안 된다."""
    SO.upsert_rows([_so("2026070100000014", od_seq="1", proc_seq="2", status="취소완료"),
                    _so("2026070100000014", od_seq="2", proc_seq="1", status="수취완료")],
                   session=session)
    r = {"판매처": "롯데온", "오픈마켓주문번호": "2026070100000014", "주문상태": "회수지시",
         "_kind": "change", "_odseq": "1", "옵션": "블랙"}
    SO.fill_from_so(session, [r])
    assert r["주문상태"] == "회수지시" and r.get("_kind") == "change"


def test_숫자가_아닌_주문번호는_적재하지_않는다(session):
    """진단 프로브 등 오염 행 차단 — 롯데온 주문번호는 숫자만."""
    st = SO.upsert_rows([_so("__PROBE__"), _so("2026072018057538")], session=session)
    assert st["new"] == 1 and st["skipped_no_odno"] == 1
