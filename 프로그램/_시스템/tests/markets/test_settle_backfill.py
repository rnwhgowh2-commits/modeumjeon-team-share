# -*- coding: utf-8 -*-
"""미정산 공란 채움 3종 — 2026-07-21 사장님 확정.

① 취소완료 = 거래 무산 → 정산·수수료 0 이 **사실값**(추정 아님). 취소요청은 미확정이라 제외.
② 11번가: 배송완료·배송중 조회는 정산예정액을 안 주지만, 결제완료 때 받아둔
   저장분(stlPlnAmt)이 있다 → 물려받는다(마켓 원본값, 폴백 아님).
③ 역산 추정: 같은 상품의 과거 실정산/실결제 비율(실효 수수료율 — 수수료·판매자부담
   할인·경유가 전부 녹아 있는 실측 비율)로 추정. _settle_source='estimated' 표식.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.markets import line_uid as L
from lemouton.markets import order_store as OS
from lemouton.markets import order_export as oe


@pytest.fixture
def session():
    from shared.db import Base
    import lemouton.markets.models_orders  # noqa: F401
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


# ── ① 취소완료 = 정산 0 (전 마켓 공통 _finalize_rows) ─────────────────────────

def _row(**kw):
    base = {"주문일": "2026-07-16 10:00:00", "판매처": "롯데온", "주문상태": "취소완료",
            "_kind": "change", "단가": 46200, "수량": 1, "배송비": 0,
            "실결제금액": 46200, "정산예정금액": "", "오픈마켓주문번호": "X1"}
    base.update(kw)
    return base


def test_취소완료_빈_정산은_0_확정():
    r = oe._finalize_rows([_row()])[0]
    assert r["정산예정금액"] == 0
    assert r["마켓수수료"] == 0            # 실결제−0 = 46200 으로 날조되면 안 된다
    assert r["수수료율"] == ""
    assert r["정산예정금(배송비포함)"] == 0
    assert r["_settle_source"] == "zero_cancel"


def test_취소완료라도_실정산이_있으면_유지():
    """옥션 송금후취소 등 환불 마이너스 정산이 실재 — 실값을 0 으로 덮으면 안 된다."""
    r = oe._finalize_rows([_row(정산예정금액=-5000)])[0]
    assert r["정산예정금액"] == -5000


def test_취소요청은_미확정이라_그대로_빈칸():
    r = oe._finalize_rows([_row(주문상태="취소요청")])[0]
    assert r["정산예정금액"] == ""


# ── ② 11번가 정산예정액 저장분 물려받기 ──────────────────────────────────────

def test_11번가_배송완료의_빈_정산을_저장분에서_물려받는다(session):
    OS.save([{L.FIELD: "eleven11|ON5|1", "판매처": "11번가", "오픈마켓주문번호": "ON5",
              "주문일": "2026-07-18 09:00:00", "주문상태": "결제완료",
              "상품명": "코트", "정산예정금액": 169155, "_settle_source": "real"}],
            session=session)
    row = {"판매처": "11번가", "오픈마켓주문번호": "ON5", "_kind": "order",
           "_line_uid": "eleven11|ON5|1", "주문상태": "배송완료",
           "상품명": "코트", "정산예정금액": ""}
    oe.fill_claim_blanks_from_history([row], "eleven11", session=session,
                                      include_blank_orders=True,
                                      settle_from_store_for_orders=True)
    assert row["정산예정금액"] == 169155
    assert row["_settle_source"] == "store"


def test_클레임행은_저장분_정산을_물려받지_않는다(session):
    """반품·취소면 정산이 취소·차감된다 — 활성 시절 예정액을 물려받으면 날조."""
    OS.save([{L.FIELD: "eleven11|ON6|1", "판매처": "11번가", "오픈마켓주문번호": "ON6",
              "주문일": "2026-07-18 09:00:00", "주문상태": "결제완료",
              "상품명": "코트", "정산예정금액": 169155}], session=session)
    claim = {"판매처": "11번가", "오픈마켓주문번호": "ON6", "_kind": "change",
             "_line_uid": "eleven11|ON6|1", "주문상태": "반품완료",
             "상품명": "", "정산예정금액": ""}
    oe.fill_claim_blanks_from_history([claim], "eleven11", session=session,
                                      include_blank_orders=True,
                                      settle_from_store_for_orders=True)
    assert claim["정산예정금액"] == ""      # 정산은 안 물려받음
    assert claim["상품명"] == "코트"        # 상품명 등은 채움


# ── ③ 실효 수수료율 역산 추정(과거 실정산 비율) ────────────────────────────────

def _hist(uid, pid, paid, settle):
    return {L.FIELD: uid, "판매처": "옥션", "오픈마켓주문번호": uid.split("|")[1],
            "주문일": "2026-07-01 10:00:00", "주문상태": "배송완료",
            "상품명": "과거상품", "_pd_market_product_id": pid,
            "실결제금액": paid, "정산예정금액": settle, "_settle_source": "real"}


def test_같은_상품의_과거_실효수수료율로_추정한다(session):
    """실정산/실결제 비율에는 수수료·판매자부담할인·경유가 전부 녹아 있다(실측 비율)."""
    OS.save([_hist("auction|H1", "P9", 100000, 90000),
             _hist("auction|H2", "P9", 50000, 45000)], session=session)   # rate 0.9
    row = {"판매처": "옥션", "_kind": "order", "주문상태": "배송준비중",
           "_pd_market_product_id": "P9", "실결제금액": 63400,
           "정산예정금액": "", "오픈마켓주문번호": "N1"}
    oe.estimate_settle_from_history([row], "auction", session=session)
    assert row["정산예정금액"] == 57060      # 63400 × 0.9
    assert row["_settle_source"] == "estimated"


def test_같은_상품_이력이_없으면_마켓_중앙값_비율(session):
    OS.save([_hist("auction|H3", "PA", 100000, 88000),
             _hist("auction|H4", "PB", 100000, 90000),
             _hist("auction|H5", "PC", 100000, 92000)], session=session)
    row = {"판매처": "옥션", "_kind": "order", "주문상태": "배송준비중",
           "_pd_market_product_id": "PZ", "실결제금액": 10000,
           "정산예정금액": "", "오픈마켓주문번호": "N2"}
    oe.estimate_settle_from_history([row], "auction", session=session)
    assert row["정산예정금액"] == 9000       # 중앙값 0.9
    assert row["_settle_source"] == "estimated"


def test_이력이_아예_없으면_빈칸_유지(session):
    row = {"판매처": "옥션", "_kind": "order", "주문상태": "배송준비중",
           "실결제금액": 10000, "정산예정금액": "", "오픈마켓주문번호": "N3"}
    oe.estimate_settle_from_history([row], "auction", session=session)
    assert row["정산예정금액"] == ""         # 지어내지 않는다


def test_추정은_실정산_이력만_재료로_쓴다(session):
    """추정으로 추정을 만들면 오차가 복리로 는다 — estimated 행은 재료에서 제외."""
    OS.save([_hist("auction|H6", "P7", 100000, 50000) | {"_settle_source": "estimated"}],
            session=session)
    row = {"판매처": "옥션", "_kind": "order", "주문상태": "배송준비중",
           "_pd_market_product_id": "P7", "실결제금액": 10000,
           "정산예정금액": "", "오픈마켓주문번호": "N4"}
    oe.estimate_settle_from_history([row], "auction", session=session)
    assert row["정산예정금액"] == ""
