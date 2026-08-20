# -*- coding: utf-8 -*-
"""[TEST] 회차(CrawlLapRun) 중복 전수 감사·청소.

진짜 한 바퀴는 수 분 간격인데, 신고자 중복으로 같은 바퀴가 0~수십 초 간격의
클러스터(쌍·삼중…)로 여러 행 박혔다. audit/dedupe 가 연속 간격 window 이하를
같은 바퀴로 묶어 첫 행만 남기고 전수 제거하는지 검증.
"""
from datetime import datetime, timedelta
import pytest

from lemouton.sources.crawl_schedule import audit_lap_runs, dedupe_lap_runs
from lemouton.sources.models import CrawlLapRun

BASE = datetime(2026, 7, 8, 0, 0, 0)


def _seed(db, offsets_seconds):
    for off in offsets_seconds:
        db.add(CrawlLapRun(completed_at=BASE + timedelta(seconds=off)))
    db.flush()


def test_audit_counts_clusters_pairs_and_triples(db):
    # 진짜 바퀴 3개(0s / 600s / 1200s) + 중복: 쌍(0.12s) · 삼중(0.05s,20.1s)
    _seed(db, [0, 0.12, 600, 600.05, 620.1, 1200])
    a = audit_lap_runs(db, window_seconds=90)
    assert a["total"] == 6
    assert a["real_laps"] == 3          # 진짜 바퀴 3
    assert a["duplicates"] == 3         # 삭제 대상 3
    assert a["max_cluster"] == 3        # 가장 큰 클러스터(600s 묶음)=3


def test_dedupe_keeps_one_per_cluster(db):
    _seed(db, [0, 0.12, 600, 600.05, 620.1, 1200])
    dedupe_lap_runs(db, window_seconds=90)
    db.commit()
    remaining = sorted(
        (r.completed_at - BASE).total_seconds() for r in db.query(CrawlLapRun).all()
    )
    assert db.query(CrawlLapRun).count() == 3
    assert remaining == [0, 600, 1200]   # 각 클러스터 첫 행만 남음


def test_dedupe_is_idempotent(db):
    _seed(db, [0, 0.1, 600, 1200, 1200.03])
    dedupe_lap_runs(db, window_seconds=90); db.commit()
    first = db.query(CrawlLapRun).count()
    a2 = dedupe_lap_runs(db, window_seconds=90); db.commit()
    assert a2["duplicates"] == 0          # 두 번째엔 중복 없음
    assert db.query(CrawlLapRun).count() == first


def test_no_false_merge_of_real_laps(db):
    # 전부 진짜 바퀴(수 분 간격) → 아무것도 안 지움
    _seed(db, [0, 480, 960, 1500])
    a = audit_lap_runs(db, window_seconds=90)
    assert a["duplicates"] == 0
    assert a["real_laps"] == 4


def test_empty(db):
    a = audit_lap_runs(db, window_seconds=90)
    assert a == {"total": 0, "real_laps": 0, "duplicates": 0, "max_cluster": 0,
                 "dup_ids": [], "window_seconds": 90}
