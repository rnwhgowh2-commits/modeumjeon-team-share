"""수집 잡 — 청크 분할과 실패 처리 계약.

가장 큰 위험: 11번가는 조회 창 상한을 **에러가 아니라 빈 응답**으로 알린다
(2026-07-20 실측: 7일 15건 → 8일 0건). 청크를 상한보다 크게 잡으면 주문이
에러 없이 사라진다. 그래서 청크 크기를 테스트로 못 박는다.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from lemouton.markets import order_ingest as OI

KST = OI.KST


def _dt_(y, m, d):
    return _dt.datetime(y, m, d, tzinfo=KST)


# ── 청크 크기 ─────────────────────────────────────────────────
@pytest.mark.parametrize("market,limit", [
    ("smartstore", 1),    # 실측 24시간
    ("lotteon", 1),       # 실측 1일
    ("eleven11", 7),      # 실측 7일 — 초과 시 조용히 0건 🔴
    ("coupang", 31),      # 실측 31일
    ("gmarket", 31),      # 실측 31일
    ("auction", 180),     # 실측 180일
])
def test_청크는_실측_상한을_넘지_않는다(market, limit):
    assert OI.chunk_days(market) <= limit, f"{market} 청크가 마켓 상한을 넘는다"


def test_11번가_청크는_7일을_절대_안_넘는다():
    """이 값을 올리면 에러 없이 주문이 사라진다. 실측 근거가 있는 상수다."""
    assert OI.chunk_days("eleven11") == 7


def test_모르는_마켓은_좁은_청크를_쓴다():
    """넓게 잡아 조용히 잃느니 느린 게 낫다."""
    assert OI.chunk_days("shopmine") <= 7


# ── 구간 분할 ─────────────────────────────────────────────────
def test_구간을_청크로_끊는다():
    wins = list(OI.windows(_dt_(2026, 1, 1), _dt_(2026, 1, 10), 3))
    assert len(wins) == 3
    assert all((e - s).days <= 3 for s, e in wins)


def test_최신부터_과거_순으로_돈다():
    """중간에 끊겨도 어디까지 됐는지 명확하고, 먼저 사라지는 과거를 나중에 다룬다."""
    wins = list(OI.windows(_dt_(2026, 1, 1), _dt_(2026, 1, 10), 3))
    assert wins[0][1] > wins[-1][1]


def test_구간_전체를_빠짐없이_덮는다():
    since, until = _dt_(2026, 1, 1), _dt_(2026, 1, 10)
    wins = list(OI.windows(since, until, 4))
    assert wins[0][1] == until and wins[-1][0] == since
    for a, b in zip(wins, wins[1:]):        # 최신→과거라 앞 구간의 시작 = 뒤 구간의 끝
        assert a[0] == b[1], "구간 사이에 구멍이 있으면 주문이 빠진다"


def test_청크가_구간보다_크면_한_번만_돈다():
    assert len(list(OI.windows(_dt_(2026, 1, 1), _dt_(2026, 1, 5), 30))) == 1


def test_청크가_0이하면_1일로_보정한다():
    """0 이면 무한루프가 된다."""
    assert len(list(OI.windows(_dt_(2026, 1, 1), _dt_(2026, 1, 3), 0))) == 2


# ── 실패 처리 ─────────────────────────────────────────────────
def test_한_청크가_실패해도_나머지는_계속한다(monkeypatch):
    calls = []

    def fake(market, start, end, session=None, include_settlement=True):
        calls.append(start)
        if len(calls) == 2:
            raise RuntimeError("429 rate limit")
        return {"fetched": 1, "orders_new": 1, "orders_updated": 0,
                "claims_new": 0, "claims_updated": 0, "skipped_no_uid": 0}

    monkeypatch.setattr(OI, "ingest_window", fake)
    got = OI.backfill(["coupang"], days=90)[0]
    assert got["windows"] == 3
    assert got["orders_new"] == 2                 # 실패한 1개 빼고 적재
    assert len(got["errors"]) == 1 and "429" in got["errors"][0]


def test_실패를_숨기지_않는다(monkeypatch):
    """부분 성공을 성공이라 하면 구멍이 난 걸 아무도 모른다."""
    monkeypatch.setattr(OI, "ingest_window",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    got = OI.backfill(["coupang"], days=60)[0]
    assert got["orders_new"] == 0
    assert len(got["errors"]) == got["windows"] > 0


def test_진행률_콜백이_호출된다(monkeypatch):
    seen = []
    monkeypatch.setattr(OI, "ingest_window",
                        lambda *a, **k: {"fetched": 0, "orders_new": 0})
    OI.backfill(["coupang"], days=90, on_progress=lambda i, n, m: seen.append((i, n, m)))
    assert seen and seen[-1][0] == seen[-1][1] == 3


# ── 규모 예측 ─────────────────────────────────────────────────
def test_백필_규모를_미리_알려준다():
    """1년치가 몇 번 호출인지 돌리기 전에 알 수 있어야 한다."""
    est = OI.estimate(["smartstore", "auction"], days=365)
    assert est["per_market"]["smartstore"] == 365     # 1일 창
    assert est["per_market"]["auction"] == 3          # 170일 창 → 3회
    assert est["total_windows"] == 368


def test_증분은_최근만_본다(monkeypatch):
    seen = []
    monkeypatch.setattr(OI, "ingest_window",
                        lambda m, s, e, session=None, include_settlement=True:
                        seen.append((s, e)) or {"fetched": 0})
    OI.ingest_recent(["coupang"], days=3)
    assert len(seen) == 1
    assert (seen[0][1] - seen[0][0]).days <= 3


# ── 백필 속도 대책 ─────────────────────────────────────────────
def test_백필은_마켓을_순차로_돈다(monkeypatch):
    """2026-07-20 라이브 장애: 마켓 4개를 동시에 돌렸더니 웹 프로세스 자원을 다 먹어
    앱이 502 로 죽었다. 백필을 빨리 하자고 서비스를 멈출 수는 없다."""
    import threading
    import time
    active, peak, lock = [0], [0], threading.Lock()

    def slow(market, start, end, session=None, include_settlement=True):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        with lock:
            active[0] -= 1
        return {"fetched": 0}

    monkeypatch.setattr(OI, "ingest_window", slow)
    OI.backfill(["coupang", "gmarket", "auction"], days=30)
    assert peak[0] == 1, "마켓이 동시에 돌면 웹 프로세스가 죽는다"


def test_백필은_정산조회를_끈다(monkeypatch):
    """정산이 창마다 붙어 가장 느리다. 과거 정산은 나중에 따로 채운다."""
    seen = []
    monkeypatch.setattr(OI, "ingest_window",
                        lambda m, s, e, session=None, include_settlement=True:
                        seen.append(include_settlement) or {"fetched": 0})
    OI.backfill(["coupang"], days=30)
    assert seen and all(v is False for v in seen)


def test_증분은_정산을_켠다(monkeypatch):
    """최근 주문은 정산까지 최신이어야 한다."""
    seen = []
    monkeypatch.setattr(OI, "ingest_window",
                        lambda m, s, e, session=None, include_settlement=True:
                        seen.append(include_settlement) or {"fetched": 0})
    OI.ingest_recent(["coupang"], days=3)
    assert seen and all(v is True for v in seen)


def test_규모_예측은_백필_청크로_센다():
    """증분 청크로 세면 실제 계획과 어긋나 진행률이 영영 100%가 안 된다
    (롯데온: 증분 1일=365창 vs 백필 29일=13창)."""
    est = OI.estimate(["lotteon"], days=365)
    assert est["per_market"]["lotteon"] == 13
    assert OI.estimate(["lotteon"], days=365, backfill=False)["per_market"]["lotteon"] == 365
