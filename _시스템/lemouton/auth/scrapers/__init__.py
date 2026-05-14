"""소싱처 스크래퍼 — 송장전송기 패턴 통합본.

사용법:
    from lemouton.auth.scrapers import get_scraper
    scraper = get_scraper("musinsa")
    success = scraper.ensure_logged_in("rnwhgowh", "pw_value")
"""
from typing import Optional, Callable
from .base import BaseScraper
from .musinsa import MusinsaScraper
from .ssf import SSFShopScraper
from .ssg import SSGScraper
from .lotteon import LotteonScraper
from .abc import ABCMartScraper, ABCMartGSScraper, GrandStageScraper
from .gs import GSScraper, FolderScraper
from .lotteimall import LotteimallScraper

# 사이트 키 → 스크래퍼 클래스
SCRAPERS = {
    "musinsa": MusinsaScraper,
    "ssf": SSFShopScraper,
    "ssg": SSGScraper,
    "abc": ABCMartScraper,
    "abcGs": ABCMartGSScraper,
    "grandstage": GrandStageScraper,
    "gs": GSScraper,
    "folder": FolderScraper,
    "lotteimall": LotteimallScraper,
    "lotteon": LotteonScraper,
}


def get_scraper(site_key: str,
                log_callback: Optional[Callable[[str, str], None]] = None) -> Optional[BaseScraper]:
    """사이트 키로 스크래퍼 인스턴스 생성."""
    cls = SCRAPERS.get(site_key)
    if cls is None:
        return None
    return cls(log_callback=log_callback)


__all__ = [
    "BaseScraper", "MusinsaScraper", "SSFShopScraper",
    "SSGScraper", "LotteonScraper",
    "ABCMartScraper", "ABCMartGSScraper", "GrandStageScraper",
    "GSScraper", "FolderScraper", "LotteimallScraper",
    "get_scraper", "SCRAPERS",
]
