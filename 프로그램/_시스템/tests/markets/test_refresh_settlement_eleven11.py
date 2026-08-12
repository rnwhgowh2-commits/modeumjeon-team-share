# -*- coding: utf-8 -*-
"""11번가 정산 스윕 — 구매확정 뒤 인식되는 실정산(settlementList)을 옛 주문까지 되짚는다.

🔴 왜 11번가도 따로인가 — 정산 스윕이 없어 적재틱(21일)이 닫힌 뒤 구매확정된 주문의
  실정산(stlAmt)이 영영 안 들어와 추정치(stlPlnAmt)로 고착됐다(다른 5마켓이 이미 닫은 갭).

★ 조인 키 = (ordNo, ordPrdSeq) 라인 단위(다상품 주문 N배 계상 방지 — 인라인 조인과 동형).
★ 정산예정금액 = 정산금액 − 배송비정산(배송비 분리, 인라인 order_export:2592 규약).
★ rate 가 **IP 전역**이라 계정 **순차**(ESM·롯데온의 계정 병렬과 정반대 — 병렬 시 429 전체 죽음).
"""
from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.markets import line_uid as L
from lemouton.markets import order_ingest as OI
from lemouton.markets import order_store as OS

KST = _dt.timezone(_dt.timedelta(hours=9))


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


def _order_date(days_ago: int) -> str:
    return (_dt.datetime.now(KST) - _dt.timedelta(days=days_ago)
            ).strftime("%Y-%m-%d %H:%M:%S")


def _row(uid="eleven11|E100|1", ono="E100", seq="1", days_ago=40, **kw):
    """days_ago 기본 40 — 스윕이 '주문일 창'으로 좁히지 않음을 보이려 일부러 오래된 주문."""
    row = {L.FIELD: uid, "판매처": "11번가", "쇼핑몰": "11번가",
           "오픈마켓주문번호": ono, "_send_ids": {"ord_prd_seq": seq},
           "주문일": _order_date(days_ago), "주문상태": "구매확정",
           "상품명": "테스트 상품", "단가": 30000, "수량": 1,
           "실결제금액": 30000, "배송비": 0,
           "정산예정금액": 27000, "_settle_source": "estimated"}
    row.update(kw)
    return row


def _patch(monkeypatch, detail_map, clients=(("메인", object()),), seen_order=None):
    """detail_map = {(ordNo,ordPrdSeq): {"정산금액":int, "배송비정산":int?, "옵션추가금":int?}}."""
    monkeypatch.setattr(OI, "_esm_settlement_clients", lambda market: list(clients))
    from shared.platforms.eleven11 import settlement as _el

    def _fake(since, until, *, client=None):
        if seen_order is not None:
            seen_order.append(client)
        return {k: dict(v) for k, v in detail_map.items()}
    monkeypatch.setattr(_el, "settlement_detail_map", _fake)


