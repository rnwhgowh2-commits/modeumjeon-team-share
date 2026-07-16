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
    assert sv.derive_stage(req, acknowledged=True) == "대응필요"
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
    assert [c["오픈마켓주문번호"] for c in res["groups"]["대응필요"]] == ["LO1"]
    assert [c["오픈마켓주문번호"] for c in res["groups"]["대응완료"]] == ["CP1"]   # 완료=자동
    assert res["groups"]["신규요청"] == []
    assert res["market_counts"]["전체"] == 2
