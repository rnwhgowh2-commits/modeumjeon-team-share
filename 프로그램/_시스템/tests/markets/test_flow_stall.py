# -*- coding: utf-8 -*-
"""배송흐름 감시 — 송장 넣고 24시간 넘게 안 움직인 주문.

사장님 정의(2026-07-24): 엑셀과 무관하게, 송장번호가 들어간 주문 중 24시간이
지나도 배송 흐름에 변화가 없는 건.
"""
import datetime as _dt

from lemouton.markets import flow_stall as fs

NOW = _dt.datetime(2026, 7, 24, 12, 0, tzinfo=fs.KST)


def _row(**kw):
    base = {"주문상태": "배송준비중", "송장입력": "505045353994",
            "발송처리일": "2026-07-23 09:00:00", "판매처": "스마트스토어"}
    base.update(kw)
    return base


def test_송장넣고_24시간_넘으면_멈춤이다():
    v, h = fs.judge(_row(), NOW)
    assert v == "stalled" and round(h) == 27


def test_24시간_안_지났으면_아직_멈춘_게_아니다():
    v, _ = fs.judge(_row(발송처리일="2026-07-24 01:00:00"), NOW)
    assert v == "moving"


def test_이미_배송중이면_흐름이_시작된_것이다():
    """배송중·배송완료로 넘어갔으면 택배가 움직이고 있다 — 경보 대상 아님."""
    for st in ("배송중", "배송완료", "구매확정"):
        v, _ = fs.judge(_row(주문상태=st), NOW)
        assert v == "moving", st


def test_송장이_없으면_감시_대상이_아니다():
    """아직 안 보낸 주문이다 — 멈춘 게 아니라 시작을 안 한 것."""
    for inv in ("", "송장미입력", "확인 불가"):
        v, _ = fs.judge(_row(송장입력=inv), NOW)
        assert v == "no_invoice", inv


def test_송장칸에_번호가_아닌_문구가_들어와도_속지_않는다():
    """샵마인은 송장열에 '송장입력됨' 같은 상태 문구를 넣는다 — 번호가 아니다."""
    v, _ = fs.judge(_row(송장입력="송장입력됨"), NOW)
    assert v == "no_invoice"


def test_기준시각이_없으면_멈췄다고_말하지_않는다():
    """'언제부터 멈췄는지' 모르는데 멈췄다고 하면 거짓 경보다."""
    v, _ = fs.judge(_row(발송처리일=""), NOW)
    assert v == "unknown"


def test_여러_날짜_모양을_읽는다():
    """마켓마다 발송처리일 표기가 다르다 — 못 읽으면 통째로 판정 불가가 된다."""
    for s in ("2026-07-23 09:00:00", "2026-07-23T09:00:00", "20260723090000",
              "2026-07-23", "2026-07-23T09:00:00+09:00"):
        assert fs._parse_dt(s) is not None, s


def test_판정_못_한_건수를_숨기지_않는다(monkeypatch):
    """쿠팡·옥션·G마켓은 발송처리일을 안 준다 — 조용히 빠지면 안 보인다."""
    rows = [_row(), _row(발송처리일="", 판매처="쿠팡"), _row(발송처리일="", 판매처="옥션")]
    monkeypatch.setattr(fs, "__name__", fs.__name__)
    from lemouton.markets import order_store
    monkeypatch.setattr(order_store, "load", lambda **k: rows)
    got = fs.find_stalled(now=NOW)
    assert got["count"] == 1
    assert got["unknown"] == 2
    assert got["per_market"] == {"스마트스토어": 1}


def test_오래_멈춘_것부터_보여준다(monkeypatch):
    rows = [_row(발송처리일="2026-07-23 09:00:00"),
            _row(발송처리일="2026-07-21 09:00:00"),
            _row(발송처리일="2026-07-22 09:00:00")]
    from lemouton.markets import order_store
    monkeypatch.setattr(order_store, "load", lambda **k: rows)
    got = fs.find_stalled(now=NOW)
    hours = [r["_stall_hours"] for r in got["rows"]]
    assert hours == sorted(hours, reverse=True)
    assert round(hours[0]) == 75
