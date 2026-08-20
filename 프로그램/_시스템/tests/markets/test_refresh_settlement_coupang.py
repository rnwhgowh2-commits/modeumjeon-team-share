# -*- coding: utf-8 -*-
"""쿠팡 정산 스윕 — 5일 넘게 안 본 옛 주문의 실정산을 인식일 창으로 되짚는다.

🔴 왜 쿠팡만 따로인가 — ESM 과 정산 인식 시점·조인 키가 다르다.
  · **인식일 기준**: 정산은 구매확정 뒤에 인식된다. 두 달 전 주문이 최근에 인식되므로
    옛 주문을 갱신하려면 최근 인식일 창을 훑어 orderId 로 되짚어야 한다. 주문일 창으로
    물으면 옛 주문의 새 정산을 영영 못 본다.
  · **(주문번호, 옵션ID) 복합키**: 한 주문에 여러 옵션이 있어 orderId 만으론 못 가른다.

★ 화면 조회는 창을 열 때만 실값을 붙여, 5일 넘게 안 본 쿠팡 주문이 추정으로 고착됐다.
  이 스윕이 스케줄러에서 그 고착을 푼다(옥션·G마켓 스윕과 같은 이유·별도 함수).
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


def _row(uid="coupang|70001|1001", ono="70001", vid="1001", days_ago=40, **kw):
    """days_ago 기본 40 — 스윕이 '주문일 창'으로 좁히지 않음을 보이려 일부러 오래된 주문."""
    row = {L.FIELD: uid, "판매처": "쿠팡", "쇼핑몰": "쿠팡", "오픈마켓주문번호": ono,
           "_pd_market_option_id": vid,
           "주문일": _order_date(days_ago), "주문상태": "구매확정",
           "상품명": "테스트 상품", "단가": 30000, "수량": 1,
           "실결제금액": 30000, "배송비": 0,
           "정산예정금액": 27000, "_settle_source": "estimated"}
    row.update(kw)
    return row


def _patch(monkeypatch, item_map, clients=(("메인", object()),), calls=None):
    monkeypatch.setattr(OI, "_esm_settlement_clients", lambda market: list(clients))
    import lemouton.markets.order_export as _oe

    def _fake(since, until, client):
        if calls is not None:
            calls.append((since.date(), until.date(), client))
        return dict(item_map), {}, {}
    monkeypatch.setattr(_oe, "_coupang_settle_map", _fake)


def test_옛_주문도_인식창이_덮으면_실정산으로_갱신(session, monkeypatch):
    OS.save([_row()], session=session)
    _patch(monkeypatch, {("70001", "1001"): 26500})

    stat = OI.refresh_settlement_coupang(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "26500"
    assert stored["_settle_source"] == "real"
    # 파생열(배송비포함)도 함께 갱신 — 마진계산기가 읽는 칸이 옛값으로 남지 않게.
    assert str(stored["정산예정금(배송비포함)"]) == "26500"


def test_옵션ID까지_맞아야_갱신된다(session, monkeypatch):
    """같은 주문번호라도 옵션ID가 다르면 남의 정산 — 조인 키는 (주문번호,옵션ID)."""
    OS.save([_row(vid="1001")], session=session)
    _patch(monkeypatch, {("70001", "9999"): 26500})   # 주문은 같고 옵션만 다름

    stat = OI.refresh_settlement_coupang(session=session)

    assert stat["updated"] == 0
    stored = OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["_settle_source"] == "estimated"


def test_조인키_없는_행은_건드리지_않는다(session, monkeypatch):
    OS.save([_row(**{"_pd_market_option_id": ""})], session=session)
    _patch(monkeypatch, {("70001", ""): 26500})

    stat = OI.refresh_settlement_coupang(session=session)
    assert stat["updated"] == 0


def test_이미_실정산인_행은_건드리지_않는다(session, monkeypatch):
    OS.save([_row(정산예정금액=26500, _settle_source="real")], session=session)
    _patch(monkeypatch, {("70001", "1001"): 11111})

    stat = OI.refresh_settlement_coupang(session=session)
    assert stat["updated"] == 0
    stored = OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "26500"


def test_정산조회에_없는_주문은_그대로_둔다(session, monkeypatch):
    OS.save([_row()], session=session)
    _patch(monkeypatch, {("88888", "1001"): 50000})

    stat = OI.refresh_settlement_coupang(session=session)
    assert stat["updated"] == 0
    stored = OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "27000"
    assert stored["_settle_source"] == "estimated"


def test_클레임_행은_건드리지_않는다(session, monkeypatch):
    OS.save([_row(주문상태="반품완료", _kind="change", _change_date="2026-07-10")],
            session=session)
    _patch(monkeypatch, {("70001", "1001"): 26500})

    stat = OI.refresh_settlement_coupang(session=session)
    assert stat["updated"] == 0


def test_인식일_창은_주문일과_무관하게_최근이다(session, monkeypatch):
    """조회 창은 recognitionDate 기준이라 '지금'에서 뒤로 잡힌다(주문일 40일 전과 무관)."""
    OS.save([_row(days_ago=40)], session=session)
    calls = []
    _patch(monkeypatch, {("70001", "1001"): 26500}, calls=calls)

    OI.refresh_settlement_coupang(session=session)

    assert calls, "정산조회가 호출돼야 한다"
    since, until, _ = calls[0]
    today = _dt.datetime.now(KST).date()
    assert (today - since).days <= OI.COUPANG_SETTLE_SWEEP_DAYS + 1
    assert (today - until).days <= OI.COUPANG_SETTLE_SWEEP_SKIP_DAYS + 1
