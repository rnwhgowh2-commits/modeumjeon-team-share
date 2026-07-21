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
    import lemouton.delivery.models        # noqa: F401 — mango_orders 등록
    import lemouton.markets.models_shopmine  # noqa: F401 — shopmine_orders 등록
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
        Base.metadata.tables["product_sets"],
        Base.metadata.tables["set_channels"],
        Base.metadata.tables["mango_orders"],
        Base.metadata.tables["shopmine_orders"],
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


# ── 롯데온·11번가 확장 (2026-07-21 사장님: 6마켓 전체 공란 채움) ─────────────

def test_롯데온_클레임의_구매자_주소_실결제를_저장분에서_채운다(session):
    """라이브 감사: 롯데온 클레임 76건 중 73건이 구매자·수령자·주소·실결제 공란."""
    OS.save([{L.FIELD: "lotteon|OD1|1", "판매처": "롯데온", "오픈마켓주문번호": "OD1",
              "주문일": "2026-07-16 10:00:00", "주문상태": "배송준비중",
              "상품명": "라코스테 치노", "구매자": "김철수", "수령자": "김철수",
              "주소": "부산 어딘가 3-4", "우편번호": "54321",
              "실결제금액": 134170}], session=session)
    claim = {"판매처": "롯데온", "오픈마켓주문번호": "OD1", "_kind": "change",
             "주문상태": "취소완료", "상품명": "라코스테 치노", "구매자": "",
             "수령자": "", "주소": "", "우편번호": "", "실결제금액": ""}
    oe.fill_claim_blanks_from_history([claim], "lotteon", session=session)
    assert claim["구매자"] == "김철수"
    assert claim["주소"] == "부산 어딘가 3-4"
    assert claim["실결제금액"] == 134170
    assert claim["주문상태"] == "취소완료"       # 상태는 안 덮는다


def test_11번가_배송중_빈행도_저장분에서_채운다(session):
    """라이브 감사: 11번가 배송중 목록은 상품 상세를 안 줘 8건이 통째 공란(_kind=order).
    include_blank_orders=True 면 상품명이 빈 정상 행도 저장분으로 채운다."""
    OS.save([{L.FIELD: "eleven11|ON1|1", "판매처": "11번가", "오픈마켓주문번호": "ON1",
              "주문일": "2026-07-18 09:00:00", "주문상태": "배송준비중",
              "상품명": "코트", "옵션": "블랙/95", "수량": "2", "단가": "189000",
              "수령자": "박영희"}], session=session)
    row = {"판매처": "11번가", "오픈마켓주문번호": "ON1", "_kind": "order",
           "_line_uid": "eleven11|ON1|1", "주문상태": "배송중",
           "상품명": "", "옵션": "", "수량": "", "단가": "", "수령자": ""}
    oe.fill_claim_blanks_from_history([row], "eleven11", session=session,
                                      include_blank_orders=True)
    assert row["상품명"] == "코트"
    assert row["단가"] == "189000"
    assert row["주문상태"] == "배송중"           # 최신 상태 유지


def test_더망고_업로드분에서_수령자_전화_상품명을_채운다(session):
    """⑤더망고 — 사장님이 올리는 전 마켓 주문 대조 자료. 롯데온 취소 API 는 구매자
    정보를 안 준다(2026-07-21 라이브 프로브 확정) — 더망고가 마지막 실데이터 소스."""
    from lemouton.delivery.models import MangoOrder
    session.add(MangoOrder(mango_uid="MG1", market_order_no="2026071918259609",
                           market_name="롯데온", recipient="이영희",
                           phone="010-9999-8888", product_name="라코스테 치노 팬츠",
                           option1="044", raw={"수령인주소": "서울 송파구 어딘가 5"}))
    session.commit()
    claim = {"판매처": "롯데온", "오픈마켓주문번호": "2026071918259609",
             "_kind": "change", "주문상태": "취소완료",
             "상품명": "", "옵션": "", "수령자": "", "수령자전화번호": "", "주소": ""}
    oe.fill_claim_blanks_from_history([claim], "lotteon", session=session)
    assert claim["수령자"] == "이영희"
    assert claim["수령자전화번호"] == "010-9999-8888"
    assert claim["상품명"] == "라코스테 치노 팬츠"
    assert claim["주소"] == "서울 송파구 어딘가 5"   # raw 의 주소류 키에서
    assert "수령자" in (claim.get("_mango_filled") or "")


