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


# ── 클레임행과 주문행의 병합 (2026-07-21 검수 발견분) ────────────
def test_클레임행이_같은_uid의_주문행을_지우지_않는다(monkeypatch):
    """스스·ESM·롯데온(209경로) 클레임행은 주문행과 line_uid 가 같다. dict 병합에서
    클레임이 매출(주문)행을 삼키면 그 판매가 마진에서 통째로 사라진다(라이브 74쌍)."""
    order = {L.FIELD: "auction|123", "판매처": "옥션", "주문금액": 30000, "_kind": "order"}
    claim = {L.FIELD: "auction|123", "판매처": "옥션", "_kind": "change",
             "_change_date": "2026-07-01", "주문상태원본": "21"}
    _stub(monkeypatch, stored=[order, claim],
          coverage=[{"market": "auction", "oldest": "2025-01-01", "newest": "2026-07-21"}])
    rows = SRC.fetch_rows(NOW - _dt.timedelta(days=30), NOW, ["auction"])
    kinds = sorted(str(r.get("_kind")) for r in rows)
    assert kinds == ["change", "order"], "클레임이 매출행을 대체하면 안 된다(둘 다 보존)"


def test_uid없는_클레임은_적재_라이브에_겹쳐도_한번만(monkeypatch):
    """쿠팡 클레임행은 line_uid 조각이 없다. 적재분과 라이브 꼬리(5일)에 같은 취소건이
    양쪽으로 오면 2행이 된다 — 클레임 이벤트키로 접어야 한다."""
    claim = {"판매처": "쿠팡", "_kind": "change", "오픈마켓주문번호": "CP1",
             "_change_date": "2026-07-19", "주문상태원본": "RU"}
    _stub(monkeypatch, stored=[dict(claim)], live=[dict(claim)],
          coverage=[{"market": "coupang", "oldest": "2025-01-01", "newest": "2026-07-21"}])
    rows = SRC.fetch_rows(NOW - _dt.timedelta(days=30), NOW, ["coupang"])
    assert len(rows) == 1, "같은 클레임이 두 번 계상되면 안 된다"


# ── 수집이 밀렸을 때의 공백 경고 ────────────────────────────────
def test_수집이_라이브꼬리보다_뒤처지면_공백을_경고한다(monkeypatch):
    """적재 newest 가 8일 전 + 라이브 보충 5일 → 6~8일 전 구간이 무경고로 빠진다."""
    _stub(monkeypatch, stored=[_row("c|1", 100)],
          coverage=[{"market": "coupang", "oldest": "2025-01-01", "newest": "2026-07-13"}])
    w = []
    SRC.fetch_rows(NOW - _dt.timedelta(days=30), NOW, ["coupang"], warnings=w)
    assert any("수집" in x for x in w), "수집 공백은 조용히 넘기면 안 된다"


def test_수집이_라이브꼬리_안이면_공백_경고_없다(monkeypatch):
    _stub(monkeypatch, stored=[_row("c|1", 100)],
          coverage=[{"market": "coupang", "oldest": "2025-01-01", "newest": "2026-07-18"}])
    w = []
    SRC.fetch_rows(NOW - _dt.timedelta(days=30), NOW, ["coupang"], warnings=w)
    assert w == []


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


# ── ⑥ 저장분도 주문내역 화면과 같은 수준으로 보강한다 ────────────
#  2026-07-24 실측 — 주문내역(라이브)은 조회 결과에 이력 채움·정산 추정을 태워 보여주는데
#  그 보강이 저장분엔 안 남아, 저장분만 읽는 마진 분석이 같은 주문을 덜 채워진 채로 봤다
#  (11번가 정산 16·실결제 19·단가 10 · 롯데온 실결제 32 공란). 사장님 지시로 읽기 시 보강.

def test_적재분도_주문내역과_같은_보강을_받는다(monkeypatch):
    _stub(monkeypatch, stored=[_row("c|1", 100)],
          coverage=[{"market": "coupang", "oldest": "2025-01-01", "newest": "2026-07-21"}])
    import lemouton.markets.order_export as OE
    got = {}

    def _enrich(rows, session=None):
        got["uids"] = [r[L.FIELD] for r in rows]
        for r in rows:
            r["상품명"] = "채워짐"            # 보강 결과가 반환 행에 반영되는지
        return rows

    monkeypatch.setattr(OE, "enrich_stored_rows", _enrich)
    rows = SRC.fetch_rows(NOW - _dt.timedelta(days=30), NOW, ["coupang"], live_tail_days=0)
    assert got["uids"] == ["c|1"]
    assert [r.get("상품명") for r in rows] == ["채워짐"]


def test_보강이_실패해도_주문은_그대로_돌려준다(monkeypatch):
    _stub(monkeypatch, stored=[_row("c|1", 100)],
          coverage=[{"market": "coupang", "oldest": "2025-01-01", "newest": "2026-07-21"}])
    import lemouton.markets.order_export as OE
    monkeypatch.setattr(OE, "enrich_stored_rows",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("보강 실패")))
    rows = SRC.fetch_rows(NOW - _dt.timedelta(days=30), NOW, ["coupang"], live_tail_days=0)
    assert [r[L.FIELD] for r in rows] == ["c|1"]     # 보강 실패가 주문을 지우지 않는다


def test_적재분_비면_보강_안부른다(monkeypatch):
    _stub(monkeypatch, stored=[],
          coverage=[{"market": "coupang", "oldest": "2025-01-01", "newest": "2026-07-21"}])
    import lemouton.markets.order_export as OE
    monkeypatch.setattr(OE, "enrich_stored_rows",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("호출 금지")))
    assert SRC.fetch_rows(NOW - _dt.timedelta(days=30), NOW, ["coupang"],
                          live_tail_days=0) == []
