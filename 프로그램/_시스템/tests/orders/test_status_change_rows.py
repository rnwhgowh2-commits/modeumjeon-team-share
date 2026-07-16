# -*- coding: utf-8 -*-
"""status_change_rows — _kind='change' 를 변경일 기준으로 수집."""
import datetime as dt
import pytest
from lemouton.markets import order_export as oe

KST = dt.timezone(dt.timedelta(hours=9))
SINCE = dt.datetime(2026, 7, 15, tzinfo=KST)
UNTIL = dt.datetime(2026, 7, 15, 23, 59, tzinfo=KST)


def _fake_fetch(rows):
    def _f(markets, days, now, since=None, until=None, include_settlement=True, warnings=None):
        return list(rows)
    return _f


def test_keeps_change_rows_in_change_window(monkeypatch):
    rows = [
        {"_kind": "order", "주문일": "2026-07-15 09:00:00", "주문상태": "결제완료"},
        {"_kind": "change", "_change_date": "20260715120000", "주문상태": "취소요청", "오픈마켓주문번호": "A"},
        {"_kind": "change", "_change_date": "20260710120000", "주문상태": "반품완료", "오픈마켓주문번호": "B"},
        {"_kind": "change", "_change_date": "", "주문상태": "교환요청", "오픈마켓주문번호": "C"},
    ]
    monkeypatch.setattr(oe, "_fetch_combined", _fake_fetch(rows))
    out = oe.status_change_rows(["lotteon"], since=SINCE, until=UNTIL)
    assert {r["오픈마켓주문번호"] for r in out} == {"A"}   # 변경일 창내 change 만(order·창밖·공란 제외)


def test_parses_iso_change_date(monkeypatch):
    rows = [{"_kind": "change", "_change_date": "2026-07-15T12:00:00", "주문상태": "취소요청", "오픈마켓주문번호": "D"}]
    monkeypatch.setattr(oe, "_fetch_combined", _fake_fetch(rows))
    out = oe.status_change_rows(["coupang"], since=SINCE, until=UNTIL)
    assert [r["오픈마켓주문번호"] for r in out] == ["D"]
