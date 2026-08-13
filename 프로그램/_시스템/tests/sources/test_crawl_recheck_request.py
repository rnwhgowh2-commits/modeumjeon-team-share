# -*- coding: utf-8 -*-
"""「확인 요청」 표식 — 이행 판단이 찍으면 **두 경로 모두**에서 먼저 긁힌다 (노션 ⑤).

사장님 확정: *"변경값 없는건 저장된 크롤값 그대로 + 변경값있는건 새로 긁고 판정.
해당 주문건에 소싱처 url 있는것만 긁으면 돼"*
「변경값」 = **그 상품의 가격·재고가 바뀐 것**(2026-08-13 확인). 그 신호는 이미 있다 —
크롤이 `CrawlDelta` 를 남기며 `no_change_streak` 를 0 으로 되돌린다.

🔴 마감(due) 경로가 **둘**이라는 게 이 시험의 존재 이유다:
   · 기준주기 > 0  → 벽시계 경로(`due_products` → `overdue_seconds`)
   · 기준주기 ≤ 0  → 가중 라운드로빈 랩(`next_lap_products` → `weighted_due_products`)
   한 쪽에만 끼우면 **설정에 따라 조용히 안 도는** 기능이 된다.
"""
import datetime as dt

import pytest

from lemouton.sources import crawl_schedule as CS

NOW = dt.datetime(2026, 8, 13, 12, 0, 0)


# ── ① 벽시계 경로 ────────────────────────────────────────────────────────────

def test_확인요청은_아직_때가_안_됐어도_마감이다():
    """방금 긁어 한참 남았어도, 확인 요청이 있으면 지금 긁어야 한다."""
    just_now = NOW - dt.timedelta(seconds=10)      # 10초 전에 긁음
    assert CS.is_due(NOW, just_now, 3600, 1, 0) is False          # 평소엔 아직
    # 사장님이 **그 뒤에** 판단 단추를 눌렀다 → 지금 다시 긁어야 한다
    assert CS.is_due(NOW, just_now, 3600, 1, 0,
                     recheck_requested_at=NOW) is True


def test_확인요청은_가장_앞으로_간다():
    """연체 순 정렬에서 맨 앞 — 사장님이 지금 판단하려고 누른 것이다."""
    old = CS.overdue_seconds(NOW, NOW - dt.timedelta(days=30), 3600, 1, 0)
    req = CS.overdue_seconds(NOW, NOW - dt.timedelta(seconds=10), 3600, 1, 0,
                             recheck_requested_at=NOW)
    assert req > old


def test_크롤이_끝나면_저절로_풀린다():
    """요청 뒤에 실제로 긁혔으면 더는 앞지르지 않는다 — 지우는 코드가 없어야 안 샌다."""
    req_at = NOW - dt.timedelta(minutes=10)
    fetched_after = NOW - dt.timedelta(minutes=5)      # 요청 뒤에 긁힘
    assert CS.is_due(NOW, fetched_after, 3600, 1, 0,
                     recheck_requested_at=req_at) is False


def test_크롤_제외_상품은_확인요청이어도_안_긁는다():
    """계수 0 = 「이 URL 은 안 긁는다」 — 확인 요청이 그 뜻을 뒤집으면 안 된다."""
    assert CS.is_due(NOW, NOW - dt.timedelta(days=1), 3600, 0, 0,
                     recheck_requested_at=NOW) is False


def test_확인요청_없으면_예전과_똑같다():
    """기본값 None = 아무것도 안 바뀐다(기존 동작 보호)."""
    for lf in (None, NOW - dt.timedelta(hours=2), NOW - dt.timedelta(seconds=5)):
        assert (CS.overdue_seconds(NOW, lf, 3600, 1, 0)
                == CS.overdue_seconds(NOW, lf, 3600, 1, 0, recheck_requested_at=None))


# ── ② 랩(연속 모드) 경로 ─────────────────────────────────────────────────────

class _P:
    """SourceProduct 대역 — 랩 계산이 쓰는 칸만."""

    def __init__(self, pid, weight=1, lap=0, status="ok", req=None, fetched=None):
        self.id = pid
        self.crawl_weight = weight
        self.crawl_lap_count = lap
        self.last_status = status
        self.recheck_requested_at = req
        self.last_fetched_at = fetched


def _patch_lap(monkeypatch, prods):
    monkeypatch.setattr(CS, "_lap_products", lambda s: prods)
    monkeypatch.setattr(CS, "build_batch_weight_resolver",
                        lambda s: type("R", (), {
                            "__call__": lambda self, p: p.crawl_weight,
                            "slowdown": lambda self, p: 1.0})())


def test_랩에서도_확인요청이_맨_앞이다(monkeypatch):
    """🔴 기준주기 0(연속 모드)에서는 `last_fetched_at` 을 아예 안 본다 —
    벽시계 쪽만 고치면 이 설정에서 기능이 통째로 안 돈다."""
    a = _P(1, lap=0)                                  # 아직 안 채운 평범한 URL
    b = _P(2, lap=0, req=NOW)                         # 확인 요청
    _patch_lap(monkeypatch, [a, b])
    got = CS.weighted_due_products(None)
    assert [p.id for p in got][0] == 2, [p.id for p in got]


def test_랩_확인요청은_이미_채웠어도_다시_나온다(monkeypatch):
    """이번 랩 몫을 다 채운 URL이라도, 확인 요청이 있으면 지금 긁어야 한다."""
    a = _P(1, weight=1, lap=1)                        # 몫 다 채움 → 평소엔 안 나옴
    _patch_lap(monkeypatch, [a])
    assert CS.weighted_due_products(None) == []
    a.recheck_requested_at = NOW
    assert [p.id for p in CS.weighted_due_products(None)] == [1]


def test_랩_계수0은_확인요청이어도_빠진다(monkeypatch):
    a = _P(1, weight=0, lap=0, req=NOW)
    _patch_lap(monkeypatch, [a])
    assert CS.weighted_due_products(None) == []


def test_랩_확인요청도_크롤_뒤엔_풀린다(monkeypatch):
    a = _P(1, weight=1, lap=1, req=NOW - dt.timedelta(minutes=10),
           fetched=NOW - dt.timedelta(minutes=5))
    _patch_lap(monkeypatch, [a])
    assert CS.weighted_due_products(None) == []
