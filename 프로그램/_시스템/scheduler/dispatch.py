"""스케줄러 디스패치 — 서버는 크롤하지 않고 '잡 등록'만 한다.

기존 `full_cycle()` 은 서버에서 직접 크롤(Phase A)했으나, 무신사(로그인)·롯데온
(playwright)이 서버에서 구조적으로 불가했다(라이브 검증). 이제 스케줄러는
crawl_jobs 에 잡을 등록(enqueue)만 하고, 실제 크롤은 팀 로컬 PC 워커(Phase 2)가
원자적으로 선점·실행한다. 설계: docs/crawl-worker-system.md

매 틱마다:
  1) 리스 만료된 잡 회수(reaper) — 워커 PC 가 크롤 중 꺼져도 다른 PC 가 승계
  2) 기존 bundle_runs 좀비 'running' 정리
  3) '전체 번들' 크롤 잡 1건 등록(중복 방지 — 미완 잡이 있으면 재사용)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def scheduled_dispatch() -> dict:
    """스케줄러 1틱 — 잡 등록만 (서버 직접 크롤 ❌)."""
    from lemouton.sourcing.crawl_queue import (
        enqueue_crawl, reap_expired_jobs, cleanup_stale_bundle_runs,
    )
    out: dict = {}
    try:
        out["reaped"] = reap_expired_jobs()
    except Exception:
        logger.exception("reap_expired_jobs 실패")
        out["reaped"] = {"error": True}
    try:
        out["stale_runs_cleaned"] = cleanup_stale_bundle_runs()
    except Exception:
        logger.exception("cleanup_stale_bundle_runs 실패")
        out["stale_runs_cleaned"] = -1
    try:
        # 전체 번들 크롤 잡 — dedup 으로 미완 잡 있으면 새로 안 만듦(큐 적체 방지)
        out["enqueued"] = enqueue_crawl(
            None, triggered_by="scheduler", routing="queue", dedup=True)
    except Exception:
        logger.exception("enqueue_crawl(scheduler) 실패")
        out["enqueued"] = {"error": True}
    logger.info("scheduled_dispatch: %s", out)
    return out
