# -*- coding: utf-8 -*-
"""옥션·G마켓 클레임 빈칸 — 「주문 들어왔던 내역(저장분·등록DB) 뒤지기」 계약.

마켓 클레임 응답은 주문번호+상태뿐이고, 상품이 삭제되면 상품 API 도 이름을 못 준다
("삭제된 상품 입니다" — 2026-07-21 라이브 실측). 그때 남는 실데이터 소스 두 곳:
  ① 주문 적재분(market_order_lines) — 그 주문이 활성일 때 실제로 잡힌 행 전체
  ② 우리 등록 DB(set_channels→product_sets) — 우리가 그 사이트상품번호로 등록한 구성 이름
빈 칸만 채운다. 정산·주문조회가 이미 준 값은 절대 덮지 않는다(폴백·날조 금지).
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
    import lemouton.markets.models_orders  # noqa: F401 — 테이블 등록
    import lemouton.sets.models            # noqa: F401 — set_channels 등록
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
        Base.metadata.tables["product_sets"],
        Base.metadata.tables["set_channels"],
    ])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


def _stored_order(order_no="2566096092", **kw):
    row = {L.FIELD: f"auction|{order_no}", "판매처": "옥션",
           "오픈마켓주문번호": order_no, "주문일": "2026-07-16 22:03:00",
           "주문상태": "배송준비중", "상품명": "국내정품 나이키 이니시에이터 TRK3",
           "옵션": "270", "수량": 1, "단가": "63400", "구매자": "홍길동",
           "수령자": "홍길동", "주소": "서울 어딘가 1-2", "우편번호": "12345"}
    row.update(kw)
    return row


def _claim_row(order_no="2566096092", **kw):
    """클레임 행 — 마켓이 주문번호+상태만 줘서 대부분 빈칸."""
    row = {"판매처": "옥션", "오픈마켓주문번호": order_no, "_kind": "change",
           "주문상태": "취소완료", "배송메시지": "구매자 귀책 · 단순변심",
           "상품명": "", "옵션": "", "수량": "", "단가": "", "구매자": "",
           "수령자": "", "주소": "", "우편번호": ""}
    row.update(kw)
    return row


def test_클레임_빈칸을_저장된_원주문에서_채운다(session):
    """①저장분 — 활성일 때 잡힌 행이 있으면 상품명·옵션·구매자까지 통째로 채워진다."""
    OS.save([_stored_order()], session=session)
    claim = _claim_row(단가=63400)          # 단가는 정산이 먼저 채웠다고 가정
    oe.fill_claim_blanks_from_history([claim], "auction", session=session)
    assert claim["상품명"] == "국내정품 나이키 이니시에이터 TRK3"
    assert claim["옵션"] == "270"
    assert claim["구매자"] == "홍길동"
    assert claim["주소"] == "서울 어딘가 1-2"
    assert claim["단가"] == 63400            # 이미 있는 값은 안 덮는다
    assert "상품명" in (claim.get("_store_filled") or "")


def test_저장분의_상태는_클레임_상태를_덮지_않는다(session):
    """저장분 상태(배송준비중)가 취소완료를 덮으면 클레임이 사라진 것처럼 보인다."""
    OS.save([_stored_order()], session=session)
    claim = _claim_row()
    oe.fill_claim_blanks_from_history([claim], "auction", session=session)
    assert claim["주문상태"] == "취소완료"
    assert claim["배송메시지"] == "구매자 귀책 · 단순변심"   # 클레임 사유 유지
    assert claim["_kind"] == "change"


def test_저장분에_없으면_등록DB_구성이름으로_상품명만(session):
    """②등록DB — 사이트상품번호로 우리가 등록한 구성 이름을 상품명에 채운다."""
    from lemouton.sets.models import ProductSet, SetChannel
    ps = ProductSet(model_code="M1", name="나이키 TRK3 런닝화 구성")
    session.add(ps)
    session.flush()
    session.add(SetChannel(set_id=ps.id, market="auction",
                           market_product_id="F575628540", status="linked"))
    session.commit()
    claim = _claim_row(order_no="9999999999")
    claim["_pd_market_product_id"] = "F575628540"
    oe.fill_claim_blanks_from_history([claim], "auction", session=session)
    assert claim["상품명"] == "나이키 TRK3 런닝화 구성"
    assert claim.get("_regname_filled")


def test_아무데도_없으면_빈칸_그대로(session):
    """지어내지 않는다 — 저장분도 등록DB도 없으면 빈칸 유지."""
    claim = _claim_row(order_no="0000000000")
    oe.fill_claim_blanks_from_history([claim], "auction", session=session)
    assert claim["상품명"] == ""
    assert not claim.get("_store_filled")


def test_정상주문_행은_건드리지_않는다(session):
    """클레임(_kind=change)만 대상 — 정상 주문 행은 이 경로를 타면 안 된다."""
    OS.save([_stored_order()], session=session)
    normal = {"판매처": "옥션", "오픈마켓주문번호": "2566096092", "_kind": "order",
              "상품명": "", "주문상태": "배송중"}
    oe.fill_claim_blanks_from_history([normal], "auction", session=session)
    assert normal["상품명"] == ""            # 정상 행은 손대지 않음


def test_같은_조회의_같은_상품번호_정상주문에서_상품명을_얻는다(session):
    """③같은 사이트상품번호 = 같은 상품 — 같은 조회창의 정상주문 행이 이름을 안다.
    (실사례: 취소건 F575628540 은 삭제된 상품이라 상품API 실패, 그런데 같은 상품의
    다른 주문이 같은 창에 정상으로 잡혀 GoodsName 을 들고 있다.)"""
    normal = {"판매처": "옥션", "오픈마켓주문번호": "1111", "_kind": "order",
              "상품명": "나이키 TRK3 270", "_pd_market_product_id": "F575628540"}
    claim = _claim_row(order_no="2222")
    claim["_pd_market_product_id"] = "F575628540"
    oe.fill_claim_blanks_from_history([normal, claim], "auction", session=session)
    assert claim["상품명"] == "나이키 TRK3 270"
    assert claim.get("_pdname_filled") == "같은조회"


def test_저장분의_같은_상품번호_과거주문에서도_상품명을_얻는다(session):
    """④저장분을 상품번호로도 뒤진다 — 주문번호가 달라도 같은 상품이면 이름은 같다."""
    OS.save([_stored_order(order_no="0001",
                           **{"_pd_market_product_id": "F575628540",
                              "상품명": "나이키 TRK3 이니시에이터"})], session=session)
    claim = _claim_row(order_no="9998")
    claim["_pd_market_product_id"] = "F575628540"
    oe.fill_claim_blanks_from_history([claim], "auction", session=session)
    assert claim["상품명"] == "나이키 TRK3 이니시에이터"
    assert claim.get("_pdname_filled") == "저장분"
