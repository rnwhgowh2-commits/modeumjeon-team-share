"""백필 실행기 — 라이브 장애 2건에서 배운 계약.

  ① 긴 작업이 gunicorn 워커에서 돌면 워커가 점유돼 **앱이 502** 가 되고,
     워커 재활용(`--timeout 60`·`--max-requests`) 때 작업이 통째로 죽는다.
     → 웹은 요청만 남기고, 실행은 스케줄러(마스터)가 가져간다.
  ② 중단되면 처음부터 다시 하면 안 된다 → cursor 부터 이어서 한다.
  ③ 마켓 호출이 타임아웃 없이 매달리면 백필 전체가 멈춘다 → 창별 시간 상한.
"""
from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.markets import backfill_runner as BR
from lemouton.markets import order_ingest as OI


def _wins(market, days):
    """그 마켓의 백필 창 개수(청크 크기가 바뀌어도 테스트가 안 깨지게)."""
    return -(-days // OI.backfill_chunk_days(market))


@pytest.fixture
def db(monkeypatch):
    from shared.db import Base
    import lemouton.markets.models_orders  # noqa: F401
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[Base.metadata.tables["order_ingest_runs"]])
    Maker = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(BR, "_session", Maker)
    return Maker


# ── 요청/실행 분리 ─────────────────────────────────────────────
def test_요청은_즉시_돌아온다(db, monkeypatch):
    """웹 워커에서 긴 작업을 하지 않는다 — 플래그만 적는다."""
    called = []
    monkeypatch.setattr(BR, "ingest_window", lambda *a, **k: called.append(1))
    BR.request_backfill(["coupang"], 365)
    assert called == [], "요청 단계에서 마켓을 때리면 안 된다"
    st = BR.status()
    assert st["requested"] is True and st["total"] > 0


def test_요청이_없으면_틱은_아무것도_안_한다(db, monkeypatch):
    called = []
    monkeypatch.setattr(BR, "ingest_window", lambda *a, **k: called.append(1))
    BR.run_if_requested()
    assert called == []


def test_요청이_있으면_틱이_실행한다(db, monkeypatch):
    calls = []
    monkeypatch.setattr(BR, "ingest_window",
                        lambda m, s, e, **k: calls.append(m) or {"fetched": 0})
    BR.request_backfill(["coupang"], 60)
    BR.run_if_requested()
    assert len(calls) == _wins("coupang", 60)
    st = BR.status()
    assert st["done"] == _wins("coupang", 60)
    assert st["requested"] is False and st["finished_at"]


# ── 중단 후 이어하기 ───────────────────────────────────────────
def test_예산이_끝나면_다음_틱이_이어받는다(db, monkeypatch):
    calls = []

    def fake(m, s, e, **k):
        calls.append((s, e))
        return {"fetched": 0}

    monkeypatch.setattr(BR, "ingest_window", fake)
    monkeypatch.setattr(BR, "TICK_BUDGET_SEC", -1)   # 즉시 예산 소진
    BR.request_backfill(["coupang"], 90)
    BR.run_if_requested()
    assert len(calls) <= 1, "예산을 넘겨 계속 돌면 안 된다"
    assert BR.status()["requested"] is True, "안 끝났으면 요청이 남아 있어야 한다"

    monkeypatch.setattr(BR, "TICK_BUDGET_SEC", 600)
    BR.run_if_requested()
    assert BR.status()["done"] == _wins("coupang", 90)
    assert BR.status()["requested"] is False


def test_이어할_때_앞_구간을_다시_안_돈다(db, monkeypatch):
    seen = []
    monkeypatch.setattr(BR, "ingest_window",
                        lambda m, s, e, **k: seen.append(s) or {"fetched": 0})
    monkeypatch.setattr(BR, "TICK_BUDGET_SEC", -1)
    BR.request_backfill(["coupang"], 90)
    BR.run_if_requested()
    first = list(seen)
    monkeypatch.setattr(BR, "TICK_BUDGET_SEC", 600)
    BR.run_if_requested()
    assert len(set(seen)) == len(seen), f"같은 구간을 다시 돌았다: {first}"


