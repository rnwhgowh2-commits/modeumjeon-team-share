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


def test_enrich_unmatched_fetch_fail(db, monkeypatch):
    # 쿠팡 응답이 아예 없음(조회 실패) → 사유=계정 조회 실패(IP/키)
    _seed(db, "10", "쿠팡", "NOEXIST")
    monkeypatch.setattr(me._oe, "combined_order_rows", lambda markets, **kw: [])
    me.enrich_from_market_api(db, ["10"])
    o = db.query(M.MangoOrder).filter_by(mango_uid="10").one()
    assert o.market_check_error and "조회 실패" in o.market_check_error


def test_enrich_unmatched_but_market_fetched(db, monkeypatch):
    # 쿠팡은 조회됐는데 그 주문만 없음 → 사유=기간 밖/취소
    _seed(db, "11", "쿠팡", "NOEXIST")
    monkeypatch.setattr(me._oe, "combined_order_rows", lambda markets, **kw: [
        {"판매처": "쿠팡", "오픈마켓주문번호": "OTHER", "주문상태": "배송중", "송장입력": "X"}])
    me.enrich_from_market_api(db, ["11"])
    o = db.query(M.MangoOrder).filter_by(mango_uid="11").one()
    assert o.market_check_error and ("기간" in o.market_check_error or "취소" in o.market_check_error)


def test_enrich_widens_window_and_skips_settlement(db, monkeypatch):
    # 해외배송중 = 오래된 주문(40여일 전). 7일 기본창 밖이라 조회 못 하던 문제 →
    # enrich 는 업로드된 주문의 '주문일'까지 조회 기간을 넓히고, 배송검사는 정산이
    # 필요 없으니 정산 조회를 건너뛴다(정산 하루씩 루프 = 넓은 창에서 타임아웃 원인).
    import datetime as _dt
    # 🔴 [2026-08-03] 주문일을 **못 박으면 안 된다**(달력만 지나가도 저절로 빨간불).
    #   조회 끝이 '지금'이고 소급 상한이 62일(_MAX_LOOKBACK_DAYS)이라, 못 박은
    #   '2026-06-01' 이 63일 전이 된 2026-08-02 부터 이 검사가 깨졌다.
    #   그 바람에 **main 배포가 통째로 막혔다**(#712·정산 PR 둘 다 실패).
    #   돈·로직은 멀쩡했다 — 검사만 썩은 것이다. 그래서 '오늘로부터 40일 전'으로 적는다
    #   (상한 62일 안쪽이라 언제 돌려도 같은 뜻: 7일 기본창 밖 · 소급 상한 안쪽).
    _주문일 = _dt.date.today() - _dt.timedelta(days=40)
    db.add(M.MangoOrder(mango_uid="OLD", market_name="스마트스토어",
                        market_order_no="SS-OLD", mango_status="해외현지배송중",
                        ordered_at=_주문일.isoformat()))
    db.commit()
    captured = {}

    def fake_rows(markets, **kw):
        captured.update(kw)
        return [{"판매처": "스마트스토어", "오픈마켓주문번호": "SS-OLD",
                 "주문상태": "배송중", "송장입력": "X"}]
    monkeypatch.setattr(me._oe, "combined_order_rows", fake_rows)

    me.enrich_from_market_api(db, ["OLD"])
    # ① 조회 기간이 그 주문일을 덮어야 매칭 가능
    since = captured.get("since")
    assert since is not None and since.date() <= _주문일
    # ② 배송검사는 정산 스킵(넓은 창 타임아웃 방지)
    assert captured.get("include_settlement") is False
    # 결과: 오래된 주문도 매칭됨
    o = db.query(M.MangoOrder).filter_by(mango_uid="OLD").one()
    assert o.market_check_error is None and o.market_api_status == "배송중"


