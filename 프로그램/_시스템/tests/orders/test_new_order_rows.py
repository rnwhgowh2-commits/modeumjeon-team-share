# -*- coding: utf-8 -*-
"""new_order_rows — 실주문일이 기간 안인 행만 남기는 필터."""
import datetime as dt
import pytest
from lemouton.markets import order_export as oe

KST = dt.timezone(dt.timedelta(hours=9))
SINCE = dt.datetime(2026, 7, 15, tzinfo=KST)
UNTIL = dt.datetime(2026, 7, 15, 23, 59, tzinfo=KST)


def _fake_combined(rows):
    def _f(markets, **kw):
        return list(rows)
    return _f


def test_keeps_order_rows_regardless_of_status(monkeypatch):
    rows = [
        {"오픈마켓주문번호": "A", "주문일": "2026-07-15 09:00:00", "주문상태": "결제완료", "_kind": "order"},
        {"오픈마켓주문번호": "B", "주문일": "2026-07-15 10:00:00", "주문상태": "취소완료", "_kind": "order"},
    ]
    monkeypatch.setattr(oe, "combined_order_rows", _fake_combined(rows))
    out = oe.new_order_rows(["smartstore"], since=SINCE, until=UNTIL)
    assert {r["오픈마켓주문번호"] for r in out} == {"A", "B"}   # 취소여도 order면 남김


def test_change_in_window_kept_out_of_window_dropped(monkeypatch):
    rows = [
        {"오픈마켓주문번호": "C", "주문일": "2026-07-15 08:00:00", "주문상태": "취소요청", "_kind": "change"},
        {"오픈마켓주문번호": "D", "주문일": "2026-07-10 08:00:00", "주문상태": "취소요청", "_kind": "change"},
    ]
    monkeypatch.setattr(oe, "combined_order_rows", _fake_combined(rows))
    out = oe.new_order_rows(["lotteon"], since=SINCE, until=UNTIL)
    assert {r["오픈마켓주문번호"] for r in out} == {"C"}   # 기간 안 change만


def test_change_blank_orderdate_dropped(monkeypatch):
    rows = [
        {"오픈마켓주문번호": "E", "주문일": "", "주문상태": "취소완료", "_kind": "change"},
        {"오픈마켓주문번호": "F", "주문일": "2026-07-15 08:00:00", "주문상태": "결제완료", "_kind": "order"},
    ]
    monkeypatch.setattr(oe, "combined_order_rows", _fake_combined(rows))
    out = oe.new_order_rows(["coupang"], since=SINCE, until=UNTIL)
    assert {r["오픈마켓주문번호"] for r in out} == {"F"}   # 공란 change(쿠팡·11번가) 제외


def test_fetch_combined_default_tags_kind_order(monkeypatch):
    """빌더가 _kind 를 안 붙여도 _fetch_combined 가 'order'로 기본 태그(후속 태스크 의존)."""
    def _fake_order_rows(market, **kw):          # _fetch_combined 의 per-market 디스패치
        return [{"오픈마켓주문번호": "G", "주문일": "2026-07-15 09:00:00",
                 "주문상태": "결제완료"}]          # ★ _kind 키 없음
    monkeypatch.setattr(oe, "order_rows", _fake_order_rows)
    rows = oe._fetch_combined(["smartstore"], days=7, now=SINCE,
                              since=SINCE, until=UNTIL)
    assert rows and rows[0]["오픈마켓주문번호"] == "G"
    assert all(r.get("_kind") == "order" for r in rows)   # 기본 태그 붙음


def test_preview_json_uses_new_order_rows(monkeypatch):
    """preview.json 이 new_order_rows(=옛주문 상태변경 제외)를 쓰는지."""
    import pathlib
    from flask import Flask
    from webapp.routes import orders as om

    called = {"fn": None}

    def _fake_new(markets, **kw):
        called["fn"] = "new_order_rows"
        return [{"오픈마켓주문번호": "A", "주문일": "2026-07-15 09:00:00", "_kind": "order"}]

    monkeypatch.setattr(om._oe, "new_order_rows", _fake_new)

    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    client = app.test_client()

    resp = client.get("/orders/preview.json?markets=smartstore&days=7")
    assert resp.status_code == 200
    assert called["fn"] == "new_order_rows"


def test_window_days_fallback_and_since_until():
    """_window — since/until 없으면 최근 days일, 있으면 그 범위."""
    lo, hi = oe._window(None, None, days=3,
                        now=dt.datetime(2026, 7, 15, 12, tzinfo=KST))
    assert (lo, hi) == (dt.date(2026, 7, 12), dt.date(2026, 7, 15))
    assert oe._window(SINCE, UNTIL, 7) == (dt.date(2026, 7, 15), dt.date(2026, 7, 15))
