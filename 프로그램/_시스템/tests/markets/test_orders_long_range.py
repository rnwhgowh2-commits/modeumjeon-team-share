"""90일 초과 조회 — 클램프 해제와 적재분 경로.

「샵마인은 1년치도 나오는데 우리는 안 된다」의 원인은 마켓 API 가 아니라
webapp/routes/orders.py 의 전 마켓 90일 클램프였다(2026-07-20 실측).
여기서 그 해제와, 적재분이 비었을 때 조용히 빈 화면을 주지 않는 것을 못 박는다.
"""
from __future__ import annotations

import datetime as _dt

import webapp.routes.orders as R


def _args(fr, to):
    return {"from": fr, "to": to}


# ── 클램프 ─────────────────────────────────────────────────────
def test_1년치_구간이_잘리지_않는다():
    since, until = R._parse_range(_args("2025-07-20", "2026-07-20"))
    assert (until - since).days >= 364, "1년을 요청했는데 잘렸다"


def test_365일을_넘으면_365일로_자른다():
    since, until = R._parse_range(_args("2023-01-01", "2026-07-20"))
    assert (until - since).days <= R.MAX_RANGE_DAYS


def test_예전_90일_클램프는_사라졌다():
    """이 값이 90 으로 돌아가면 1년치가 다시 막힌다."""
    assert R.MAX_RANGE_DAYS == 365


def test_짧은_구간은_그대로():
    since, until = R._parse_range(_args("2026-07-01", "2026-07-10"))
    assert (until - since).days == 9


# ── 실시간 vs 적재분 분기 ───────────────────────────────────────
def test_90일_이내는_실시간_경로():
    since = _dt.datetime(2026, 5, 1)
    assert R._is_long_range(since, since + _dt.timedelta(days=90)) is False


def test_90일_초과는_적재분_경로():
    since = _dt.datetime(2026, 1, 1)
    assert R._is_long_range(since, since + _dt.timedelta(days=91)) is True


def test_기간이_없으면_실시간():
    assert R._is_long_range(None, None) is False


# ── 적재 현황을 숨기지 않는다 ───────────────────────────────────
def test_적재가_비었으면_빈화면이_아니라_이유를_알린다(monkeypatch):
    """말없이 0건을 주면 「주문이 없다」로 오해한다."""
    monkeypatch.setattr("lemouton.markets.order_store.load", lambda *a, **k: [])
    monkeypatch.setattr("lemouton.markets.order_store.coverage", lambda: [])
    rows, note = R._rows_from_store(["coupang"], _dt.datetime(2025, 7, 1),
                                    _dt.datetime(2026, 7, 1))
    assert rows == []
    assert "저장된 게 없는 마켓" in note and "coupang" in note


def test_저장된_범위를_알려준다(monkeypatch):
    monkeypatch.setattr("lemouton.markets.order_store.load", lambda *a, **k: [{"a": 1}])
    monkeypatch.setattr("lemouton.markets.order_store.coverage",
                        lambda: [{"market": "coupang", "rows": 12,
                                  "oldest": "2026-01-02 10:00:00",
                                  "newest": "2026-07-01 10:00:00"}])
    rows, note = R._rows_from_store(["coupang"], _dt.datetime(2025, 7, 1),
                                    _dt.datetime(2026, 7, 1))
    assert len(rows) == 1
    assert "2026-01-02~2026-07-01" in note and "12건" in note


def test_적재분_읽기가_실패하면_사실대로_말한다(monkeypatch):
    """빈 결과로 위장하면 데이터가 없는 건지 고장난 건지 구분이 안 된다."""
    monkeypatch.setattr("lemouton.markets.order_store.load",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    rows, note = R._rows_from_store(["coupang"], _dt.datetime(2025, 7, 1),
                                    _dt.datetime(2026, 7, 1))
    assert rows == [] and "읽지 못했어요" in note
