# -*- coding: utf-8 -*-
"""정산 스윕 틱에 얹힌 「깊은 백필」 — 하루 한 마켓씩 과거 180일.

🔴 2026-08-07 라이브 — 평소 스윕이 최근 45~75일만 봐서 창 밖 정산이 「확인 불가」로
   1억 5,242만원 쌓여 있었다. 손으로 넓게 훑어 1억 5,433만을 되찾았고, 이 틱이 그걸 자동화한다.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from lemouton.markets import settle_backfill as BF
from scheduler import main as SM


@pytest.fixture(autouse=True)
def _tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(BF, "_path", lambda: str(tmp_path / "bf.json"))


def _spy(monkeypatch, *, fail=False):
    """각 스윕 함수를 가로채 (마켓, 창) 을 기록한다."""
    calls = []
    from lemouton.markets import order_ingest as OI

    def mk(name):
        def _f(*a, since=None, until=None, **kw):
            calls.append({"market": name if not a else a[0],
                          "days": (until - since).days if (since and until) else None})
            if fail:
                raise RuntimeError("마켓이 막힘")
            return {"updated": 3, "settle_rows": 7, "errors": [], "accounts": 1}
        return _f
    monkeypatch.setattr(OI, "refresh_settlement_coupang", mk("coupang"))
    monkeypatch.setattr(OI, "refresh_settlement_smartstore", mk("smartstore"))
    monkeypatch.setattr(OI, "refresh_settlement_lotteon", mk("lotteon"))
    monkeypatch.setattr(OI, "refresh_settlement_eleven11", mk("eleven11"))
    monkeypatch.setattr(OI, "refresh_settlement", mk("esm"))
    return calls


def test_하루에_한_마켓만_과거_180일로_훑는다(monkeypatch):
    calls = _spy(monkeypatch)
    SM._deep_backfill_once(set(BF.MARKETS))
    assert len(calls) == 1
    assert calls[0]["days"] == BF.DEEP_DAYS          # 평소 창(45~75일)보다 훨씬 넓다


def test_같은_날_두_번째_틱은_건너뛴다(monkeypatch):
    calls = _spy(monkeypatch)
    SM._deep_backfill_once(set(BF.MARKETS))
    SM._deep_backfill_once(set(BF.MARKETS))
    assert len(calls) == 1                          # 30분 틱마다 무거운 조회를 반복하지 않는다


def test_마켓이_막혀도_다음_마켓으로_넘어간다(monkeypatch):
    """한 마켓에서 계속 넘어지면 나머지가 영영 굶는다."""
    _spy(monkeypatch, fail=True)
    first = BF.due_market(today=_dt.date.today())
    SM._deep_backfill_once(set(BF.MARKETS))
    st = BF.load()
    assert st["last_date"] == _dt.date.today().isoformat()
    assert st["history"][-1]["market"] == first
    assert st["history"][-1]["errors"] == 1          # 실패를 조용히 삼키지 않는다


def test_연동_안_된_마켓은_안_부른다(monkeypatch):
    calls = _spy(monkeypatch)
    SM._deep_backfill_once({"lotteon"})
    assert len(calls) == 1 and calls[0]["market"] == "lotteon"


def test_지원_마켓이_없으면_아무것도_안_한다(monkeypatch):
    calls = _spy(monkeypatch)
    SM._deep_backfill_once(set())
    assert calls == []
