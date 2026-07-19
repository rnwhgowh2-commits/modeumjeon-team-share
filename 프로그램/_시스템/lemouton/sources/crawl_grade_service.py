"""구성별 등급 서비스 — 「하루에 몇 번 긁나」를 재고, 그 위에 등급을 얹는다.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §6
대량등록 ① 데이터수집 탭이 읽는다.

━━ 왜 「하루 크롤 횟수」가 먼저인가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━
  강도(%) = 변동률 × **하루 크롤 횟수** × 100  (crawl_grade_bridge)
  그래서 하루에 몇 번 긁는지를 모르면 등급을 못 매긴다.

━━ 크롤 모드가 둘이라 환산도 둘 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · 벽시계 모드 (기준주기 > 0)
        하루 크롤 = 계수 × 하루 ÷ 기준주기 ÷ 느리게배수
  · 연속(랩) 모드 (기준주기 0 = '항상 마감')
        하루 크롤 = 하루 랩 수 × 계수          (하루 랩 수 = 1440 ÷ 1바퀴 분)

  ★ 아직 한 바퀴도 안 돌았으면 **None(모름)** 이다. 0 이나 1 로 지어내면
    등급이 통째로 틀어진다.
"""
from __future__ import annotations

from lemouton.sources.crawl_grade import GradeConfig

DAY_SECONDS = 86400.0
DAY_MINUTES = 1440.0

# 스케줄러(effective_interval_seconds)와 같은 상한. 다르면 화면이 거짓말을 한다 —
# '하루 8회 긁는 중'이라 말해놓고 실제로는 5회만 긁는다.
_WEIGHT_MAX = 5


def crawls_per_day(*, weight, base_interval_seconds, avg_lap_minutes,
                   slowdown=None):
    """이 URL 을 하루에 몇 번 긁나. 모르면 None.

    Args:
        weight: crawl_weight (0 이하 = 크롤 제외 → 0.0)
        base_interval_seconds: 자동화 설정 기준주기. 0/None = 연속(랩) 모드.
        avg_lap_minutes: 1바퀴 평균 분 (연속 모드에서만 씀).
        slowdown: 느리게 배수. None = 1.0. 1 미만은 거부(스케줄러와 같은 규칙).
    """
    w = int(weight or 0)
    if w <= 0:
        return 0.0                      # 계수 0 = 크롤 제외 (스케줄러와 같은 뜻)
    w = min(_WEIGHT_MAX, w)

    slow = 1.0 if slowdown is None else float(slowdown)
    if slow < 1.0:
        raise ValueError(
            f"느리게 배수는 1 이상이어야 합니다: {slowdown} — "
            f"더 자주 긁으려면 계수를 올리세요")

    if base_interval_seconds and base_interval_seconds > 0:
        return w * DAY_SECONDS / float(base_interval_seconds) / slow

    # 연속(랩) 모드 — 랩 회전 속도로 환산
    if avg_lap_minutes and avg_lap_minutes > 0:
        return DAY_MINUTES / float(avg_lap_minutes) * w / slow
    return None                          # 아직 한 바퀴도 안 돎 = 모름


def recent_avg_lap_minutes(session, *, limit: int = 12):
    """최근 완료된 랩들의 평균 1바퀴 분. 없으면 None.

    ★ :func:`~lemouton.sources.crawl_schedule.lap_stats` 의 avg_lap_minutes 는
      **오늘 자정(KST) 이후** 완료분만 본다. 오늘 2바퀴가 안 됐으면 None 이 되고,
      그러면 등급을 하나도 못 매긴다 — 어제까지 잘 돌았어도.
      화면이 늘 비어 있으면 쓸모가 없으므로 날짜와 무관하게 최근 N개로 넓혀 잡는다.
    """
    from lemouton.sources.models import CrawlLapRun

    runs = (session.query(CrawlLapRun)
            .order_by(CrawlLapRun.completed_at.desc())
            .limit(max(2, int(limit))).all())
    times = sorted(r.completed_at for r in runs if r.completed_at)
    if len(times) < 2:
        return None
    diffs = [(times[i] - times[i - 1]).total_seconds() / 60.0
             for i in range(1, len(times))]
    diffs = [d for d in diffs if d > 0]
    if not diffs:
        return None
    return round(sum(diffs) / len(diffs), 1)


