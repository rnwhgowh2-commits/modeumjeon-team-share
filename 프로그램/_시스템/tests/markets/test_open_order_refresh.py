# -*- coding: utf-8 -*-
"""최근 3주 상태·송장 최신화 — 미확정 날짜만 골라 재확인.

사장님 기준(2026-07-24): 보통 3주 안에 구매확정·클레임으로 바뀌므로 최근 21일의
주문상태·송장번호가 늘 최신이어야 한다. 스스·롯데온은 하루씩만 조회되므로
'아직 안 끝난 건이 남은 날짜'만 다시 본다.
"""
import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.markets import order_store as _store
from lemouton.markets.models_orders import Base, MarketOrderLine


@pytest.fixture()
def session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _line(s, uid, market, date, status, seen_days_ago=0):
    s.add(MarketOrderLine(
        line_uid=uid, market=market, order_no=uid, order_date=date + " 10:00:00",
        status=status, account="계정", row={"주문상태": status},
        first_seen_at=_dt.datetime(2026, 7, 1),
        last_seen_at=_dt.datetime(2026, 7, 24) - _dt.timedelta(days=seen_days_ago)))
    s.commit()


def test_끝난_주문만_있는_날짜는_안_고른다(session):
    """구매확정·취소완료만 남은 날은 값이 더 안 바뀐다 — 다시 부를 이유가 없다."""
    _line(session, "a1", "smartstore", "2026-07-10", "구매확정")
    _line(session, "a2", "smartstore", "2026-07-10", "취소완료")
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", session=session)
    assert got == []


def test_안_끝난_건이_하나라도_있으면_그_날짜를_고른다(session):
    _line(session, "b1", "smartstore", "2026-07-11", "구매확정")
    _line(session, "b2", "smartstore", "2026-07-11", "배송중")
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", session=session)
    assert got == ["2026-07-11"]


def test_배송완료는_아직_안_끝난_것으로_본다(session):
    """배송완료 다음에 구매확정으로 한 번 더 바뀐다 — 여기서 끊으면 그 변화를 놓친다."""
    _line(session, "c1", "smartstore", "2026-07-12", "배송완료")
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", session=session)
    assert got == ["2026-07-12"]


def test_오래_안_본_날짜부터_준다(session):
    """한 틱에 몇 개만 처리해도 다음 틱이 나머지를 이어받아야 굶는 날짜가 없다."""
    _line(session, "d1", "smartstore", "2026-07-13", "배송중", seen_days_ago=1)
    _line(session, "d2", "smartstore", "2026-07-14", "배송중", seen_days_ago=5)
    _line(session, "d3", "smartstore", "2026-07-15", "배송중", seen_days_ago=3)
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", session=session)
    assert got == ["2026-07-14", "2026-07-15", "2026-07-13"]


def test_한_틱_처리량을_제한한다(session):
    _line(session, "e1", "smartstore", "2026-07-13", "배송중", seen_days_ago=1)
    _line(session, "e2", "smartstore", "2026-07-14", "배송중", seen_days_ago=5)
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", limit=1, session=session)
    assert got == ["2026-07-14"]


def test_3주_밖은_안_고른다(session):
    """3주가 지나면 거의 확정된다 — 무한정 되돌아보지 않는다."""
    _line(session, "f1", "smartstore", "2026-06-01", "배송중")
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", session=session)
    assert got == []


def test_다른_마켓_날짜는_안_섞인다(session):
    _line(session, "g1", "lotteon", "2026-07-16", "배송중")
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", session=session)
    assert got == []


# ══════════════════════════════════════════════════════════════════════════
# [2026-08-02] 창 밖에서 굳은 미확정 주문 — 옛 차선(stale lane)
#   라이브 실측: 롯데온 저장분에 '주문'(결제 직후) 상태로 굳은 554건이 있었고
#   주문일이 전부 2026-03(483)·04(71)월. 5~7월은 0건 — 최근은 잘 따라잡는데
#   21일 창 밖은 다시 볼 기회가 없어 영영 멈춰 있었다. 에러도 로그도 없다
#   (실패가 아니라 '안 본 것').
# ══════════════════════════════════════════════════════════════════════════

def _patch_now(monkeypatch, oi, when):
    """refresh_open_orders 안의 '지금'을 고정한다(창 계산이 시간에 걸리므로)."""
    real = oi._dt.datetime

    class _FixedDT(real):
        @classmethod
        def now(cls, tz=None):
            return when if tz is None else when.replace(tzinfo=tz)

    monkeypatch.setattr(oi._dt, "datetime", _FixedDT)


