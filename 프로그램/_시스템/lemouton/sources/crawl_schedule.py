"""연속 배수 큐 — '지금 크롤할 URL'을 오래된 순 + 계수로 선정 (두뇌).

유효 간격 = 기준주기 ÷ 계수 × 완화배수.
- 계수(crawl_weight) 1~5: 클수록 자주(간격 나눔).
- 완화배수 = min(1 + 무변동연속 × RELAX_STEP, RELAX_CAP): 계속 안 변하면 덜 긁음.
실제 크롤 실행은 P3(워커). 여기는 순서만 정한다.
"""
from datetime import datetime, timezone

RELAX_STEP = 0.5   # 무변동 1회당 간격 +0.5배
RELAX_CAP = 4.0    # 완화 상한(최대 4배)


def _as_naive_utc(dt: datetime | None) -> datetime | None:
    """aware→naive-UTC, naive는 그대로. SQLite naive/aware 섞임 방지."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def effective_interval_seconds(base_interval_seconds: float,
                               crawl_weight, no_change_streak) -> float:
    weight = max(1, int(crawl_weight or 1))
    streak = max(0, int(no_change_streak or 0))
    base = base_interval_seconds / weight
    relax = min(1.0 + streak * RELAX_STEP, RELAX_CAP)
    return base * relax


def overdue_seconds(now: datetime, last_fetched_at,
                    base_interval_seconds: float,
                    crawl_weight, no_change_streak) -> float:
    """연체 초. 클수록 더 오래 밀림. 한 번도 안 긁음 = 무한대(최우선)."""
    if last_fetched_at is None:
        return float("inf")
    n = _as_naive_utc(now)
    lf = _as_naive_utc(last_fetched_at)
    age = (n - lf).total_seconds()
    return age - effective_interval_seconds(base_interval_seconds,
                                            crawl_weight, no_change_streak)


def is_due(now, last_fetched_at, base_interval_seconds,
           crawl_weight, no_change_streak) -> bool:
    return overdue_seconds(now, last_fetched_at, base_interval_seconds,
                           crawl_weight, no_change_streak) >= 0