def composition_grades(session, *, laps: int = 10, window_days: int = 30,
                       now=None, config: GradeConfig | None = None) -> dict:
    """구성(소싱처 × 브랜드)마다 등급·제안계수를 얹은 목록.

    기존 :func:`~lemouton.sources.crawl_change_stats.change_stats` 위에 얹는다 —
    통계를 새로 모으지 않는다(이미 쌓이는 CrawlChangeStat 이 합집합을 들고 있다).
    """
    from datetime import datetime, timezone

    from lemouton.sources.crawl_change_stats import change_stats
    from lemouton.sources.crawl_grade_bridge import summarize_composition
    from lemouton.sources.crawl_schedule import (
        base_crawl_interval_seconds, lap_stats,
    )

    _now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    stats = change_stats(session, laps=laps)
    base = base_crawl_interval_seconds(session)
    laps_info = lap_stats(session, now=_now)
    avg_min = laps_info.get("avg_lap_minutes")
    avg_source = "today"
    if not avg_min:
        # 오늘 2바퀴가 안 됐으면 최근 랩으로 넓혀 잡는다 (위 함수 주석 참조).
        avg_min = recent_avg_lap_minutes(session)
        avg_source = "recent" if avg_min else "none"

    rows = []
    unknown = 0
    for r in stats["rows"]:
        cpd = crawls_per_day(weight=r["current_weight"],
                             base_interval_seconds=base,
                             avg_lap_minutes=avg_min)
        if not cpd:
            # 하루 크롤 횟수를 모르면 등급을 매길 수 없다 — 지어내지 않고 그대로 말한다.
            unknown += 1
            why = ("계수가 0 입니다 — 이 구성은 크롤에서 빼두셨습니다."
                   if (r.get("current_weight") or 0) <= 0 else
                   "랩 완료 기록이 2개 미만이라 하루 크롤 횟수를 알 수 없습니다 — "
                   "크롤이 몇 바퀴 돌아야 등급을 말할 수 있습니다.")
            rows.append({**r, "crawls_per_day": cpd, "grade": None,
                         "grade_name": None, "intensity_pct": None, "note": why})
            continue

        g = summarize_composition(
            source_key=r["source_key"], brand=r["brand"],
            observed=r["observed"], changed=r["changed"],
            price_changed=r.get("price_changed", 0),
            stock_changed=r.get("stock_changed", 0),
            crawls_per_day=cpd, window_days=window_days, config=config)
        rows.append({**r, "crawls_per_day": cpd, **g})

    graded = [x for x in rows if x.get("grade") is not None]
    return {
        "window": {**stats["window"], "window_days": window_days},
        "mode": ("clock" if (base and base > 0) else "continuous"),
        "base_interval_seconds": base,
        "avg_lap_minutes": avg_min,
        # 오늘 것인지 최근 랩에서 넓혀 잡은 것인지 — 화면이 지어내지 않게 그대로 알려준다.
        "avg_lap_source": avg_source,
        "granularity": "composition",   # ★상품별이 아니다 — 화면이 오해하면 안 된다
        "rows": rows,
        "excluded_zero": stats["excluded_zero"],
        "counts": {
            "total": len(rows),
            "graded": len(graded),
            "ungraded": unknown + (len(rows) - len(graded) - unknown),
        },
        # ★화면이 그대로 찍는 문구다 — 마크다운(**굵게**)을 쓰면 별표가 그대로 보인다.
        "note": ("CrawlChangeStat 이 (랩, 소싱처, 브랜드) 집계라 상품별 행이 없습니다. "
                 "상품별 산포는 이 데이터로 만들 수 없습니다."),
    }
