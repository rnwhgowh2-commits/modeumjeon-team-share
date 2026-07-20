# -*- coding: utf-8 -*-
"""[TEST] 업로드 속도 정본 = 계정(API) 단위.

P4(마켓 per_minute)를 폐기하고, 계정별 seconds_per_item 정본에서 파생한
마켓별 '1개당 최소 초 간격'을 실제 전송 루프(run_uploader)가 적용하는지 검증.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
# create_all 은 전체 FK 그래프가 등록돼야 성공 — 앱 부트와 동일한 모델 세트 등록.
import lemouton.sourcing.models  # noqa: F401
import lemouton.sourcing.models_pricing  # noqa: F401
import lemouton.sourcing.models_v2  # noqa: F401
import lemouton.uploader.models  # noqa: F401
import lemouton.templates.models  # noqa: F401
import lemouton.inventory.models  # noqa: F401
import lemouton.sets.models  # noqa: F401
import lemouton.sources.models  # noqa: F401
import lemouton.multitenancy.models  # noqa: F401  (market_accounts 등록)
import lemouton.audit.models  # noqa: F401
import lemouton.mapping.models  # noqa: F401
from lemouton.sourcing.models_v2 import UploadAccount
from lemouton.pricing.settings import AccountUploadPolicy  # noqa: F401
from lemouton.uploader.throttle import (
    market_min_interval_seconds, IntervalPacer, build_market_pacer,
)
from lemouton.uploader.orchestrator import run_uploader
from lemouton.uploader.adapters.base import MarketAdapter, UploadResult


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


class _FakeClock:
    """sleep 이 시각을 전진시키는 결정론적 시계 (실제 대기 없음)."""
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, sec):
        self.slept.append(sec)
        self.t += sec

    def advance(self, sec):
        self.t += sec


def _acc(db, market, name, sec, enabled=True):
    a = UploadAccount(account_key=f"{market}_{name}", display_name=name,
                      market=market, env_prefix=f"{market}_{name}".upper(),
                      is_active=True)
    db.add(a); db.flush()
    db.add(AccountUploadPolicy(account_id=a.id, seconds_per_item=sec, enabled=enabled))
    db.flush()
    return a


# ── 파생: 마켓별 '1개당 최소 초 간격' = 3600 / 총 스토어 업로드수 ──────────────

def test_min_interval_derives_from_enabled_accounts(db):
    # smartstore 2계정 @ 6초 → per_hour 600+600=1200 → 간격 3600/1200 = 3.0
    _acc(db, "smartstore", "본계정", 6)
    _acc(db, "smartstore", "세컨", 6)
    assert market_min_interval_seconds(db, "smartstore") == 3.0
    # 계정 없는 마켓 → 무대기(0.0). 함부로 막지 않음.
    assert market_min_interval_seconds(db, "coupang") == 0.0


def test_more_accounts_shrink_interval(db):
    # 계정 1개(6초) → 간격 6.0
    _acc(db, "coupang", "a", 6)
    assert market_min_interval_seconds(db, "coupang") == 6.0
    # 계정 추가(6초) → 처리량 2배 → 간격 절반 3.0
    _acc(db, "coupang", "b", 6)
    assert market_min_interval_seconds(db, "coupang") == 3.0


def test_disabled_account_excluded_from_interval(db):
    _acc(db, "smartstore", "켜짐", 6)
    _acc(db, "smartstore", "꺼짐", 6, enabled=False)
    # 꺼진 계정 제외 → 켜진 1개(600/h) → 간격 6.0
    assert market_min_interval_seconds(db, "smartstore") == 6.0


# ── IntervalPacer: 같은 마켓 연속 전송 사이 최소 간격 강제 ────────────────────

def test_pacer_first_send_no_wait():
    clk = _FakeClock()
    pacer = IntervalPacer({"smartstore": 2.0}, sleep_fn=clk.sleep, now_fn=clk.now)
    assert pacer.wait("smartstore") == 0.0
    assert clk.slept == []


def test_pacer_waits_min_interval_between_consecutive():
    clk = _FakeClock()
    pacer = IntervalPacer({"smartstore": 2.0}, sleep_fn=clk.sleep, now_fn=clk.now)
    pacer.wait("smartstore")                 # 첫 전송 (t=0)
    assert pacer.wait("smartstore") == 2.0   # 즉시 다음 → 2초 대기
    assert clk.slept == [2.0]
    clk.advance(5.0)                          # 충분히 흐름
    assert pacer.wait("smartstore") == 0.0   # 간격 충족 → 무대기


def test_pacer_zero_interval_never_waits():
    clk = _FakeClock()
    pacer = IntervalPacer({"coupang": 0.0}, sleep_fn=clk.sleep, now_fn=clk.now)
    assert pacer.wait("coupang") == 0.0
    assert pacer.wait("coupang") == 0.0
    assert clk.slept == []


def test_pacer_tracks_markets_independently():
    clk = _FakeClock()
    pacer = IntervalPacer({"smartstore": 2.0, "coupang": 2.0},
                          sleep_fn=clk.sleep, now_fn=clk.now)
    assert pacer.wait("smartstore") == 0.0
    assert pacer.wait("coupang") == 0.0      # 다른 마켓 첫 전송 → 무대기
    assert clk.slept == []


def test_build_market_pacer_reads_account_policies(db):
    _acc(db, "smartstore", "본계정", 6)
    _acc(db, "smartstore", "세컨", 6)
    clk = _FakeClock()
    pacer = build_market_pacer(db, sleep_fn=clk.sleep, now_fn=clk.now)
    pacer.wait("smartstore")                 # 첫 전송
    assert pacer.wait("smartstore") == 3.0   # 파생 간격 3.0 적용


# ── 배선: run_uploader 가 전송마다 pacer.wait(market) 호출 ────────────────────

class _OkAdapter(MarketAdapter):
    def __init__(self, market):
        self.market_name = market

    def update_price_and_stock(self, *, canonical_sku, **_):
        return UploadResult(market=self.market_name, canonical_sku=canonical_sku,
                            success=True, http_status=200)


class _RecordingPacer:
    def __init__(self):
        self.calls = []

    def wait(self, market):
        self.calls.append(market)
        return 0.0


def _cout_two_markets():
    return {
        "smartstore": {"M1": {
            "product_id": 111, "base_price": 10000,
            "options": [{"option_id": 555, "add_price": 0, "stock": 5}],
        }},
        "coupang": {"M2": {
            "product_id": 222,
            "options": [{"option_id": 777, "price": 20000, "stock": 3}],
        }},
        "alerts": [],
    }


_SKU = {("smartstore", 555): "SKU-A", ("coupang", 777): "SKU-B"}


def test_run_uploader_paces_every_send(db, tmp_path):
    pacer = _RecordingPacer()
    r = run_uploader(db, _cout_two_markets(), sku_by_option=_SKU,
                     adapters={"smartstore": _OkAdapter("smartstore"),
                               "coupang": _OkAdapter("coupang")},
                     dlq_path=str(tmp_path / "dlq.jsonl"), pacer=pacer)
    assert r["uploaded"] == 2
    # 전송된 각 옵션마다 그 마켓으로 pacer.wait 1회
    assert sorted(pacer.calls) == ["coupang", "smartstore"]


def test_run_uploader_without_pacer_still_works(db, tmp_path):
    # pacer 미주입(기본 None) → 현행 동작 그대로
    r = run_uploader(db, _cout_two_markets(), sku_by_option=_SKU,
                     adapters={"smartstore": _OkAdapter("smartstore"),
                               "coupang": _OkAdapter("coupang")},
                     dlq_path=str(tmp_path / "dlq.jsonl"))
    assert r["uploaded"] == 2