def test_샵마인_적재분에서_구매자_주소_실결제까지_채운다(session):
    """⑥샵마인 — 마켓 취소 API 가 안 주는 값을 샵마인이 취소 전에 받아뒀다.
    라이브 대조(2026-07-22): 롯데온 공란 38건 중 24건이 샵마인에 전부 값 보유."""
    from lemouton.markets.models_shopmine import ShopmineOrder
    session.add(ShopmineOrder(sm_uid="SM1", market="lotteon",
                              order_no="2026071516654239", buyer="최대혁",
                              recipient="최대혁", phone="010-1111-2222",
                              buyer_phone="010-1111-2222", zipcode="12345",
                              address="서울 강남 테헤란로 1",
                              product_name="라코스테 스니커즈", option1="270",
                              qty="1", unit_price="151800", paid_amount="147900"))
    session.commit()
    claim = {"판매처": "롯데온", "오픈마켓주문번호": "2026071516654239",
             "_kind": "change", "주문상태": "취소완료",
             "상품명": "", "옵션": "", "수량": "", "단가": "", "실결제금액": "",
             "구매자": "", "구매자번호": "", "수령자": "", "수령자전화번호": "",
             "주소": "", "우편번호": ""}
    oe.fill_claim_blanks_from_history([claim], "lotteon", session=session)
    assert claim["구매자"] == "최대혁"
    assert claim["수령자전화번호"] == "010-1111-2222"
    assert claim["주소"] == "서울 강남 테헤란로 1"
    assert claim["실결제금액"] == "147900"
    assert claim["상품명"] == "라코스테 스니커즈"
    assert claim["단가"] == "151800"
    assert "구매자" in (claim.get("_shopmine_filled") or "")
    assert claim["주문상태"] == "취소완료"      # 상태 안 덮음


def test_샵마인_다품주문은_연락처만_채우고_상품값은_안_섞는다(session):
    """같은 주문번호에 라인 2개 — 어느 상품인지 특정 불가면 상품·금액은 안 채운다.
    연락처(구매자·주소)는 주문 단위라 어느 라인이든 같아 안전하게 채운다."""
    from lemouton.markets.models_shopmine import ShopmineOrder
    session.add(ShopmineOrder(sm_uid="SM2", market="lotteon", order_no="900",
                              buyer="김구매", address="부산 해운대 1",
                              product_name="상품A", unit_price="10000"))
    session.add(ShopmineOrder(sm_uid="SM3", market="lotteon", order_no="900",
                              buyer="김구매", address="부산 해운대 1",
                              product_name="상품B", unit_price="20000"))
    session.commit()
    claim = {"판매처": "롯데온", "오픈마켓주문번호": "900", "_kind": "change",
             "주문상태": "취소완료", "상품명": "", "단가": "", "구매자": "", "주소": ""}
    oe.fill_claim_blanks_from_history([claim], "lotteon", session=session)
    assert claim["구매자"] == "김구매"          # 주문 단위 정보는 채움
    assert claim["주소"] == "부산 해운대 1"
    assert claim["상품명"] == ""                # 라인 특정 불가 → 안 섞음
    assert claim["단가"] == ""


def test_더망고_다품주문은_송장번호로_라인을_특정해_상품명을_채운다(session):
    """실사례(2026-07-22): 11번가 20260716085481341 — 한 주문 2라인(송장 2개),
    배송중 목록은 송장만 줌. 더망고엔 실제 송장번호가 있어 라인 정확 매칭 가능."""
    from lemouton.delivery.models import MangoOrder
    session.add(MangoOrder(mango_uid="MG10", market_order_no="555", market_name="11번가",
                           recipient="김민", invoice_no="91721129835",
                           product_name="볼캡 블랙", option1="F"))
    session.add(MangoOrder(mango_uid="MG11", market_order_no="555", market_name="11번가",
                           recipient="김민", invoice_no="91721134396",
                           product_name="저지탑 그레이", option1="M"))
    session.commit()
    row = {"판매처": "11번가", "오픈마켓주문번호": "555", "_kind": "order",
           "주문상태": "배송중", "_line_uid": "eleven11|555|2",
           "송장입력": "91721134396", "상품명": "", "옵션": "", "수령자": ""}
    oe.fill_claim_blanks_from_history([row], "eleven11", session=session,
                                      include_blank_orders=True)
    assert row["상품명"] == "저지탑 그레이"      # 송장 일치 라인의 상품(볼캡 아님!)
    assert row["옵션"] == "M"
    assert row["수령자"] == "김민"


