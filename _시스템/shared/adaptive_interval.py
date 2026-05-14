# -*- coding: utf-8 -*-
"""
monitor.py - 이상 감지 및 어댑티브 크롤링 간격 조정
역할: 에러율 기반 크롤링 간격 동적 조정. 가격 판단/업로드 없음.
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from shared.platforms import MONITOR

logger = logging.getLogger(__name__)


@dataclass
class CrawlStats:
    """소싱처별 크롤링 통계"""
    소싱처명: str
    현재간격_초: float = MONITOR["초기간격_초"]
    총_요청수: int = 0
    에러수: int = 0
    차단여부: bool = False
    차단해제_시각: float = 0.0      # time.time() 기준
    # 최근 N회 요청의 성공/실패 기록 (True=성공, False=실패)
    최근기록: deque = field(default_factory=lambda: deque(maxlen=100))
    마지막_크롤링_시각: float = 0.0


class AdaptiveCrawlMonitor:
    """
    어댑티브 크롤링 모니터.
    소싱처별로 CrawlStats를 관리하며 에러율에 따라 간격을 동적 조정한다.
    """

    def __init__(self):
        self._stats: dict[str, CrawlStats] = {}

    def get_stats(self, 소싱처명: str) -> CrawlStats:
        """소싱처별 통계 객체를 가져온다. 없으면 새로 생성."""
        if 소싱처명 not in self._stats:
            self._stats[소싱처명] = CrawlStats(소싱처명=소싱처명)
        return self._stats[소싱처명]

    def record_success(self, 소싱처명: str) -> None:
        """크롤링 성공 기록"""
        stats = self.get_stats(소싱처명)
        stats.총_요청수 += 1
        stats.최근기록.append(True)
        stats.마지막_크롤링_시각 = time.time()
        self._adjust_interval(stats)

    def record_error(self, 소싱처명: str, status_code: Optional[int] = None) -> None:
        """크롤링 실패 기록. 429 응답이면 별도 처리."""
        stats = self.get_stats(소싱처명)
        stats.총_요청수 += 1
        stats.에러수 += 1
        stats.최근기록.append(False)

        if status_code == 429:
            self._handle_rate_limit(stats)
        else:
            self._adjust_interval(stats)

    def record_block(self, 소싱처명: str) -> None:
        """차단 감지 시 호출. 60분 대기 설정 + 알림 필요 플래그."""
        stats = self.get_stats(소싱처명)
        stats.차단여부 = True
        stats.차단해제_시각 = time.time() + MONITOR["차단대기_초"]
        logger.error(
            "차단 감지 — 소싱처: %s, 대기: %d초 후 재시도 예정",
            소싱처명, MONITOR["차단대기_초"],
        )

    def can_crawl(self, 소싱처명: str) -> bool:
        """현재 크롤링 가능한 상태인지 확인"""
        stats = self.get_stats(소싱처명)

        # 차단 상태 확인
        if stats.차단여부:
            if time.time() >= stats.차단해제_시각:
                stats.차단여부 = False
                logger.info("차단 해제 — 소싱처: %s", 소싱처명)
            else:
                남은시간 = stats.차단해제_시각 - time.time()
                logger.debug("차단 중 — 소싱처: %s, 남은시간: %.0f초", 소싱처명, 남은시간)
                return False

        # 최소 간격 확인
        if stats.마지막_크롤링_시각 > 0:
            경과시간 = time.time() - stats.마지막_크롤링_시각
            if 경과시간 < stats.현재간격_초:
                return False

        return True

    def get_interval(self, 소싱처명: str) -> float:
        """현재 크롤링 간격(초) 반환"""
        return self.get_stats(소싱처명).현재간격_초

    def get_error_rate(self, 소싱처명: str) -> float:
        """최근 요청 기준 에러율 반환"""
        stats = self.get_stats(소싱처명)
        if not stats.최근기록:
            return 0.0
        errors = sum(1 for r in stats.최근기록 if not r)
        return errors / len(stats.최근기록)

    def _adjust_interval(self, stats: CrawlStats) -> None:
        """에러율에 따라 크롤링 간격을 동적 조정"""
        에러율 = self.get_error_rate(stats.소싱처명)
        이전간격 = stats.현재간격_초

        if 에러율 > MONITOR["에러율_임계치"]:
            # 에러율 5% 초과 → 간격 2배 증가
            stats.현재간격_초 = min(stats.현재간격_초 * 2, MONITOR["차단대기_초"])
            logger.warning(
                "간격 증가 — 소싱처: %s, 에러율: %.1f%%, 간격: %.0f → %.0f초",
                stats.소싱처명, 에러율 * 100, 이전간격, stats.현재간격_초,
            )
        else:
            # 안정 시 20% 단축 (최소 5분)
            단축간격 = stats.현재간격_초 * (1 - MONITOR["안정시_단축률"])
            stats.현재간격_초 = max(단축간격, MONITOR["최소간격_초"])
            if stats.현재간격_초 != 이전간격:
                logger.info(
                    "간격 단축 — 소싱처: %s, 에러율: %.1f%%, 간격: %.0f → %.0f초",
                    stats.소싱처명, 에러율 * 100, 이전간격, stats.현재간격_초,
                )

    def _handle_rate_limit(self, stats: CrawlStats, retry_after: Optional[int] = None) -> None:
        """
        429 수신 시 처리.
        Retry-After 헤더값이 있으면 해당 시간 대기, 없으면 기본 3600초.
        """
        대기시간 = retry_after if retry_after else MONITOR["429_기본대기_초"]
        stats.차단여부 = True
        stats.차단해제_시각 = time.time() + 대기시간
        logger.warning(
            "429 Rate Limit — 소싱처: %s, 대기: %d초",
            stats.소싱처명, 대기시간,
        )

    def is_all_blocked(self, 소싱처목록: list[str]) -> bool:
        """전 소싱처가 차단 상태인지 확인"""
        return all(
            self.get_stats(name).차단여부
            for name in 소싱처목록
        )

    def get_summary(self) -> dict:
        """전체 소싱처 모니터링 요약 반환"""
        summary = {}
        for name, stats in self._stats.items():
            summary[name] = {
                "현재간격_초": stats.현재간격_초,
                "에러율": f"{self.get_error_rate(name):.1%}",
                "총_요청수": stats.총_요청수,
                "에러수": stats.에러수,
                "차단여부": stats.차단여부,
            }
        return summary
