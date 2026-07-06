"""자정 이후 '오늘 몇 바퀴' + 평균 1바퀴 시간 (항목 4).

랩이 완료될 때마다 CrawlLapRun 1행 기록 → 자정(KST) 이후 개수 = 오늘 바퀴,
연속 완료 간격 = 1바퀴 걸린 시간. 링 박스가 이 값을 읽어 표시.
"""
from datetime import datetime, timedelta

from lemouton.sources.crawl_schedule import start_new_lap, lap_stats
from lemouton.sources.models import SourceProduct, CrawlLapRun


def _sp(db):
    sp = SourceProduct(site="s1", url="u/a", last_fetched_at=None)
    db.add(sp); db.flush()
    return sp


def test_start_new_lap_records_completion(db):
    _sp(db)
    t = datetime(2026, 7, 6, 3, 0, 0)
    start_new_lap(db, now=t)
    runs = db.query(CrawlLapRun).all()
    assert len(runs) == 1
    assert runs[0].completed_at == t


def test_lap_stats_counts_today_by_kst_midnight(db):
    # now = 2026-07-06 05:00 UTC = 14:00 KST(6일). KST 자정(6일 00:00)=2026-07-05 15:00 UTC.
    now = datetime(2026, 7, 6, 5, 0, 0)
    for h in (16, 18, 20):                       # 5일 16~20 UTC = 6일 01~05 KST → 오늘
        db.add(CrawlLapRun(completed_at=datetime(2026, 7, 5, h, 0, 0)))
    for h in (10, 12):                           # 5일 10,12 UTC = 5일 19,21 KST → 어제
        db.add(CrawlLapRun(completed_at=datetime(2026, 7, 5, h, 0, 0)))
    db.flush()
    st = lap_stats(db, now=now)
    assert st["laps_today"] == 3
    assert st["current_lap_no"] == 4             # 지금은 4바퀴째


def test_lap_stats_avg_and_recent_durations(db):
    now = datetime(2026, 7, 6, 5, 0, 0)
    base = datetime(2026, 7, 5, 15, 0, 0)        # 6일 00:00 KST
    for m in (0, 30, 70, 130):                   # 간격 30·40·60분
        db.add(CrawlLapRun(completed_at=base + timedelta(minutes=m)))
    db.flush()
    st = lap_stats(db, now=now)
    assert st["laps_today"] == 4
    assert st["recent_lap_minutes"][-3:] == [30, 40, 60]
    assert st["avg_lap_minutes"] == 43           # (30+40+60)/3 = 43.33 → 43


def test_lap_stats_empty_when_no_runs(db):
    now = datetime(2026, 7, 6, 5, 0, 0)
    st = lap_stats(db, now=now)
    assert st["laps_today"] == 0
    assert st["current_lap_no"] == 1
    assert st["avg_lap_minutes"] is None
    assert st["recent_lap_minutes"] == []
