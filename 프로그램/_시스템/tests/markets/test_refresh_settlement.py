# -*- coding: utf-8 -*-
"""정산만 다시 훑기 — 구매확정 뒤에 들어오는 실정산을 받아온다.

🔴 왜 필요한가(2026-07-25 G마켓 라이브 실측) — 정산은 **구매확정 뒤에** 확정되는데
ESM 증분 수집은 최근 21일만 훑는다. 주문 2026-07-01 은 07-21 이 마지막 관측이었고
그때는 아직 미정산이었다. 21일 창이 닫힌 뒤 마켓에 실정산 69,530 이 들어왔지만
우리 저장분은 추정치로 고착됐다(같은 지문 43건 · 2026-04~07).

★ 계정별로 물어야 한다 — 대표 계정으로 07-01~07-05 를 물으면 2건뿐이고 찾는 주문이
  없다. 같은 창을 「브랜드위시」로 물으면 4건 전부 나온다(69,530 · 68,469 · 63,510 ·
  37,323 — 샵마인 정산금과 원 단위까지 일치). 계정을 안 나누면 「마켓에 정산이 없다」는
  잘못된 결론에 도달한다.
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


def _row(uid="gmarket|4463818179", ono="4463818179", days_ago=24, **kw):
    row = {L.FIELD: uid, "판매처": "G마켓", "쇼핑몰": "G마켓", "오픈마켓주문번호": ono,
           "주문일": _order_date(days_ago), "주문상태": "구매결정",
           "상품명": "나이키 리엑스 8", "단가": 81800, "수량": 1,
           "실결제금액": 81800, "배송비": 0,
           "정산예정금액": 69000, "_settle_source": "estimated"}
    row.update(kw)
    return row


def _patch_settlement(monkeypatch, smap, clients=(("브랜드위시", object()),), calls=None):
    monkeypatch.setattr(OI, "_esm_settlement_clients", lambda market: list(clients))
    import shared.platforms.esm.settlements as _s

    def _fake(market, since, until, *, client, srch_type="D1", page_rows=None):
        if calls is not None:
            calls.append((market, srch_type, since.date(), until.date(), client))
        return smap
    monkeypatch.setattr(_s, "settle_detail_map", _fake)


def test_구매확정_뒤_들어온_실정산을_받아온다(session, monkeypatch):
    OS.save([_row()], session=session)
    _patch_settlement(monkeypatch, {"4463818179": {"정산예정금액": 69530}})

    stat = OI.refresh_settlement("gmarket", session=session)

    assert stat["updated"] == 1
    stored = OS.load(["gmarket"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "69530"
    assert stored["_settle_source"] == "real"
    # 파생열도 함께 갱신돼야 마진계산기가 읽는 칸이 옛값으로 남지 않는다.
    assert str(stored["정산예정금(배송비포함)"]) == "69530"


def test_이미_실정산인_행은_건드리지_않는다(session, monkeypatch):
    OS.save([_row(정산예정금액=69530, _settle_source="real")], session=session)
    _patch_settlement(monkeypatch, {"4463818179": {"정산예정금액": 11111}})

    stat = OI.refresh_settlement("gmarket", session=session)

    assert stat["updated"] == 0
    stored = OS.load(["gmarket"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "69530"


def test_정산조회에_없는_주문은_그대로_둔다(session, monkeypatch):
    """없는 값을 0 으로 채우지 않는다 — 미정산은 미정산이다."""
    OS.save([_row()], session=session)
    _patch_settlement(monkeypatch, {"9999999999": {"정산예정금액": 50000}})

    stat = OI.refresh_settlement("gmarket", session=session)

    assert stat["updated"] == 0
    stored = OS.load(["gmarket"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "69000"
    assert stored["_settle_source"] == "estimated"


def test_클레임_행은_건드리지_않는다(session, monkeypatch):
    """취소·반품 정산은 취소 확정(zero_cancel)·실정산 조인이 담당한다.
    여기서 활성 시절 정산액을 얹으면 취소된 돈을 되살리는 날조가 된다."""
    OS.save([_row(주문상태="반품완료", _kind="change", _change_date="2026-07-10")],
            session=session)
    _patch_settlement(monkeypatch, {"4463818179": {"정산예정금액": 69530}})

    stat = OI.refresh_settlement("gmarket", session=session)
    assert stat["updated"] == 0


def test_계정별로_물어본다(session, monkeypatch):
    """★ 대표 계정만 물으면 다른 계정 주문의 정산을 통째로 못 본다(라이브 실측)."""
    calls = []
    c1, c2 = object(), object()
    OS.save([_row()], session=session)
    _patch_settlement(monkeypatch, {"4463818179": {"정산예정금액": 69530}},
                      clients=(("브랜드위시", c1), ("브랜드웍스", c2)), calls=calls)

    OI.refresh_settlement("gmarket", session=session)

    assert [c[4] for c in calls] == [c1, c2]


def test_옥션_G마켓_전용(session):
    with pytest.raises(ValueError):
        OI.refresh_settlement("coupang", session=session)


# ── 재발 방지: 안 들어온 정산을 숫자로 드러낸다 ────────────────────────────────

def test_실정산이_오래_안_들어오면_화면에_알린다(monkeypatch):
    """🔴 사장님 지시(2026-07-25): "이런 일 없도록 하고 싶어".
    이번 사고의 두 원인은 **둘 다 에러를 안 남겼다** — 실패가 아니라 「안 본 것」이라
    로그도 경보도 없이 43건이 3개월간 추정치로 남았다. 고치는 것만으로는 같은 종류를
    또 놓친다 → 안 들어온 것이 숫자로 보이게 한다."""
    from lemouton.margin import sell_source as SS

    old = (_dt.datetime.now(KST) - _dt.timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
    rows = [{"판매처": "G마켓", "주문일": old, "_settle_source": "estimated",
             "오픈마켓주문번호": "1", "단가": 1000, "수량": 1},
            {"판매처": "G마켓", "주문일": old, "_settle_source": "real",
             "오픈마켓주문번호": "2", "단가": 1000, "수량": 1}]
    monkeypatch.setattr(SS, "_fetch_rows", lambda *a, **k: (rows, []))

    df = SS.from_api(_dt.datetime.now(KST) - _dt.timedelta(days=90),
                     _dt.datetime.now(KST), markets=["gmarket"])
    notices = " ".join(df.attrs.get("notices") or [])
    assert "1건" in notices and "추정치" in notices


def test_실정산이_다_들어왔으면_조용하다(monkeypatch):
    """거짓 경보 금지 — 멀쩡할 땐 아무 말도 안 한다."""
    from lemouton.margin import sell_source as SS

    old = (_dt.datetime.now(KST) - _dt.timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
    rows = [{"판매처": "G마켓", "주문일": old, "_settle_source": "real",
             "오픈마켓주문번호": "2", "단가": 1000, "수량": 1},
            {"판매처": "G마켓", "주문일": old, "_settle_source": "zero_cancel",
             "주문상태": "취소완료", "오픈마켓주문번호": "3", "단가": 1000, "수량": 1}]
    monkeypatch.setattr(SS, "_fetch_rows", lambda *a, **k: (rows, []))

    df = SS.from_api(_dt.datetime.now(KST) - _dt.timedelta(days=90),
                     _dt.datetime.now(KST), markets=["gmarket"])
    assert not [n for n in (df.attrs.get("notices") or []) if "추정치" in n]