def test_더망고_다품인데_송장도_없으면_상품명은_안_섞는다(session):
    """라인 특정 불가 → 연락처(주문 단위)만 채우고 상품은 비워둔다(날조 금지)."""
    from lemouton.delivery.models import MangoOrder
    session.add(MangoOrder(mango_uid="MG12", market_order_no="556", market_name="11번가",
                           recipient="박도", invoice_no="111", product_name="상품A"))
    session.add(MangoOrder(mango_uid="MG13", market_order_no="556", market_name="11번가",
                           recipient="박도", invoice_no="222", product_name="상품B"))
    session.commit()
    row = {"판매처": "11번가", "오픈마켓주문번호": "556", "_kind": "order",
           "주문상태": "배송중", "송장입력": "", "상품명": "", "수령자": ""}
    oe.fill_claim_blanks_from_history([row], "eleven11", session=session,
                                      include_blank_orders=True)
    assert row["수령자"] == "박도"              # 주문 단위는 채움
    assert row["상품명"] == ""                  # 어느 라인인지 몰라 안 섞음


def test_더망고_마켓명이_다르면_같은_주문번호라도_안_섞는다(session):
    """주문번호가 우연히 같아도 다른 마켓 건이면 채우면 안 된다(날조 방지)."""
    from lemouton.delivery.models import MangoOrder
    session.add(MangoOrder(mango_uid="MG2", market_order_no="777",
                           market_name="쿠팡", recipient="김쿠팡"))
    session.add(MangoOrder(mango_uid="MG3", market_order_no="777",
                           market_name="11번가", recipient="박십일"))
    session.commit()
    claim = {"판매처": "롯데온", "오픈마켓주문번호": "777", "_kind": "change",
             "주문상태": "취소완료", "수령자": ""}
    oe.fill_claim_blanks_from_history([claim], "lotteon", session=session)
    assert claim["수령자"] == ""                     # 마켓 불일치 → 안 채움


def test_연락처_빈_정상행도_저장분에서_채운다(session):
    """쿠팡 배송완료 후 안심번호가 폐기돼 전화번호가 빈다(라이브 감사 4건) —
    활성일 때 잡아둔 저장분이 유일한 소스다."""
    OS.save([{L.FIELD: "coupang|CP1|V1", "판매처": "쿠팡", "오픈마켓주문번호": "CP1",
              "주문일": "2026-07-16 10:00:00", "주문상태": "배송중",
              "상품명": "가방", "수령자전화번호": "010-1234-5678",
              "구매자번호": "010-1234-5678"}], session=session)
    row = {"판매처": "쿠팡", "오픈마켓주문번호": "CP1", "_kind": "order",
           "_line_uid": "coupang|CP1|V1", "주문상태": "배송완료",
           "상품명": "가방", "수령자전화번호": "", "구매자번호": ""}
    oe.fill_claim_blanks_from_history([row], "coupang", session=session,
                                      include_blank_contact_orders=True)
    assert row["수령자전화번호"] == "010-1234-5678"
    assert row["구매자번호"] == "010-1234-5678"
    assert row["주문상태"] == "배송완료"        # 상태 안 덮음


def test_같은_주문번호_여러라인이면_line_uid_정확일치로_채운다(session):
    """다품 주문 — 주문번호만으로는 어느 상품인지 특정 불가. line_uid 가 같으면 그 라인."""
    OS.save([
        {L.FIELD: "eleven11|ON2|1", "판매처": "11번가", "오픈마켓주문번호": "ON2",
         "주문일": "2026-07-18 09:00:00", "주문상태": "배송준비중", "상품명": "코트A"},
        {L.FIELD: "eleven11|ON2|2", "판매처": "11번가", "오픈마켓주문번호": "ON2",
         "주문일": "2026-07-18 09:00:00", "주문상태": "배송준비중", "상품명": "코트B"},
    ], session=session)
    row = {"판매처": "11번가", "오픈마켓주문번호": "ON2", "_kind": "order",
           "_line_uid": "eleven11|ON2|2", "주문상태": "배송중", "상품명": ""}
    oe.fill_claim_blanks_from_history([row], "eleven11", session=session,
                                      include_blank_orders=True)
    assert row["상품명"] == "코트B"              # uid 일치 라인(주문번호 조인이면 못 채움)
