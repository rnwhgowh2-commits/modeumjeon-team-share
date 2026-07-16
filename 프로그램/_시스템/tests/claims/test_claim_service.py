# -*- coding: utf-8 -*-
"""CS 클레임 처리상태 모델·서비스."""
import datetime as dt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from shared.db import Base


@pytest.fixture()
def session():
    import lemouton.claims.models  # 모델 등록
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    yield s
    s.close()


def test_claim_handling_table_created(session):
    from lemouton.claims.models import ClaimHandling
    row = ClaimHandling(claim_key="롯데온:LO1:반품", market="롯데온", order_no="LO1", claim_type="반품")
    session.add(row); session.commit()
    got = session.query(ClaimHandling).filter_by(claim_key="롯데온:LO1:반품").one()
    assert got.acknowledged_at is None and got.memo is None


def test_derive_helpers():
    from lemouton.claims import service as sv
    req = {"판매처": "롯데온", "오픈마켓주문번호": "LO1", "주문상태": "취소요청", "주문상태원본": "02"}
    done = {"판매처": "쿠팡", "오픈마켓주문번호": "CP1", "주문상태": "반품완료", "주문상태원본": "RETURNS_COMPLETED"}
    wd_lo = {"판매처": "롯데온", "오픈마켓주문번호": "LO2", "주문상태": "취소요청", "주문상태원본": "22"}  # 철회
    assert sv.claim_key_of(req) == "롯데온:LO1:취소"
    assert sv.claim_type_of(req) == "취소" and sv.claim_type_of(done) == "반품"
    assert sv.is_terminal(done) is True
    assert sv.is_terminal(wd_lo) is True          # 철회(raw 22)=종결
    assert sv.is_terminal(req) is False
    assert sv.derive_stage(done, acknowledged=False) == "대응완료"
    assert sv.derive_stage(wd_lo, acknowledged=False) == "대응완료"
    assert sv.derive_stage(req, acknowledged=True) == "대응중"
    assert sv.derive_stage(req, acknowledged=False) == "신규요청"
    assert sv.derive_stage(done, acknowledged=True) == "대응완료"   # 종결은 확인해도 대응완료


def test_acknowledge_and_memo_upsert(session):
    from lemouton.claims import service as sv
    from lemouton.claims.models import ClaimHandling
    sv.acknowledge("롯데온:LO1:반품", market="롯데온", order_no="LO1", claim_type="반품", session=session)
    got = session.query(ClaimHandling).filter_by(claim_key="롯데온:LO1:반품").one()
    assert got.acknowledged_at is not None
    sv.save_memo("롯데온:LO1:반품", "전화완료·수거대기", session=session)
    got2 = session.query(ClaimHandling).filter_by(claim_key="롯데온:LO1:반품").one()
    assert got2.memo == "전화완료·수거대기" and got2.acknowledged_at is not None   # 확인 유지
    sv.acknowledge("롯데온:LO1:반품", market="롯데온", order_no="LO1", claim_type="반품", session=session)
    assert session.query(ClaimHandling).filter_by(claim_key="롯데온:LO1:반품").count() == 1


def test_unacknowledge_reverts_to_new(session):
    """되돌리기 — acknowledged_at 제거로 대응중→신규요청 복귀, 메모는 유지."""
    from lemouton.claims import service as sv
    from lemouton.claims.models import ClaimHandling
    sv.acknowledge("쿠팡:C1:반품", market="쿠팡", order_no="C1", claim_type="반품", session=session)
    sv.save_memo("쿠팡:C1:반품", "메모유지", session=session)
    assert session.query(ClaimHandling).filter_by(claim_key="쿠팡:C1:반품").one().acknowledged_at is not None
    sv.unacknowledge("쿠팡:C1:반품", session=session)
    got = session.query(ClaimHandling).filter_by(claim_key="쿠팡:C1:반품").one()
    assert got.acknowledged_at is None and got.memo == "메모유지"       # 확인만 풀리고 메모 유지
    assert sv.derive_stage({"주문상태": "반품요청"}, acknowledged=bool(got.acknowledged_at)) == "신규요청"
    sv.unacknowledge("쿠팡:NOPE:반품", session=session)                 # 없는 키 = 조용히 무시(에러 없음)


def test_list_claims_groups_and_counts(session, monkeypatch):
    from lemouton.claims import service as sv
    import datetime as dt
    KST = dt.timezone(dt.timedelta(hours=9))
    change_rows = [
        {"판매처": "롯데온", "오픈마켓주문번호": "LO1", "주문상태": "취소요청", "주문상태원본": "02",
         "_change_date": "20260715120000", "상품명": "코트", "옵션": "블랙", "수량": 1, "배송메시지": "변심"},
        {"판매처": "쿠팡", "오픈마켓주문번호": "CP1", "주문상태": "반품완료", "주문상태원본": "RETURNS_COMPLETED",
         "_change_date": "20260715090000", "상품명": "니트", "옵션": "M", "수량": 1, "배송메시지": ""},
    ]
    monkeypatch.setattr(sv, "status_change_rows", lambda markets, **kw: change_rows)
    sv.acknowledge("롯데온:LO1:취소", market="롯데온", order_no="LO1", claim_type="취소", session=session)
    since = dt.datetime(2026, 7, 15, tzinfo=KST); until = dt.datetime(2026, 7, 15, 23, tzinfo=KST)
    res = sv.list_claims(["lotteon", "coupang"], since=since, until=until, session=session)
    assert [c["오픈마켓주문번호"] for c in res["groups"]["대응중"]] == ["LO1"]
    assert [c["오픈마켓주문번호"] for c in res["groups"]["대응완료"]] == ["CP1"]   # 완료=자동
    assert res["groups"]["신규요청"] == []
    assert res["market_counts"]["전체"] == 2


def test_done_retention_7days_and_dismiss(session, monkeypatch):
    from lemouton.claims import service as sv
    import datetime as dt
    KST = dt.timezone(dt.timedelta(hours=9))
    now = dt.datetime(2026, 7, 16, 12, tzinfo=KST)
    rows = [
        {"판매처": "롯데온", "오픈마켓주문번호": "D1", "주문상태": "취소완료", "주문상태원본": "21", "_change_date": "20260715120000"},  # 1일전=노출
        {"판매처": "롯데온", "오픈마켓주문번호": "D8", "주문상태": "취소완료", "주문상태원본": "21", "_change_date": "20260706120000"},  # 10일전=숨김
        {"판매처": "쿠팡", "오픈마켓주문번호": "D2", "주문상태": "취소완료", "주문상태원본": "RETURNS_COMPLETED", "_change_date": "20260716010000"},  # 오늘→삭제
        {"판매처": "11번가", "오픈마켓주문번호": "N1", "주문상태": "취소요청", "주문상태원본": "02", "_change_date": "20260701000000"},  # 요청=항상노출
    ]
    monkeypatch.setattr(sv, "status_change_rows", lambda markets, **kw: rows)
    sv.dismiss_claim("쿠팡:D2:취소", market="쿠팡", order_no="D2", claim_type="취소", session=session)
    res = sv.list_claims(["lotteon","coupang","eleven11"], since=now, until=now, now=now, session=session)
    done = {c["오픈마켓주문번호"] for c in res["groups"]["대응완료"]}
    assert done == {"D1"}
    assert {c["오픈마켓주문번호"] for c in res["groups"]["신규요청"]} == {"N1"}