def test_옛_주문_구매확정창이_덮으면_실정산으로_갱신(session, monkeypatch):
    OS.save([_row()], session=session)
    _patch(monkeypatch, {("E100", "1"): {"정산금액": 26500}})

    stat = OI.refresh_settlement_eleven11(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "26500"
    assert stored["_settle_source"] == "real"
    assert str(stored["정산예정금(배송비포함)"]) == "26500"


def test_정산일이_오면_받은_날로_저장한다(session, monkeypatch):
    """🔴 stlDy(정산일) = 정산이 끝난 날 = 「입금됐다」의 유일한 근거.

    2026-08-06 지도 정독 전엔 금액만 읽어, 11번가 520만이 계속 「입금일 지남·미확인」에
    서 있었다 — 받았는지 못 받았는지 판정할 근거가 아예 없었다.
    """
    OS.save([_row()], session=session)
    _patch(monkeypatch, {("E100", "1"): {"정산금액": 26500, "정산일": "2026-08-05",
                                          "송금예정일": "2026-08-05"}})

    stat = OI.refresh_settlement_eleven11(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["_settle_paid_date"] == "2026-08-05"


def test_이미_real_인_행에도_받은_날을_백필한다(session, monkeypatch):
    """🔴 2026-08-07 라이브 — real 행은 「날짜만 백필」 경로를 타는데 거기서 **정산예정일만**
    쓰고 있었다. 그래서 stlDy 가 실제로 오는데도 11번가 110건(2,098만)이 계속
    「입금일 지남·미확인」에 남았다(estimated 행만 보는 테스트라 못 잡았다).
    """
    OS.save([_row(_settle_source="real", 정산예정금액=26500)], session=session)
    _patch(monkeypatch, {("E100", "1"): {"정산금액": 26500, "정산일": "2026-08-05"}})

    OI.refresh_settlement_eleven11(session=session)

    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["_settle_paid_date"] == "2026-08-05"
    assert str(stored["정산예정금액"]) == "26500"      # 금액 불가침


def test_받은_날만_있고_예정일이_없으면_예정일을_지우지_않는다(session, monkeypatch):
    """없는 값으로 덮으면 있던 날짜가 사라진다."""
    OS.save([_row(_settle_source="real", 정산예정금액=26500,
                  정산예정일="2026-07-30")], session=session)
    _patch(monkeypatch, {("E100", "1"): {"정산금액": 26500, "정산일": "2026-08-05"}})

    OI.refresh_settlement_eleven11(session=session)

    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["_settle_paid_date"] == "2026-08-05"
    assert stored["정산예정일"] == "2026-07-30"        # 그대로


def test_정산일이_없으면_받았다고_하지_않는다(session, monkeypatch):
    """없는 날짜를 지어내면 「안 받은 돈」이 받은 것으로 사라진다."""
    OS.save([_row()], session=session)
    _patch(monkeypatch, {("E100", "1"): {"정산금액": 26500}})

    OI.refresh_settlement_eleven11(session=session)

    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert not stored.get("_settle_paid_date")


def test_배송비정산은_상품분에서_분리한다(session, monkeypatch):
    """정산예정금액(K) = 정산금액 − 배송비정산. 안 빼면 배송비 이중가산(인라인:2592 규약)."""
    OS.save([_row()], session=session)
    _patch(monkeypatch, {("E100", "1"): {"정산금액": 30000, "배송비정산": 3000}})

    stat = OI.refresh_settlement_eleven11(session=session)
    assert stat["updated"] == 1
    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "27000"        # 30000 − 3000


def test_라인키_ordPrdSeq까지_맞아야_갱신된다(session, monkeypatch):
    """같은 주문번호라도 주문순번이 다르면 남의 정산 — 키는 (ordNo, ordPrdSeq)."""
    OS.save([_row(seq="1")], session=session)
    _patch(monkeypatch, {("E100", "9"): {"정산금액": 26500}})   # 주문 같고 순번만 다름

    stat = OI.refresh_settlement_eleven11(session=session)
    assert stat["updated"] == 0
    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["_settle_source"] == "estimated"


def test_옵션추가금_실값이_있으면_채운다(session, monkeypatch):
    OS.save([_row()], session=session)
    _patch(monkeypatch, {("E100", "1"): {"정산금액": 26500, "옵션추가금": 2000}})

    OI.refresh_settlement_eleven11(session=session)
    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["옵션추가금"]) == "2000"


def test_다상품_주문은_각_라인이_자기_정산을_받는다_브로드캐스트금지(session, monkeypatch):
    """같은 ordNo·다른 ordPrdSeq 2줄 — 각 줄이 자기 stlAmt 만 받아야 한다(주문 합계
      브로드캐스트 = N배 계상 금지). 라인 키의 존재 이유를 직접 잠근다."""
    OS.save([_row(uid="eleven11|E100|1", ono="E100", seq="1"),
             _row(uid="eleven11|E100|2", ono="E100", seq="2")], session=session)
    _patch(monkeypatch, {("E100", "1"): {"정산금액": 10000},
                         ("E100", "2"): {"정산금액": 20000}})

    stat = OI.refresh_settlement_eleven11(session=session)
    assert stat["updated"] == 2
    rows = {r[L.FIELD]: r for r in OS.load(
        ["eleven11"], since="2000-01-01", until="2999-01-01", session=session)}
    assert str(rows["eleven11|E100|1"]["정산예정금액"]) == "10000"
    assert str(rows["eleven11|E100|2"]["정산예정금액"]) == "20000"


def test_이미_실정산인_행은_건드리지_않는다(session, monkeypatch):
    OS.save([_row(정산예정금액=26500, _settle_source="real")], session=session)
    _patch(monkeypatch, {("E100", "1"): {"정산금액": 11111}})

    stat = OI.refresh_settlement_eleven11(session=session)
    assert stat["updated"] == 0
    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "26500"


def test_정산조회에_없는_주문은_그대로_둔다(session, monkeypatch):
    OS.save([_row()], session=session)
    _patch(monkeypatch, {("OTHER", "1"): {"정산금액": 50000}})

    stat = OI.refresh_settlement_eleven11(session=session)
    assert stat["updated"] == 0
    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "27000"
    assert stored["_settle_source"] == "estimated"


def test_클레임_행은_건드리지_않는다(session, monkeypatch):
    OS.save([_row(주문상태="반품", _kind="change", _change_date="2026-07-10")],
            session=session)
    _patch(monkeypatch, {("E100", "1"): {"정산금액": 26500}})

    stat = OI.refresh_settlement_eleven11(session=session)
    assert stat["updated"] == 0


def test_계정은_순차로_돈다_병렬금지(session, monkeypatch):
    """IP 전역 rate라 계정 병렬 금지 — 순차로 각 계정을 물어 합친다."""
    OS.save([_row(uid="eleven11|E100|1", ono="E100"),
             _row(uid="eleven11|E200|1", ono="E200")], session=session)
    seen = []
    ca, cb = object(), object()
    monkeypatch.setattr(OI, "_esm_settlement_clients",
                        lambda market: [("A", ca), ("B", cb)])
    from shared.platforms.eleven11 import settlement as _el

    def _fake(since, until, *, client=None):
        seen.append(client)
        return {("E100", "1"): {"정산금액": 26500}} if client is ca \
            else {("E200", "1"): {"정산금액": 31000}}
    monkeypatch.setattr(_el, "settlement_detail_map", _fake)

    stat = OI.refresh_settlement_eleven11(session=session)
    assert stat["updated"] == 2
    assert seen == [ca, cb]           # 순서대로(순차) 호출


def test_구매확정_창은_주문일과_무관하게_최근이다(session, monkeypatch):
    OS.save([_row(days_ago=40)], session=session)
    seen = []
    _patch(monkeypatch, {("E100", "1"): {"정산금액": 26500}})
    from shared.platforms.eleven11 import settlement as _el
    calls = []
    _orig = _el.settlement_detail_map

    def _cap(since, until, *, client=None):
        calls.append((since.date(), until.date()))
        return {("E100", "1"): {"정산금액": 26500}}
    monkeypatch.setattr(_el, "settlement_detail_map", _cap)

    OI.refresh_settlement_eleven11(session=session)
    assert calls
    since, until = calls[0]
    today = _dt.datetime.now(KST).date()
    assert (today - since).days <= OI.ELEVEN11_SETTLE_SWEEP_DAYS + 1
    assert (today - until).days <= OI.ELEVEN11_SETTLE_SWEEP_SKIP_DAYS + 1


def test_이미real_배송비_이중가산은_교정한다(session, monkeypatch):
    """🔴 _stl_net(정산금액−배송비) 규약 이전에 저장된 real 행 — K 가 GROSS(배송비 포함)라
      _finalize 가 배송비를 이중 가산했다(2026-07-25 샵마인 실측 9건, 롯데온 #484 동일 클래스).

    라이브 실측 20260625079413235: K=25,061(=샵마인 N), 저장 N=28,061=+3,000.
    """
    OS.save([_row(정산예정금액=25061, 배송비=3000, _settle_source="real", ono="E477")],
            session=session)
    # 저장된 배송비포함을 옛 GROSS 이중 상태(K25061 + 배송비3000 = 28061)로 만든다.
    from lemouton.markets.models_orders import MarketOrderLine
    o = session.query(MarketOrderLine).filter_by(market="eleven11").first()
    r = dict(o.row); r["정산예정금(배송비포함)"] = 28061; o.row = r
    session.commit()

    # 정산조회 실값: 정산금액 25,061(배송비 포함) · 배송비정산 3,000 → 재도출 N=25,061.
    _patch(monkeypatch, {("E477", "1"): {"정산금액": 25061, "배송비정산": 3000}})
    stat = OI.refresh_settlement_eleven11(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금(배송비포함)"]) == "25061"    # 이중가산 제거
    assert str(stored["정산예정금액"]) == "22061"             # 상품분(−배송비)


def test_이미real_배송비교정은_멱등(session, monkeypatch):
    OS.save([_row(정산예정금액=25061, 배송비=3000, _settle_source="real", ono="E477")],
            session=session)
    from lemouton.markets.models_orders import MarketOrderLine
    o = session.query(MarketOrderLine).filter_by(market="eleven11").first()
    r = dict(o.row); r["정산예정금(배송비포함)"] = 28061; o.row = r
    session.commit()
    _patch(monkeypatch, {("E477", "1"): {"정산금액": 25061, "배송비정산": 3000}})
    OI.refresh_settlement_eleven11(session=session)
    stat2 = OI.refresh_settlement_eleven11(session=session)
    assert stat2["updated"] == 0                              # 두 번째는 서명 불일치 → 안 건드림
    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금(배송비포함)"]) == "25061"    # 22,061 로 안 떨어짐
