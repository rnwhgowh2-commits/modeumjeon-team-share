# -*- coding: utf-8 -*-
"""클레임 조회가 실패하면 **화면이 말해야 한다** — 지금은 조용히 넘어간다.

2026-08-13 실측에서 드러난 구멍:
  `_esm_all_orders` 는 클레임 조회가 터지면 `diag["errors"]["클레임조회"]` 에만
  적고 그대로 return 한다. `warnings` 에는 아무것도 안 담긴다.
  → 주문은 보이는데 **취소·반품·교환 상태가 통째로 빠진 채** 정상처럼 보인다.
  이 프로젝트 최대 금기(조용한 누락)이고, 그 때문에 「동시 발송이 거부당했는지」를
  화면만 봐서는 가릴 수 없었다.
"""
import datetime as _dt

import pytest

from lemouton.markets import order_export as oe

SINCE = _dt.datetime(2026, 8, 12, 0, 0)
UNTIL = _dt.datetime(2026, 8, 12, 23, 59)


def test_클레임_실패가_화면_경고로_올라온다(monkeypatch):
    """주문은 살리되, 무엇이 빠졌는지는 반드시 말한다."""
    import shared.platforms.esm.claims as C

    def boom(*a, **k):
        raise RuntimeError("ESM 호출제한 ResultCode=3000")

    monkeypatch.setattr(C, "iter_all", boom)
    monkeypatch.setattr(oe, "_BUILDERS", dict(oe._BUILDERS))

    def fake_orders(market, since, until, *, client, **kw):
        return iter([])

    monkeypatch.setattr("shared.platforms.esm.orders.iter_orders", fake_orders)

    warns = []
    diag = {}
    list(oe._esm_all_orders("auction", SINCE, UNTIL, client=object(),
                            diag=diag, warnings=warns))
    assert diag.get("errors", {}).get("클레임조회"), "사유가 diag 에도 없다"
    합 = " ".join(warns)
    assert warns, "클레임이 통째로 빠졌는데 화면에 아무 말도 없다"
    assert "클레임" in 합 or "취소" in 합, "무엇이 빠졌는지 안 말함: %s" % 합
    assert "3000" in 합 or "호출제한" in 합, "원문 사유를 버렸다: %s" % 합


def test_클레임이_성공하면_괜한_경고는_안_붙인다(monkeypatch):
    import shared.platforms.esm.claims as C
    monkeypatch.setattr(C, "iter_all", lambda *a, **k: iter([]))
    monkeypatch.setattr("shared.platforms.esm.orders.iter_orders",
                        lambda market, since, until, *, client, **kw: iter([]))
    warns, diag = [], {}
    list(oe._esm_all_orders("auction", SINCE, UNTIL, client=object(),
                            diag=diag, warnings=warns))
    assert warns == [], "정상인데 경고가 붙었다: %s" % warns
    assert "클레임조회초" in diag.get("counts", {}), "몇 초 걸렸는지를 안 남긴다"
