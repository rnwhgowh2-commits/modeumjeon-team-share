# -*- coding: utf-8 -*-
"""클레임 조회를 동시에 보내 화면 조회가 100초 벽을 안 넘게.

라이브 실측(2026-08-12) — 옥션 주문내역 7일치 조회 1회의 호출 구성:
  · 주문조회 5회 + 입금확인중 1회 = 6회. 이건 마켓 규정이 5초/1회라 ≈30초. 못 줄인다.
  · 클레임 = 취소 2창×1상태×2기준 4 + 반품 2×6×2 24 + 교환 2×5×2 20 + 미수령 1 = **49회**.
    이건 5초 제한 대상이 **아닌데도** 한 줄로 세워 보내 ≈44초가 그냥 흘렀다.
  30 + 44 ≈ 74.5초(실측과 일치). G마켓은 125.2초로 앞단 100초 한도를 넘겨 524.

그래서 클레임만 동시에 보낸다. 지켜야 할 것:
  · 결과가 순차와 **똑같아야** 한다 — 한 건이라도 달라지면 돈이 틀어진다
  · 실패는 여전히 예외로 올라와야 한다 — 조용한 0건은 이 프로젝트 최대 금기
"""
import datetime as _dt

import pytest

from shared.platforms.esm import claims as C

UNTIL = _dt.datetime(2026, 7, 20, 12, 0)
SINCE = UNTIL - _dt.timedelta(days=7)


class FakeClient:
    """호출을 기록하고, 본문에 따라 정해진 행을 돌려준다(동시성 안전)."""

    def __init__(self, rows_for=None, fail_on=None, delay=0.0):
        import threading
        self.calls = []
        self._lock = threading.Lock()
        self._rows_for = rows_for or (lambda body: [])
        self._fail_on = fail_on
        self._delay = delay
        self.max_동시 = 0
        self._동시 = 0

    def post(self, path, body, **kw):
        import time
        with self._lock:
            self.calls.append((path, dict(body)))
            self._동시 += 1
            self.max_동시 = max(self.max_동시, self._동시)
        try:
            if self._delay:
                time.sleep(self._delay)
            if self._fail_on and self._fail_on(body):
                return {"ResultCode": 9999, "Message": "마켓이 거부함"}
            return {"ResultCode": 0, "Data": self._rows_for(body)}
        finally:
            with self._lock:
                self._동시 -= 1


def _rows_by_status(body):
    """상태·기준마다 다른 주문번호 — 하나라도 빠지면 집계가 달라진다."""
    st = body.get("ReturnStatus") or body.get("ExchangeStatus") or body.get("CancelStatus")
    return [{"OrderNo": int("%d%d%s" % (st, body["Type"], body["StartDate"].replace("-", "")))}]


def test_클레임을_동시에_보낸다():
    c = FakeClient(rows_for=_rows_by_status, delay=0.02)
    list(C.iter_returns("auction", SINCE, UNTIL, client=c))
    assert c.max_동시 > 1, "여전히 한 줄로 보낸다 — 동시 최대 %d" % c.max_동시


def test_동시로_보내도_결과가_순차와_똑같다():
    """한 건이라도 달라지면 돈이 틀어진다 — 가장 중요한 시험."""
    seq = FakeClient(rows_for=_rows_by_status)
    par = FakeClient(rows_for=_rows_by_status)
    import shared.platforms.esm.claims as M
    old = M._CLAIM_CONCURRENCY
    try:
        M._CLAIM_CONCURRENCY = 1
        a = [r["OrderNo"] for r in M.iter_returns("auction", SINCE, UNTIL, client=seq)]
        M._CLAIM_CONCURRENCY = 8
        b = [r["OrderNo"] for r in M.iter_returns("auction", SINCE, UNTIL, client=par)]
    finally:
        M._CLAIM_CONCURRENCY = old
    assert sorted(a) == sorted(b), "동시로 보냈더니 결과가 달라졌다"
    assert len(a) == len(set(a)), "순차본에 중복이 있다(시험 자체가 헛돎)"
    assert len(a) > 1, "받은 행이 너무 적어 비교가 무의미하다"


def test_한_건이_실패하면_예외로_올라온다():
    """조용한 0건 금지 — 동시로 보내도 실패를 삼키면 안 된다."""
    c = FakeClient(rows_for=_rows_by_status,
                   fail_on=lambda b: b.get("ReturnStatus") == 3)
    with pytest.raises(RuntimeError) as e:
        list(C.iter_returns("auction", SINCE, UNTIL, client=c))
    assert "9999" in str(e.value) or "거부" in str(e.value)


def test_호출_수는_그대로다():
    """동시로 보내는 것이지 **덜 보내는** 게 아니다 — 빠뜨리면 주문이 샌다."""
    c = FakeClient(rows_for=_rows_by_status)
    list(C.iter_returns("auction", SINCE, UNTIL, client=c))
    # 7일 → 6일 창 2개 × 반품상태 6종 × 기준(신청·완료) 2 = 24
    assert len(c.calls) == 24, "호출 수가 24가 아니라 %d" % len(c.calls)
