# -*- coding: utf-8 -*-
"""정산 「깊은 백필」 — 창 밖에서 확정된 정산이 영영 안 들어오던 것.

🔴 2026-08-07 라이브 — 평소 스윕이 최근 45~75일만 봐서, 그 창이 닫힌 뒤 확정된 정산이
   「이미 받았을 것(확인 불가)」로 **1억 5,242만원** 쌓여 있었다. 손으로 과거를 넓게
   훑으니 1억 5,433만이 「확인」으로 넘어갔고 옥션 정산율 거짓 경고도 사라졌다.
   자동화하지 않으면 **시간이 지나며 똑같이 다시 쌓인다.**
"""
from __future__ import annotations

import datetime as _dt

import pytest

from lemouton.markets import settle_backfill as BF


@pytest.fixture(autouse=True)
def _tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(BF, "_path", lambda: str(tmp_path / "bf.json"))


D1 = _dt.date(2026, 8, 7)
D2 = _dt.date(2026, 8, 8)


def test_처음에는_첫_마켓을_준다():
    assert BF.due_market(today=D1) == BF.MARKETS[0]


def test_하루에_한_번만_돈다():
    m = BF.due_market(today=D1)
    BF.mark_done(m, today=D1)
    assert BF.due_market(today=D1) is None          # 같은 날 두 번째 틱은 건너뜀


def test_다음날은_다음_마켓으로_넘어간다():
    BF.mark_done(BF.due_market(today=D1), today=D1)
    assert BF.due_market(today=D2) == BF.MARKETS[1]


def test_한_바퀴_돌면_처음으로():
    d = D1
    for _ in range(len(BF.MARKETS)):
        BF.mark_done(BF.due_market(today=d), today=d)
        d += _dt.timedelta(days=1)
    assert BF.due_market(today=d) == BF.MARKETS[0]


def test_연동_안_된_마켓은_건너뛴다():
    """지원 목록에 없는 마켓을 부르면 헛일 + 에러 로그만 쌓인다."""
    got = BF.due_market(today=D1, supported={"lotteon", "smartstore"})
    assert got in ("lotteon", "smartstore")


def test_지원_마켓이_하나도_없으면_None():
    assert BF.due_market(today=D1, supported=set()) is None


def test_실패해도_다음_마켓으로_넘어간다():
    """같은 마켓에서 매 틱 재시도하면 다른 마켓이 영영 굶는다."""
    BF.mark_done("coupang", today=D1, stat={"errors": ["실패"], "updated": 0})
    assert BF.due_market(today=D2) == BF.MARKETS[1]


def test_기록을_남긴다():
    BF.mark_done("coupang", today=D1, stat={"updated": 457, "settle_rows": 811,
                                            "errors": []})
    h = BF.load()["history"][-1]
    assert h["market"] == "coupang" and h["updated"] == 457 and h["errors"] == 0


def test_기록은_최근_30회만():
    d = D1
    for i in range(35):
        BF.mark_done("coupang", today=d)
        d += _dt.timedelta(days=1)
    assert len(BF.load()["history"]) == 30


def test_창은_오늘부터_과거_180일():
    s, u = BF.window(today=D1)
    assert (u - s).days == 180
    assert u.date() == D1


def test_깨진_파일이어도_처음처럼_시작한다(tmp_path):
    (tmp_path / "bf.json").write_text("{망가짐", encoding="utf-8")
    assert BF.due_market(today=D1) == BF.MARKETS[0]
