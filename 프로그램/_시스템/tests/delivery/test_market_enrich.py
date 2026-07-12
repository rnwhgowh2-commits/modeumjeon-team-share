import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
import lemouton.delivery.models as M
from lemouton.delivery import market_enrich as me


def test_market_slug():
    assert me.market_slug("쿠팡") == "coupang"
    assert me.market_slug("롯데ON") == "lotteon"
    assert me.market_slug("롯데온") == "lotteon"
    assert me.market_slug("스마트스토어") == "smartstore"
    assert me.market_slug("11번가") == "eleven11"
    assert me.market_slug("무신사") is None   # 마켓 API 미지원 → 스킵


def test_group_by_market():
    rows = [{"mango_uid": "1", "market_name": "쿠팡", "market_order_no": "A"},
            {"mango_uid": "2", "market_name": "롯데ON", "market_order_no": "B"},
            {"mango_uid": "3", "market_name": "무신사", "market_order_no": "C"}]
    grouped, skipped = me.group_by_market(rows)
    assert set(grouped.keys()) == {"coupang", "lotteon"}
    assert grouped["coupang"] == ["A"]
    assert skipped == ["3"]


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _seed(db, uid, market, no):
    db.add(M.MangoOrder(mango_uid=uid, market_name=market, market_order_no=no,
                        mango_status="해외현지배송중"))
    db.commit()


def test_enrich_matches_and_caches(db, monkeypatch):
    _seed(db, "1", "쿠팡", "A100")
    _seed(db, "2", "롯데ON", "B200")
    _seed(db, "3", "무신사", "C300")   # 미지원 → 확인불가

    def fake_rows(markets, **kw):
        return [
            {"판매처": "쿠팡", "오픈마켓주문번호": "A100", "주문상태": "배송중", "송장입력": "INV-A"},
            {"판매처": "롯데온", "오픈마켓주문번호": "B200", "주문상태": "배송준비중", "송장입력": "송장미입력"},
        ]
    monkeypatch.setattr(me._oe, "combined_order_rows", fake_rows)

    res = me.enrich_from_market_api(db, ["1", "2", "3"])
    o1 = db.query(M.MangoOrder).filter_by(mango_uid="1").one()
    o2 = db.query(M.MangoOrder).filter_by(mango_uid="2").one()
    o3 = db.query(M.MangoOrder).filter_by(mango_uid="3").one()
    assert o1.market_api_status == "배송중" and o1.market_api_invoice == "INV-A" and not o1.market_check_error
    assert o2.market_api_status == "배송준비중" and o2.market_api_invoice == ""   # 송장미입력→빈값
    assert o3.market_check_error and "지원" in o3.market_check_error            # 미지원 마켓
    assert res["checked"] == 2


def test_enrich_unmatched_and_fetch_fail(db, monkeypatch):
    _seed(db, "10", "쿠팡", "NOEXIST")      # 마켓 응답에 없음

    def fake_rows(markets, **kw):
        return []
    monkeypatch.setattr(me._oe, "combined_order_rows", fake_rows)
    me.enrich_from_market_api(db, ["10"])
    o = db.query(M.MangoOrder).filter_by(mango_uid="10").one()
    assert o.market_check_error and "못 찾" in o.market_check_error


def test_match_keys_paren():
    # 스마트스토어 괄호형 '주문번호(상품주문번호)' → 상품주문번호(안)·주문번호(밖) 후보 포함
    assert me._match_keys("2026070695107551(2026070668195471)") == [
        "2026070695107551(2026070668195471)", "2026070668195471", "2026070695107551"]
    assert me._match_keys("A100") == ["A100"]


def test_enrich_matches_paren_orderno(db, monkeypatch):
    # 더망고엔 괄호형으로 저장, 마켓은 상품주문번호(괄호 안)만 반환 → 매칭돼야 함
    db.add(M.MangoOrder(mango_uid="P1", market_name="스마트스토어",
                        market_order_no="2026070695107551(2026070668195471)",
                        mango_status="해외현지배송중"))
    db.commit()
    monkeypatch.setattr(me._oe, "combined_order_rows", lambda markets, **kw: [
        {"판매처": "스마트스토어", "오픈마켓주문번호": "2026070668195471",
         "주문상태": "배송완료", "송장입력": "INV-SS"}])
    me.enrich_from_market_api(db, ["P1"])
    o = db.query(M.MangoOrder).filter_by(mango_uid="P1").one()
    assert o.market_check_error is None          # 확인불가 아님(매칭 성공)
    assert o.market_api_status == "배송완료" and o.market_api_invoice == "INV-SS"
