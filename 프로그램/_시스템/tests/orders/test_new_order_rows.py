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
