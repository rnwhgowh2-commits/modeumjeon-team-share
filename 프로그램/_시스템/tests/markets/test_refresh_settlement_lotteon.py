# -*- coding: utf-8 -*-
"""롯데온 정산 스윕 — 구매확정 뒤에 인식되는 실정산을 옛 주문까지 되짚는다.

🔴 왜 롯데온도 따로인가 — 정산 스윕이 없어 적재틱(7~21일)이 닫힌 뒤 구매확정된
  주문의 실정산(SettleItmdSales.pymtAmt)이 영영 안 들어와 추정치로 고착됐다
  (옥션·G마켓·쿠팡이 이미 닫은 그 갭).

★ 조인 키 = odNo 단일(쿠팡의 (주문번호,옵션ID) 복합키와 다름 — 인라인 조인과 동형).
★ 창은 구매확정일(정산기준일) 기준이라 '지금'에서 뒤로 잡는다(주문일 창 아님).
★ rate 버킷이 계정별이라 계정 병렬이 안전(11번가·스스의 IP전역과 다름).
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


def _row(uid="lotteon|LO500|1", ono="LO500", days_ago=40, **kw):
    """days_ago 기본 40 — 스윕이 '주문일 창'으로 좁히지 않음을 보이려 일부러 오래된 주문."""
    row = {L.FIELD: uid, "판매처": "롯데온", "쇼핑몰": "롯데온",
           "오픈마켓주문번호": ono,
           "주문일": _order_date(days_ago), "주문상태": "구매확정",
           "상품명": "테스트 상품", "단가": 30000, "수량": 1,
           "실결제금액": 30000, "배송비": 0,
           "정산예정금액": 27000, "_settle_source": "estimated"}
    row.update(kw)
    return row


def _patch(monkeypatch, order_map, clients=(("메인", object()),), calls=None):
    """order_map = {odNo: pymtAmt}. itmd_map 반환 형태로 감싼다."""
    monkeypatch.setattr(OI, "_esm_settlement_clients", lambda market: list(clients))
    from shared.platforms.lotteon import settlement as _lo

    def _fake_itmd(since, until, *, client=None):
        if calls is not None:
            calls.append((since.date(), until.date(), client))
        return {k: {"pymtAmt": v, "pcs_cmsn": 0, "is_affiliate": False}
                for k, v in order_map.items()}
    monkeypatch.setattr(_lo, "itmd_map", _fake_itmd)


def test_옛_주문도_구매확정창이_덮으면_실정산으로_갱신(session, monkeypatch):
    OS.save([_row()], session=session)
    _patch(monkeypatch, {"LO500": 26500})

    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "26500"
    assert stored["_settle_source"] == "real"
    # 파생열(배송비포함)도 함께 갱신 — 마진계산기가 읽는 칸이 옛값으로 남지 않게.
    assert str(stored["정산예정금(배송비포함)"]) == "26500"


def test_이미_실정산인_행은_건드리지_않는다(session, monkeypatch):
    OS.save([_row(정산예정금액=26500, _settle_source="real")], session=session)
    _patch(monkeypatch, {"LO500": 11111})

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 0
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "26500"


def test_정산조회에_없는_주문은_그대로_둔다(session, monkeypatch):
    OS.save([_row()], session=session)
    _patch(monkeypatch, {"OTHER": 50000})

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 0
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "27000"
    assert stored["_settle_source"] == "estimated"


def test_클레임_행은_건드리지_않는다(session, monkeypatch):
    OS.save([_row(주문상태="반품완료", _kind="change", _change_date="2026-07-10")],
            session=session)
    _patch(monkeypatch, {"LO500": 26500})

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 0


def test_구매확정_창은_주문일과_무관하게_최근이다(session, monkeypatch):
    """조회 창은 정산기준일(구매확정일) 기준이라 '지금'에서 뒤로 잡힌다(주문일 40일 전과 무관)."""
    OS.save([_row(days_ago=40)], session=session)
    calls = []
    _patch(monkeypatch, {"LO500": 26500}, calls=calls)

    OI.refresh_settlement_lotteon(session=session)

    assert calls, "정산조회가 호출돼야 한다"
    since, until, _ = calls[0]
    today = _dt.datetime.now(KST).date()
    assert (today - since).days <= OI.LOTTEON_SETTLE_SWEEP_DAYS + 1
    assert (today - until).days <= OI.LOTTEON_SETTLE_SWEEP_SKIP_DAYS + 1


def test_다계정_정산이_합쳐진다(session, monkeypatch):
    """서로 다른 계정의 정산맵이 합쳐져 각자 주문을 갱신한다(대표계정만 물으면 누락)."""
    OS.save([_row(uid="lotteon|LO500|1", ono="LO500"),
             _row(uid="lotteon|LO900|1", ono="LO900")], session=session)

    monkeypatch.setattr(OI, "_esm_settlement_clients",
                        lambda market: [("A", object()), ("B", object())])
    from shared.platforms.lotteon import settlement as _lo
    by_client = {}

    def _fake_itmd(since, until, *, client=None):
        # 계정 A 는 LO500 만, 계정 B 는 LO900 만 안다.
        idx = len(by_client)
        by_client[id(client)] = idx
        m = {"LO500": 26500} if idx == 0 else {"LO900": 31000}
        return {k: {"pymtAmt": v, "pcs_cmsn": 0, "is_affiliate": False}
                for k, v in m.items()}
    monkeypatch.setattr(_lo, "itmd_map", _fake_itmd)

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 2