# ── 매달림 방지 ────────────────────────────────────────────────
def test_창이_시간을_넘기면_건너뛴다(db, monkeypatch):
    import time
    monkeypatch.setattr(BR, "WINDOW_TIMEOUT_BY_MARKET", {})
    monkeypatch.setattr(BR, "WINDOW_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(BR, "ingest_window", lambda *a, **k: time.sleep(3))
    BR.request_backfill(["coupang"], 30)             # 1창
    BR.run_if_requested()
    st = BR.status()
    assert any("초과" in e for e in st["recent_errors"]), st


def test_연속_타임아웃이_이어지면_그_마켓을_포기한다(db, monkeypatch):
    """버려진 스레드가 쌓이면 그게 또 자원을 먹는다 — 마켓이 죽었으면 그만 두드린다.
    단 **그 마켓만** 포기한다(전체를 멈추면 뒤 마켓 차례가 영영 안 온다)."""
    import time
    calls = []
    monkeypatch.setattr(BR, "WINDOW_TIMEOUT_BY_MARKET", {})
    monkeypatch.setattr(BR, "WINDOW_TIMEOUT_SEC", 0.02)
    monkeypatch.setattr(BR, "MAX_TIMEOUTS", 2)
    monkeypatch.setattr(BR, "ingest_window",
                        lambda m, s, e, **k: calls.append(m) or time.sleep(3))
    BR.request_backfill(["coupang"], 365)
    BR.run_if_requested()
    assert len(calls) <= 3, "연속 타임아웃인데 계속 두드렸다"
    assert any("마켓 남은 구간 건너뜀" in e for e in BR.status()["recent_errors"])


def test_한_창이_실패해도_나머지는_계속한다(db, monkeypatch):
    n = {"i": 0}

    def flaky(m, s, e, **k):
        n["i"] += 1
        if n["i"] == 1:
            raise RuntimeError("429")
        return {"fetched": 0}

    monkeypatch.setattr(BR, "ingest_window", flaky)
    BR.request_backfill(["coupang"], 90)
    BR.run_if_requested()
    st = BR.status()
    assert st["done"] == _wins("coupang", 90)
    assert any("429" in e for e in st["recent_errors"])


# ── 중단 ──────────────────────────────────────────────────────
def test_취소하면_다음_틱이_안_돈다(db, monkeypatch):
    calls = []
    monkeypatch.setattr(BR, "ingest_window", lambda *a, **k: calls.append(1))
    BR.request_backfill(["coupang"], 365)
    BR.cancel()
    BR.run_if_requested()
    assert calls == [] and BR.status()["requested"] is False


# ── 계획 ──────────────────────────────────────────────────────
def test_마켓별_청크로_계획을_세운다(db):
    plan = BR._plan(["coupang", "smartstore"], 60)
    assert sum(1 for m, *_ in plan if m == "coupang") >= _wins("coupang", 60)
    assert sum(1 for m, *_ in plan if m == "smartstore") >= 60  # 1일 청크 × 계정수


def test_에러는_최근_30건만_보관한다(db, monkeypatch):
    """행이 비대해지면 상태 조회 자체가 느려진다."""
    monkeypatch.setattr(BR, "ingest_window",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    BR.request_backfill(["smartstore"], 40)
    BR.run_if_requested()
    assert len(BR.status()["recent_errors"]) <= 30


def test_타임아웃이_실제로_기다리지_않는다(db, monkeypatch):
    """🔴 라이브 버그: `with ThreadPoolExecutor` 는 빠져나갈 때 shutdown(wait=True)
    가 불려 매달린 작업이 끝날 때까지 블록된다 — 타임아웃을 걸어놓고도 무한정 기다린다.
    (백필이 15/796 에서 running=True 인 채 멈춘 원인.)
    여기서는 '타임아웃 시각에 실제로 돌아오는가'를 시간으로 잰다."""
    import time
    monkeypatch.setattr(BR, "WINDOW_TIMEOUT_BY_MARKET", {})
    monkeypatch.setattr(BR, "WINDOW_TIMEOUT_SEC", 0.2)
    monkeypatch.setattr(BR, "MAX_TIMEOUTS", 1)
    monkeypatch.setattr(BR, "ingest_window", lambda *a, **k: time.sleep(10))
    BR.request_backfill(["coupang"], 30)
    t0 = time.monotonic()
    BR.run_if_requested()
    elapsed = time.monotonic() - t0
    assert elapsed < 5, f"타임아웃 후에도 {elapsed:.1f}초 기다렸다 — shutdown 이 블록한다"


def test_마켓_자체_429가_있는_마켓은_창_사이에_쉰다(db):
    """스스·11번가는 마켓 자체 rate limit(429)이 있어 연달아 때리면 클라이언트가
    호출 간격을 늘려 뒤로 갈수록 느려진다 — 서버 사양과 무관한 마켓 측 제약이다.
    (다른 마켓·기본값은 서버 여유에 따라 조정 가능 — 여기서 하한을 강제하지 않는다.)"""
    assert BR.PACE_SEC.get("smartstore", 0) >= 1.0
    assert BR.PACE_SEC.get("eleven11", 0) >= 1.0


def test_틱은_너무_길게_붙잡지_않는다(db):
    """길게 붙잡을수록 웹 요청과 코어를 오래 다툰다."""
    assert BR.TICK_BUDGET_SEC <= 360


def test_커넥션풀을_프로세스당_한번만_재생성한다(db, monkeypatch):
    """gunicorn --preload 는 마스터에서 커넥션을 연 뒤 fork 한다 → 마스터와 워커가
    같은 소켓을 나눠 써 매달린다. 스케줄러 스레드는 상속분을 버리고 자기 걸 열어야 한다.
    단 매 틱마다 버리면 커넥션을 계속 새로 여는 낭비가 된다."""
    calls = []
    monkeypatch.setattr(BR, "_pool_reset_done", False)
    import shared.db as _db
    monkeypatch.setattr(_db.engine, "dispose", lambda *a, **k: calls.append(1))
    BR._reset_pool_once()
    BR._reset_pool_once()
    assert calls == [1]


def test_창_타임아웃은_실측보다_넉넉해야_한다(db):
    """건너뛴 창은 그 기간이 통째로 빈다 — '조용한 구멍'이다.
    실측(쿠팡 30일 창 75초)에 여유가 없으면 실제로 건너뛰어진다(라이브에서 겪음)."""
    assert BR.WINDOW_TIMEOUT_BY_MARKET["coupang"] >= 150   # 실측 75초의 2배 이상
    assert BR.WINDOW_TIMEOUT_BY_MARKET["lotteon"] >= 150   # 29일 창 페이징


def test_한_마켓이_막혀도_다른_마켓은_계속한다(db, monkeypatch):
    """🔴 라이브: 쿠팡이 연속 타임아웃으로 전체 실행을 멈춰 스마트스토어 차례가
    영영 안 왔다(스스 36일치만 쌓임). 막힌 마켓만 포기하고 다음으로 가야 한다."""
    import time
    seen = []

    def fn(market, start, end, **k):
        seen.append(market)
        if market == "coupang":
            time.sleep(5)          # 항상 타임아웃
        return {"fetched": 0}

    monkeypatch.setattr(BR, "WINDOW_TIMEOUT_BY_MARKET", {})
    monkeypatch.setattr(BR, "WINDOW_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(BR, "MAX_TIMEOUTS", 2)
    monkeypatch.setattr(BR, "ingest_window", fn)
    BR.request_backfill(["coupang", "gmarket"], 60)
    BR.run_if_requested()
    assert "gmarket" in seen, "앞 마켓이 막혀 뒤 마켓이 아예 안 돌았다"
    st = BR.status()
    assert st["requested"] is False, "막힌 마켓은 건너뛰고 끝까지 갔어야 한다"
    assert any("마켓 남은 구간 건너뜀" in e for e in st["recent_errors"])


def test_건너뜀_메시지가_실제_적용된_상한을_말한다(db, monkeypatch):
    """기본 상수(90초)를 찍으면 300초로 올려놓고도 90초라 적혀 원인을 오판한다."""
    import time
    monkeypatch.setattr(BR, "WINDOW_TIMEOUT_BY_MARKET", {"coupang": 0.05})
    monkeypatch.setattr(BR, "WINDOW_TIMEOUT_SEC", 999)
    monkeypatch.setattr(BR, "MAX_TIMEOUTS", 99)
    monkeypatch.setattr(BR, "ingest_window", lambda *a, **k: time.sleep(5))
    BR.request_backfill(["coupang"], 20)
    BR.run_if_requested()
    assert any("0.05초 초과" in e for e in BR.status()["recent_errors"])


def test_쿠팡_백필_창은_상한보다_작게_잡는다():
    """상한(31일)에 붙이면 과거 구간처럼 주문 많은 창이 타임아웃으로 통째 사라진다."""
    from lemouton.markets import order_ingest as OI
    assert OI.backfill_chunk_days("coupang") <= 20


def test_킬스위치가_켜지면_요청이_있어도_안_돈다(db, monkeypatch):
    """🔴 1코어 서버가 백필로 522 에 빠지면 API 취소도 안 된다(원단 응답불가).
    재배포 시 env 로 끄면 요청이 DB 에 남아 있어도 실행하지 않아 악순환이 끊긴다."""
    calls = []
    monkeypatch.setenv("MOUM_BACKFILL_OFF", "1")
    monkeypatch.setattr(BR, "ingest_window", lambda *a, **k: calls.append(1))
    BR.request_backfill(["coupang"], 60)
    BR.run_if_requested()
    assert calls == [], "킬스위치가 켜졌는데 백필이 돌았다"
    assert BR.status()["requested"] is True, "요청 자체는 DB 에 남아 있어야 한다(끄기만)"


def test_킬스위치가_꺼지면_정상_동작한다(db, monkeypatch):
    monkeypatch.delenv("MOUM_BACKFILL_OFF", raising=False)
    calls = []
    monkeypatch.setattr(BR, "ingest_window",
                        lambda m, s, e, **k: calls.append(m) or {"fetched": 0})
    BR.request_backfill(["coupang"], 30)
    BR.run_if_requested()
    assert calls, "킬스위치가 꺼졌는데 백필이 안 돌았다"


def test_stale_cursor는_0부터_다시_시작한다(db, monkeypatch):
    """🔴 취소→재요청이 이전 틱과 겹치면(race) 옛 cursor 가 새 요청의 cursor=0 을
    덮어써, 계획보다 큰 cursor 가 남아 range(cursor, len)=빈 루프가 된다.
    실측: 3개 마켓 93창인데 cursor=217 이 남아 아무것도 안 돌았다."""
    calls = []
    monkeypatch.setattr(BR, "ingest_window",
                        lambda m, s, e, **k: calls.append(m) or {"fetched": 0})
    BR.request_backfill(["coupang"], 60)          # 작은 계획
    # 이전의 큰 계획에서 남은 stale cursor 를 흉내낸다
    s = BR._session()
    r = BR._get(s); r.cursor = "999"; s.commit(); s.close()
    BR.run_if_requested()
    assert calls, "stale cursor 때문에 아무것도 안 돌았다"
    assert BR.status()["requested"] is False       # 끝까지 감


def test_cursor_리셋시_옛_에러를_비운다(db, monkeypatch):
    """다른 마켓의 옛 스킵 에러가 남아 새 실행을 오진하게 하면 안 된다."""
    monkeypatch.setattr(BR, "ingest_window", lambda *a, **k: {"fetched": 0})
    BR.request_backfill(["coupang"], 30)
    s = BR._session()
    r = BR._get(s); r.cursor = "999"; r.result = ["[smartstore] 옛 스킵"]; s.commit(); s.close()
    BR.run_if_requested()
    assert not any("옛 스킵" in str(e) for e in BR.status()["recent_errors"])


def test_워커_경로는_pool을_리셋하지_않는다(db, monkeypatch):
    """워커의 DB 연결은 정상이라 dispose 가 불필요하고, 오히려 워커 커넥션을 끊는다.
    (마스터 경로만 fork 상속분을 버린다.)"""
    calls = []
    monkeypatch.setattr(BR, "_reset_pool_once", lambda: calls.append(1))
    monkeypatch.setattr(BR, "ingest_window", lambda *a, **k: {"fetched": 0})
    BR.request_backfill(["coupang"], 30)
    BR.run_if_requested(budget=5, in_worker=True)
    assert calls == [], "워커 경로에서 pool 을 리셋했다"


def test_워커_경로는_상태를_돌려준다(db, monkeypatch):
    monkeypatch.setattr(BR, "ingest_window", lambda *a, **k: {"fetched": 0})
    BR.request_backfill(["coupang"], 30)
    res = BR.run_if_requested(budget=5, in_worker=True)
    assert isinstance(res, dict) and "done" in res


def test_짧은_예산이_적용된다(db, monkeypatch):
    """워커는 gunicorn 60초 타임아웃 아래여야 한다."""
    import time
    n = []
    monkeypatch.setattr(BR, "ingest_window",
                        lambda *a, **k: n.append(1) or time.sleep(0.3) or {"fetched": 0})
    BR.request_backfill(["coupang"], 365)     # 많은 창
    BR.run_if_requested(budget=1, in_worker=True)   # 1초 예산
    assert BR.status()["requested"] is True, "1초 예산인데 다 끝냈다"
    assert len(n) < 20, "예산을 안 지켰다"


# ── 계정별 백필 (2026-07-22 샵마인 대사: 누락 605건 최대 원인) ─────────────
def test_계정이_여러개면_계정별로_창을_쪼갠다(db, monkeypatch):
    """백필이 대표계정 1개만 돌아 나머지 계정의 과거 주문이 통째 빠졌다.
    계획은 (마켓×계정×창)으로 선다 — 창 하나의 소요시간은 그대로(타임아웃 불변)."""
    monkeypatch.setattr(BR, "_accounts_for_plan",
                        lambda m: [("P1", "가게1"), ("P2", "가게2")])
    plan = BR._plan(["coupang"], 60)
    assert len(plan) == _wins("coupang", 60) * 2
    mk, prefix, alias, s, e = plan[0]
    assert mk == "coupang" and prefix in ("P1", "P2")


def test_창_실행에_계정이_전달된다(db, monkeypatch):
    got = []
    monkeypatch.setattr(BR, "_accounts_for_plan", lambda m: [("P1", "가게1")])
    monkeypatch.setattr(BR, "ingest_window",
                        lambda m, s, e, **k: got.append((k.get("prefix"), k.get("alias")))
                        or {"fetched": 0})
    BR.request_backfill(["coupang"], 30)
    BR.run_if_requested()
    assert got and all(p == ("P1", "가게1") for p in got)


def test_계정조회가_실패해도_계획은_선다(db, monkeypatch):
    """계정 테이블이 없거나 조회가 죽으면 예전처럼 대표계정 1개로 폴백(백필 불능 방지)."""
    def boom(m):
        raise RuntimeError("no table")
    import lemouton.markets.order_export as OE
    monkeypatch.setattr(OE, "_active_accounts", boom)
    plan = BR._plan(["coupang"], 60)
    assert len(plan) == _wins("coupang", 60)
    assert plan[0][1] is None                      # prefix 폴백
