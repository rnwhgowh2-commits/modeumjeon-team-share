"""주문 조회 = 적재분 + 최근 라이브 보충 — 돈에 직결되니 계약을 못 박는다.

지킬 것:
  ① 과거는 적재분에서 온다(라이브 폭주 없음).
  ② 최근 며칠은 라이브로 보충(오늘 주문 누락 금지).
  ③ 겹치는 구간은 line_uid 로 중복 제거(금액 2배 방지), 라이브가 최신.
  ④ 적재 범위가 요청보다 짧으면 경고(빈 구간을 완전한 것처럼 보이지 않게).
  ⑤ 라이브 보충 실패해도 적재분은 돌려주되 사유를 남김(조용한 실패 금지).
"""
from __future__ import annotations

import datetime as _dt

import pytest

from lemouton.markets import line_uid as L
from lemouton.markets import order_source as SRC

KST = SRC.KST
NOW = _dt.datetime(2026, 7, 21, 12, 0, tzinfo=KST)


@pytest.fixture(autouse=True)
def _freeze(monkeypatch):
    class _DT(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(SRC._dt, "datetime", _DT)


def _stub(monkeypatch, *, stored=None, live=None, coverage=None, live_exc=None,
          store_exc=None):
    import lemouton.markets.order_store as OS
    import lemouton.markets.order_export as OE
    monkeypatch.setattr(OS, "load",
                        (lambda *a, **k: (_ for _ in ()).throw(store_exc)) if store_exc
                        else lambda *a, **k: list(stored or []))
    monkeypatch.setattr(OS, "coverage", lambda **k: list(coverage or []))

    def _live(markets, since=None, until=None, warnings=None):
        if live_exc:
            raise live_exc
        return list(live or [])
    monkeypatch.setattr(OE, "combined_order_rows", _live)


def _row(uid, amt, kind="store"):
    return {L.FIELD: uid, "판매처": "쿠팡", "주문금액": amt, "_src": kind}


# ── ① 과거는 적재분 ────────────────────────────────────────────
def test_과거_구간은_적재분에서_온다(monkeypatch):
    seen = {}
    _stub(monkeypatch, stored=[_row("c|1", 100), _row("c|2", 200)],
          coverage=[{"market": "coupang", "oldest": "2025-01-01", "newest": "2026-07-20"}])
    import lemouton.markets.order_export as OE
    monkeypatch.setattr(OE, "combined_order_rows",
                        lambda m, since=None, until=None, warnings=None: seen.update(since=since) or [])
    w = []
    rows = SRC.fetch_rows(_dt.datetime(2025, 7, 21, tzinfo=KST), NOW, ["coupang"], warnings=w)
    assert len(rows) == 2
    # 라이브는 최근 꼬리(5일)만 — since 가 요청 1년전이 아니라 now-5일
    assert seen["since"] >= NOW - _dt.timedelta(days=6)


# ── ② 최근 라이브 보충 ─────────────────────────────────────────
def test_최근_주문은_라이브로_보충된다(monkeypatch):
    _stub(monkeypatch, stored=[_row("c|old", 100)],
          live=[_row("c|today", 300, "live")],
          coverage=[{"market": "coupang", "oldest": "2025-01-01", "newest": "2026-07-19"}])
    rows = SRC.fetch_rows(NOW - _dt.timedelta(days=30), NOW, ["coupang"])
    uids = {r[L.FIELD] for r in rows}
    assert "c|today" in uids and "c|old" in uids


# ── ③ 중복 제거 ────────────────────────────────────────────────
def test_겹치는_주문은_한_번만_라이브가_이긴다(monkeypatch):
    _stub(monkeypatch,
          stored=[_row("c|1", 100, "store")],
          live=[_row("c|1", 150, "live")],        # 같은 주문, 라이브가 최신(정산 갱신)
          coverage=[{"market": "coupang", "oldest": "2025-01-01", "newest": "2026-07-21"}])
    rows = SRC.fetch_rows(NOW - _dt.timedelta(days=10), NOW, ["coupang"])
    assert len(rows) == 1
    assert rows[0]["주문금액"] == 150 and rows[0]["_src"] == "live"


def test_키_없는_라이브행도_버리지_않는다(monkeypatch):
    live = [{"판매처": "옥션", "주문금액": 50}]      # line_uid 없음
    _stub(monkeypatch, stored=[], live=live, coverage=[])
    rows = SRC.fetch_rows(NOW - _dt.timedelta(days=3), NOW, ["auction"])
    assert len(rows) == 1


# ── ④ 적재 범위 부족 경고 ──────────────────────────────────────
def test_적재가_요청보다_짧으면_경고한다(monkeypatch):
    _stub(monkeypatch, stored=[_row("c|1", 100)],
          coverage=[{"market": "coupang", "oldest": "2026-05-01", "newest": "2026-07-21"}])
    w = []
    SRC.fetch_rows(_dt.datetime(2025, 7, 21, tzinfo=KST), NOW, ["coupang"], warnings=w)
    assert any("저장된 범위" in x or "저장돼 있지 않" in x for x in w)


def test_적재가_충분하면_경고_없다(monkeypatch):
    _stub(monkeypatch, stored=[_row("c|1", 100)],
          coverage=[{"market": "coupang", "oldest": "2025-01-01", "newest": "2026-07-21"}])
    w = []
    SRC.fetch_rows(_dt.datetime(2025, 7, 21, tzinfo=KST), NOW, ["coupang"], warnings=w)
    assert not any("저장" in x for x in w)


def test_적재_전혀_없는_마켓은_경고(monkeypatch):
    _stub(monkeypatch, stored=[], coverage=[])
    w = []
    SRC.fetch_rows(NOW - _dt.timedelta(days=100), NOW, ["auction"], warnings=w)
    assert any("auction" in x for x in w)


# ── ⑤ 실패해도 조용하지 않게 ───────────────────────────────────
def test_라이브_보충_실패해도_적재분은_준다(monkeypatch):
    _stub(monkeypatch, stored=[_row("c|1", 100)],
          coverage=[{"market": "coupang", "oldest": "2025-01-01", "newest": "2026-07-21"}],
          live_exc=RuntimeError("429"))
    w = []
    rows = SRC.fetch_rows(NOW - _dt.timedelta(days=30), NOW, ["coupang"], warnings=w)
    assert len(rows) == 1
    assert any("라이브 보충에 실패" in x for x in w)


def test_적재_읽기_실패는_사유를_남긴다(monkeypatch):
    _stub(monkeypatch, live=[_row("c|1", 100, "live")], coverage=[],
          store_exc=RuntimeError("db down"))
    w = []
    rows = SRC.fetch_rows(NOW - _dt.timedelta(days=3), NOW, ["coupang"], warnings=w)
    assert any("읽지 못했" in x for x in w)
    assert len(rows) == 1        # 라이브만이라도


# ── 라이브 꼬리 0일이면 라이브 안 부른다 ────────────────────────
def test_live_tail_0이면_적재분만(monkeypatch):
    called = []
    _stub(monkeypatch, stored=[_row("c|1", 100)],
          coverage=[{"market": "coupang", "oldest": "2025-01-01", "newest": "2026-07-21"}])
    import lemouton.markets.order_export as OE
    monkeypatch.setattr(OE, "combined_order_rows",
                        lambda *a, **k: called.append(1) or [])
    SRC.fetch_rows(NOW - _dt.timedelta(days=30), NOW, ["coupang"], live_tail_days=0)
    assert called == []
