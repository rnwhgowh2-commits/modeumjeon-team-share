# -*- coding: utf-8 -*-
"""정산액과 그 근거 태그(`_settle_source`)가 갈라지면 안 된다.

배경(2026-07-25 라이브 실측) — 마진계산기가 G마켓 구매결정 주문의 정산금을 0 으로
보여줬다. 주문내역 탭은 같은 주문을 69,530 으로 보여주는데도.

저장된 원본 행:
    "정산예정금(배송비포함)": 69530,   ← 값은 있다
    "수수료율": "15.0%", "주문상태": "구매결정",
    "_settle_source": "none"          ← 근거 태그만 없다

마진계산기(`sell_source._settlement_for`)는 취소건 배송비 잔존을 정산으로 오인하지
않으려고 **근거 태그가 real/store/estimated 일 때만** 그 금액을 쓴다. 태그가 떨어져
나가면 값이 멀쩡해도 0 이 된다.

갈라진 경위(43건 전수 같은 지문: 구매결정 · `_settle_filled='실결제금액'` · 같은 날):
  ① 이전 수집 — 단가를 받아 정산 추정 69,530 + 태그 `estimated` 저장
  ② 다음 수집 — 같은 주문을 **단가·실결제 공란**으로 받음 → 추정이 밑값(단가×수량)을
     못 구해 건너뜀 → 새 행의 태그는 초깃값 `none`
  ③ 저장 병합(`_merge_row`)이 **빈 값은 안 덮지만 `"none"` 은 빈 값이 아니라서 덮는다**
     → 금액은 살아남고 태그만 `none` 으로 교체
  ④ `구매결정`은 DONE_STATUSES 라 다시 조회되지 않아 영구 고착

라이브 피해: G마켓 44 · 롯데온 124 · 11번가 57 · 스스 1 = 226건.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.margin import sell_source as SS
from lemouton.markets import line_uid as L
from lemouton.markets import order_export as OE
from lemouton.markets import order_store as OS


@pytest.fixture
def session():
    import lemouton.markets.models_orders  # noqa: F401  — 테이블 등록
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


def _gmarket_row(**kw):
    row = {L.FIELD: "gmarket|4463818179", "판매처": "G마켓", "쇼핑몰": "G마켓",
           "오픈마켓주문번호": "4463818179", "주문일": "2026-07-01 23:00:06",
           "주문상태": "구매결정", "상품명": "나이키 리엑스 8",
           "단가": 81800, "수량": 1, "실결제금액": 81800, "배송비": 0}
    row.update(kw)
    return row


# ── A. 저장 병합: 정산액을 안 가져온 조회는 근거 태그도 갱신하지 않는다 ──────────

def test_정산액_없는_재조회가_근거태그를_지우지_않는다(session):
    """②③ 재현 — 나중 조회가 단가를 못 줘 추정이 건너뛴 행이 태그를 덮으면,
    금액만 남고 근거가 사라져 마진계산기가 그 돈을 못 본다."""
    OS.save([_gmarket_row(정산예정금액=69530, _settle_source="estimated")],
            session=session)
    # 다음 수집 — 단가·실결제 공란(마켓이 안 줌) → 추정 건너뜀 → 태그 초깃값 none
    OS.save([_gmarket_row(단가="", 실결제금액="", 정산예정금액="",
                          _settle_source="none", _settle_filled="실결제금액 ")],
            session=session)

    stored = OS.load(["gmarket"], since="2026-07-01", until="2026-07-01",
                     session=session)
    assert len(stored) == 1
    assert str(stored[0]["정산예정금액"]) == "69530"      # 금액은 지금도 지켜진다
    assert stored[0]["_settle_source"] == "estimated"     # 근거도 함께 지켜져야 한다


def test_정산액을_실제로_가져온_조회는_근거태그를_갱신한다(session):
    """반대 방향 — 새 조회가 진짜 정산액을 가져왔으면 태그는 당연히 갱신된다."""
    OS.save([_gmarket_row(정산예정금액=69530, _settle_source="estimated")],
            session=session)
    OS.save([_gmarket_row(정산예정금액=68900, _settle_source="real")], session=session)

    stored = OS.load(["gmarket"], since="2026-07-01", until="2026-07-01",
                     session=session)
    assert str(stored[0]["정산예정금액"]) == "68900"
    assert stored[0]["_settle_source"] == "real"


def test_취소완료_확정은_근거태그를_덮는다(session):
    """취소완료(zero_cancel)는 정산액 0 을 **가져온** 조회다 — 태그가 갱신돼야 한다.
    안 그러면 취소된 주문이 옛 추정액을 정산으로 계속 들고 있게 된다."""
    OS.save([_gmarket_row(정산예정금액=69530, _settle_source="estimated")],
            session=session)
    OS.save([_gmarket_row(주문상태="취소완료", 정산예정금액=0,
                          _settle_source="zero_cancel")], session=session)

    stored = OS.load(["gmarket"], since="2026-07-01", until="2026-07-01",
                     session=session)
    assert stored[0]["_settle_source"] == "zero_cancel"


# ── B. 읽기 시 치유: 이미 갈라져 저장된 226건 ────────────────────────────────

def test_값만_남고_태그_없는_행은_저장분_근거로_태깅된다(session):
    """이미 갈라진 채 저장된 행은 재조회로 못 고친다(구매결정=DONE_STATUSES).
    읽을 때 `store`(저장분에서 물려받음)로 태깅해 주문내역과 같은 숫자를 쓰게 한다.
    금액은 손대지 않는다 — 태그만 정직한 값으로 되돌린다."""
    row = _gmarket_row(정산예정금액=69530, _settle_source="none",
                       _settle_filled="실결제금액 ")
    OE.enrich_stored_rows([row], session=session)

    assert str(row["정산예정금액"]) == "69530"          # 금액은 그대로
    assert row["_settle_source"] == "store"
    assert str(row["정산예정금(배송비포함)"]) == "69530"


def test_취소완료_행은_치유하지_않는다(session):
    """취소건에 남은 잔존 금액을 정산으로 되살리면 안 된다 — 그게 태그 검사를
    넣은 이유다(2026-07-23 롯데온 가짜 정산 50,350 전례)."""
    row = _gmarket_row(주문상태="취소완료", 정산예정금액=69530,
                       _settle_source="none")
    OE.enrich_stored_rows([row], session=session)

    assert row["_settle_source"] == "zero_cancel"
    assert str(row["정산예정금액"]) == "0"


def test_금액이_없으면_태깅하지_않는다(session):
    """없는 정산을 지어내지 않는다 — 태그만 붙으면 0 원이 '정산됨'이 된다."""
    row = _gmarket_row(정산예정금액="", _settle_source="none")
    OE.enrich_stored_rows([row], session=session)

    assert row["_settle_source"] == "none"


def test_실결제금액이_빈칸이어도_치유된다(session):
    """🔴 2026-07-25 배포 직후 실측 — G마켓 43건 중 12건(495,640원)이 안 고쳐졌다.
    저장분의 `실결제금액`은 빈칸인 행이 흔하고(마켓이 안 줌 — `_settle_filled` 흔적),
    그 칸은 `_finalize_rows` 가 원금(단가×수량)으로 채운다. 치유를 그 앞에서 돌리면
    비교할 매출이 없어 「수수료가 빠졌는지 모르겠다」로 건너뛴다 — 뒤에서 돌려야 한다."""
    row = _gmarket_row(단가="32000.0000", 실결제금액="", 정산예정금액=27065,
                       _settle_source="none", _settle_filled="실결제금액 ")
    OE.enrich_stored_rows([row], session=session)

    assert row["_settle_source"] == "store"
    assert SS._settlement_for(row) == (27065, "store")


def test_수수료가_안_빠진_금액은_정산으로_인정하지_않는다(session):
    """🔴 2026-07-25 라이브 실측 — 롯데온 `회수지시` 112건(1,240만원)이
    `정산예정금액 == 실결제금액 == 44,800` 이었다(수수료 4,032 은 별도 칸).
    정산액이 아니라 **매출액이 정산 칸에 실린** 것이다. 상태 이름이 아니라 돈으로 거른다."""
    row = {L.FIELD: "lotteon|2026062210302505|1|X", "판매처": "롯데온", "쇼핑몰": "롯데온",
           "오픈마켓주문번호": "2026062210302505", "주문일": "2026-06-28 13:50:49",
           "주문상태": "회수지시", "상품명": "다이나핏 보드숏", "단가": 44800, "수량": 1,
           "실결제금액": 44800, "정산예정금액": 44800, "마켓수수료": 4032,
           "배송비": 0, "_settle_source": "none"}
    OE.enrich_stored_rows([row], session=session)

    assert row["_settle_source"] == "none"


# ── C. 끝에서 끝까지: 마진계산기가 주문내역과 같은 숫자를 본다 ────────────────

def test_마진계산기가_주문내역과_같은_정산금을_쓴다(session):
    """사장님 화면 재현 — 판매가 81,800 / 매입 59,510 인데 정산 0 → -59,510 손실로
    보이던 그 행. 주문내역은 같은 주문을 69,530 으로 보여준다."""
    row = _gmarket_row(정산예정금액=69530, _settle_source="none",
                       _settle_filled="실결제금액 ")
    OE.enrich_stored_rows([row], session=session)

    settle, src = SS._settlement_for(row)
    assert settle == 69530
    assert src == "store"
