# -*- coding: utf-8 -*-
"""[TEST] #12 — 업로더가 라이브 전송 시 MarketRegistration 기준선을 영속(commit)해야
변동감지(detect_change)가 다음 사이클에 중복 전송을 건너뛴다.

근본 원인: run_uploader/jobs.py 어디에도 session.commit() 이 없고 SessionLocal 은
autocommit=False → 등록이 롤백 → detect_change 가 매번 '이전 없음'=변동으로 판정 →
라이브에서 안 바뀐 옵션도 매 사이클 재전송(레이트리밋·중복 PUT).

수정: run_uploader(persist=True) 시 종료 후 commit. dry-run(persist=False)은 커밋 안 함
(현행 동작 보존 + 미전송분이 '전송됨'으로 오염되는 것 방지).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models", "lemouton.sets.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

from lemouton.uploader.orchestrator import run_uploader
from lemouton.uploader.adapters.smartstore import MockSmartStoreAdapter
from lemouton.uploader.adapters.base import MarketAdapter, UploadResult


class _NoopCoupang(MarketAdapter):
    market_name = "coupang"

    def update_price_and_stock(self, *, canonical_sku, **_):
        return UploadResult(market="coupang", canonical_sku=canonical_sku,
                            success=True, http_status=200)


def _cout():
    return {
        "smartstore": {"M1": {
            "product_id": 111, "base_price": 10000,
            "options": [{"option_id": 555, "add_price": 0, "stock": 5}],
        }},
        "coupang": {}, "alerts": [],
    }


SKU = {("smartstore", 555): "SKU-A"}


@pytest.fixture
def eng():
    e = create_engine("sqlite://")
    Base.metadata.create_all(e)
    return e


def _run(eng, dlq, persist):
    s = Session(eng)
    try:
        return run_uploader(s, _cout(), sku_by_option=SKU,
                            adapters={"smartstore": MockSmartStoreAdapter(),
                                      "coupang": _NoopCoupang()},
                            dlq_path=dlq, persist=persist)
    finally:
        s.close()


def test_persist_true_enables_dedup(eng, tmp_path):
    dlq = str(tmp_path / "dlq.jsonl")
    r1 = _run(eng, dlq, persist=True)
    assert r1["uploaded"] == 1, "첫 전송은 1건"
    r2 = _run(eng, dlq, persist=True)
    assert r2["uploaded"] == 0, "기준선 커밋됨 → 안 바뀐 옵션 재전송 안 함"
    assert r2["skipped"] == 1


def test_persist_false_is_ephemeral(eng, tmp_path):
    """dry-run 기본: 커밋 안 함 → 기준선 안 남음(현행 동작 보존)."""
    dlq = str(tmp_path / "dlq.jsonl")
    r1 = _run(eng, dlq, persist=False)
    assert r1["uploaded"] == 1
    r2 = _run(eng, dlq, persist=False)
    assert r2["uploaded"] == 1, "커밋 안 됐으니 다음 사이클도 전송(dry-run 현행)"