def _no_fetch(monkeypatch, oi):
    """마켓 조회는 하지 않는다 — 어떤 날짜를 고르는지만 본다."""
    seen = []

    def _fake(market, since, until, session=None):
        seen.append(since.strftime("%Y-%m-%d"))
        return {"orders_new": 0, "orders_updated": 0, "claims_new": 0,
                "claims_updated": 0, "skipped_no_uid": 0}

    monkeypatch.setattr(oi, "ingest_window", _fake)
    return seen


def test_창밖_미확정도_틱당_조금씩_되찾는다(session, monkeypatch):
    from lemouton.markets import order_ingest as oi
    _line(session, "s1", "lotteon", "2026-07-20", "배송중", seen_days_ago=1)   # 최근 차선
    _line(session, "s2", "lotteon", "2026-03-05", "주문", seen_days_ago=90)    # 옛 차선
    _line(session, "s3", "lotteon", "2026-04-02", "주문", seen_days_ago=80)    # 옛 차선
    _patch_now(monkeypatch, oi, _dt.datetime(2026, 8, 2, 12, 0))
    _no_fetch(monkeypatch, oi)

    r = oi.refresh_open_orders("lotteon", days=21, limit=6, session=session)
    assert r["stale_dates"] == ["2026-03-05", "2026-04-02"]   # 오래 안 본 순
    assert "2026-07-20" in r["dates"]                          # 최근 차선은 그대로


def test_180일_넘은_주문도_결국_되찾는다(session, monkeypatch):
    """🔴🔴 2026-09-06 재발 — STALE_OPEN_DAYS=180 은 고정 절벽이었다. 08-02 수정
    직후엔 3~4월분이 이 차선(21~180일)에 걸려 해소됐지만, 시간이 지나 그 주문들이
    180일을 넘기면 21일 차선에도 180일 차선에도 안 걸리는 '차선 밖'으로 다시
    떨어진다 — 마진계산기 기타 카드에서 2월 주문 116건(215일째)으로 실측됐다.
    상한을 치운 뒤에는(STALE_OPEN_DAYS 기본값) 이 정도로 오래된 주문도 옛 차선이
    여전히 찾아내야 한다."""
    from lemouton.markets import order_ingest as oi
    _line(session, "w1", "lotteon", "2026-02-03", "주문", seen_days_ago=200)  # 215일째
    _patch_now(monkeypatch, oi, _dt.datetime(2026, 9, 6, 12, 0))
    _no_fetch(monkeypatch, oi)

    r = oi.refresh_open_orders("lotteon", days=21, session=session)  # stale_days·limit 기본값
    assert "2026-02-03" in r["stale_dates"], r


def test_옛_차선은_틱당_상한을_지킨다(session, monkeypatch):
    """상한이 없으면 밀린 옛 날짜가 매 틱을 차지해 최근 21일이 굶는다."""
    from lemouton.markets import order_ingest as oi
    for i, d in enumerate(["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04"]):
        _line(session, f"t{i}", "lotteon", d, "주문", seen_days_ago=90 - i)
    _patch_now(monkeypatch, oi, _dt.datetime(2026, 8, 2, 12, 0))
    _no_fetch(monkeypatch, oi)

    r = oi.refresh_open_orders("lotteon", days=21, limit=6, stale_limit=2,
                               session=session)
    assert len(r["stale_dates"]) == 2


def test_두_차선이_같은_날짜를_두_번_조회하지_않는다(session, monkeypatch):
    """옛 구간의 끝은 최근 구간 시작 하루 전 — 경계에서 겹치면 헛호출이다."""
    from lemouton.markets import order_ingest as oi
    _line(session, "u1", "lotteon", "2026-07-20", "배송중", seen_days_ago=90)
    _patch_now(monkeypatch, oi, _dt.datetime(2026, 8, 2, 12, 0))
    called = _no_fetch(monkeypatch, oi)

    r = oi.refresh_open_orders("lotteon", days=21, limit=6, session=session)
    assert r["dates"].count("2026-07-20") == 1
    assert called.count("2026-07-20") == 1


def test_stale_limit_0_이면_옛_차선을_끈다(session, monkeypatch):
    """수동 호출·테스트에서 최근만 보고 싶을 때."""
    from lemouton.markets import order_ingest as oi
    _line(session, "v1", "lotteon", "2026-03-05", "주문", seen_days_ago=90)
    _patch_now(monkeypatch, oi, _dt.datetime(2026, 8, 2, 12, 0))
    _no_fetch(monkeypatch, oi)

    r = oi.refresh_open_orders("lotteon", days=21, limit=6, stale_limit=0,
                               session=session)
    assert r["stale_dates"] == [] and r["dates"] == []
