# -*- coding: utf-8 -*-
"""「배송완료」에 굳은 주문 되살리기 (2026-08-08 라이브 실측 기반).

🔴 롯데온 3,941만원의 정체 = 3~6월 결제인데 아직 배송완료인 622건.
   「입금 확인 창구가 없다」가 아니라 **주문 상태가 낡은 것**이었다.
   우리 주문 갱신이 최근 21일 창만 보고, 그 창을 지나 바뀐 상태는 영영 안 따라간다.
   아무도 에러를 안 내므로 **조용히** 틀린다 — 그래서 테스트로 못 박는다.
"""
from __future__ import annotations

import datetime as _dt

from lemouton.markets import order_ingest as OI

KST = _dt.timezone(_dt.timedelta(hours=9))


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import lemouton.markets.models_orders  # noqa: F401
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        eng, tables=[Base.metadata.tables["market_order_lines"]])
    return sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()


def _ago(days):
    return (_dt.datetime.now(KST) - _dt.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _line(s, uid, ono, *, status, days, row=None):
    from lemouton.markets.models_orders import MarketOrderLine as L
    s.add(L(line_uid=uid, market="lotteon", order_no=ono, status=status,
            order_date=_ago(days), row=row if row is not None else {"주문상태": status}))
    s.commit()


def test_오래_굳은_배송완료만_고른다(monkeypatch):
    """★ 최근 건·다른 상태는 건드리지 않는다(멀쩡한 주문을 헛되이 재조회하지 않게)."""
    s = _sess()
    _line(s, "lotteon|A|1", "A", status="배송완료", days=60)    # 대상
    _line(s, "lotteon|B|1", "B", status="배송중", days=45)      # 대상
    _line(s, "lotteon|C|1", "C", status="배송완료", days=5)     # 너무 최근 — 제외
    _line(s, "lotteon|D|1", "D", status="구매확정", days=60)    # 이미 확정 — 제외
    _line(s, "lotteon|E|1", "E", status="배송완료", days=400)   # 상한 밖 — 제외

    seen = {}
    monkeypatch.setitem(OI.__dict__, "ingest_lotteon_orders_by_no",
                        lambda onos, session=None: seen.update(o=sorted(onos)) or {})
    rep = OI.refresh_stale_delivered("lotteon", session=s)
    assert seen["o"] == ["A", "B"]
    assert rep["targets"] == 2


def test_바뀐_것만_센다(monkeypatch):
    """🔴 「조회했다」와 「바뀌었다」는 다르다 — 재조회만 하고 성공이라 하면 안 된다."""
    s = _sess()
    _line(s, "lotteon|A|1", "A", status="배송완료", days=60)
    _line(s, "lotteon|B|1", "B", status="배송완료", days=60)

    from lemouton.markets.models_orders import MarketOrderLine as L

    def fake(onos, session=None):
        o = session.query(L).filter(L.line_uid == "lotteon|A|1").one()
        o.status = "구매확정"                       # A 만 실제로 바뀜
        session.commit()
        return {}
    monkeypatch.setitem(OI.__dict__, "ingest_lotteon_orders_by_no", fake)
    rep = OI.refresh_stale_delivered("lotteon", session=s)
    assert rep["targets"] == 2
    assert rep["changed"] == 1
    assert rep["moves"] == {"배송완료→구매확정": 1}


def test_재시도_간격이_굶김을_막는다(monkeypatch):
    """되조회해도 안 바뀌는 주문이 앞자리를 계속 차지하면 뒤가 영영 안 본다."""
    s = _sess()
    _line(s, "lotteon|A|1", "A", status="배송완료", days=60)
    _line(s, "lotteon|B|1", "B", status="배송완료", days=59)

    calls = []
    monkeypatch.setitem(OI.__dict__, "ingest_lotteon_orders_by_no",
                        lambda onos, session=None: calls.append(sorted(onos)) or {})
    OI.refresh_stale_delivered("lotteon", limit=1, session=s)
    OI.refresh_stale_delivered("lotteon", limit=1, session=s)   # 곧바로 또 돌려도
    assert calls == [["A"], ["B"]]                              # A 를 또 잡지 않는다


def test_지원안하는_마켓은_정직하게_거절():
    try:
        OI.refresh_stale_delivered("coupang")
    except ValueError as e:
        assert "coupang" in str(e)
    else:
        raise AssertionError("조용히 0건을 돌려주면 안 된다")