def test_소급은_62일_상한에서_멈춘다(db, monkeypatch):
    """상한(_MAX_LOOKBACK_DAYS)을 **일부러** 밟는 짝 테스트.

    바로 위 테스트가 이 상한을 **우연히** 밟아 터졌었다(못 박은 2026-06-01 이 63일
    전이 된 날 아침 main 배포가 통째로 막힘 — #713 에서 상대날짜로 고침).
    우연이 아니라 의도적으로 한 번 밟아 둬야 상한 동작 자체가 보증된다
    (마켓 조회 한계·속도 보호). 위 테스트는 이제 상한 안쪽만 다니므로 여기가 유일한 커버다.
    """
    import datetime as _dt
    old = (_dt.datetime.now(me._KST) - _dt.timedelta(days=200)).date()
    db.add(M.MangoOrder(mango_uid="ANCIENT", market_name="스마트스토어",
                        market_order_no="SS-ANCIENT", mango_status="해외현지배송중",
                        ordered_at=old.strftime("%Y-%m-%d")))
    db.commit()
    captured = {}
    monkeypatch.setattr(me._oe, "combined_order_rows",
                        lambda markets, **kw: (captured.update(kw), [])[1])

    me.enrich_from_market_api(db, ["ANCIENT"])

    since = captured.get("since")
    days_back = (_dt.datetime.now(me._KST) - since).days
    assert days_back <= me._MAX_LOOKBACK_DAYS       # 200일 전까지 안 간다
    assert days_back >= me._MAX_LOOKBACK_DAYS - 1   # 상한까지는 간다


def test_iter_enrich_streams_per_market_events(db, monkeypatch):
    # 스트리밍: start(마켓목록) → 마켓마다 fetching/done(matched·total) → done.
    _seed(db, "1", "쿠팡", "A100")
    _seed(db, "2", "롯데ON", "B200")
    _seed(db, "3", "무신사", "C300")   # 미지원 → skipped
    monkeypatch.setattr(me._oe, "combined_order_rows", lambda markets, **kw: [
        {"판매처": "쿠팡", "오픈마켓주문번호": "A100", "주문상태": "배송중", "송장입력": "INV-A"},
        {"판매처": "롯데온", "오픈마켓주문번호": "B200", "주문상태": "배송준비중", "송장입력": "송장미입력"}])
    evs = list(me.iter_enrich(db, ["1", "2", "3"]))
    start = evs[0]
    assert start["phase"] == "start" and start["skipped"] == 1
    assert {m["slug"] for m in start["markets"]} == {"coupang", "lotteon"}
    done = evs[-1]
    assert done["phase"] == "done" and done["checked"] == 2 and done["skipped"] == 1
    # 마켓 done 이벤트에 matched/total 담김
    mdone = [e for e in evs if e.get("phase") == "market" and e.get("state") == "done"]
    assert {e["slug"]: e["matched"] for e in mdone} == {"coupang": 1, "lotteon": 1}


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


def test_enrich_matches_paren_outer_orderno(db, monkeypatch):
    # 반대 방향: 마켓이 '주문번호'(괄호 밖, orderId)를 오픈마켓주문번호로 줄 때도 매칭돼야 함.
    # 스스 빌더 오픈마켓주문번호 = productOrderId or orderId → 괄호 안·밖 둘 다 커버.
    db.add(M.MangoOrder(mango_uid="P2", market_name="스마트스토어",
                        market_order_no="2026070695107551(2026070668195471)",
                        mango_status="해외현지배송중"))
    db.commit()
    monkeypatch.setattr(me._oe, "combined_order_rows", lambda markets, **kw: [
        {"판매처": "스마트스토어", "오픈마켓주문번호": "2026070695107551",   # 괄호 밖(주문번호)
         "주문상태": "배송중", "송장입력": "INV-OUT"}])
    me.enrich_from_market_api(db, ["P2"])
    o = db.query(M.MangoOrder).filter_by(mango_uid="P2").one()
    assert o.market_check_error is None          # 괄호 밖 번호로도 매칭
    assert o.market_api_status == "배송중" and o.market_api_invoice == "INV-OUT"
