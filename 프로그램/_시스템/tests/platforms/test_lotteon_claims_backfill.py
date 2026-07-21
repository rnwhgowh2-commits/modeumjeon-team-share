# -*- coding: utf-8 -*-
"""롯데온 과거 클레임 백필 모드 — 확정 전 취소는 정산API(구매확정건만)에 안 나온다.

2026-07-22 샵마인 대사: 롯데온 누락 484건 중 취소완료 계열 233건이 이 구멍.
"""
import datetime as _dt

import pytest

import lemouton.markets.order_export as oe

KST = _dt.timezone(_dt.timedelta(hours=9))
SINCE = _dt.datetime(2026, 4, 1, tzinfo=KST)
UNTIL = _dt.datetime(2026, 4, 30, tzinfo=KST)


def _no209(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("claims_only 는 209(출고지시)를 부르면 안 된다")
    monkeypatch.setattr("shared.platforms.lotteon.orders.iter_delivery_orders", boom)


def test_클레임전용_백필은_209없이_창_안만_조회한다(monkeypatch):
    _no209(monkeypatch)
    seen = {}

    def cancels(s, u, client=None):
        seen["until"] = u
        yield {"odNo": "LO1", "odSeq": "1", "clmNo": "C1", "odPrgsStepCd": "21",
               "spdNm": "상품", "sitmNm": "옵션"}

    monkeypatch.setattr("shared.platforms.lotteon.claims.iter_cancel", cancels)
    monkeypatch.setattr("shared.platforms.lotteon.claims.iter_return",
                        lambda *a, **k: iter(()))
    monkeypatch.setattr("shared.platforms.lotteon.claims.iter_exchange",
                        lambda *a, **k: iter(()))
    rows = oe.lotteon_order_rows(SINCE, UNTIL, client=object(),
                                 include_settlement=False,
                                 claims_only=True, claim_to_now=False)
    ch = [r for r in rows if r.get("_kind") == "change"]
    assert len(ch) == 1 and ch[0]["주문상태"] == "취소완료"
    assert seen["until"] == UNTIL, "'지금까지' 확장 없이 창 안만"


def test_클레임전용_백필은_조회실패를_숨기지_않는다(monkeypatch):
    """일반 경로는 클레임 실패를 삼켜도 되지만(활성 주문 유지), 백필은 클레임이
    전부라 삼키면 그 창이 조용히 빈다 — 창 실패로 전파해 재시도되게 한다."""
    _no209(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("500")
        yield  # pragma: no cover

    monkeypatch.setattr("shared.platforms.lotteon.claims.iter_cancel", boom)
    with pytest.raises(RuntimeError):
        oe.lotteon_order_rows(SINCE, UNTIL, client=object(),
                              include_settlement=False,
                              claims_only=True, claim_to_now=False)
