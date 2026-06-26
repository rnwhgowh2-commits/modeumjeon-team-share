"""크롤러 패키지 + 공용 build_crawlers 헬퍼.

scheduler/jobs.py, webapp/routes/api.py, webapp/routes/sources.py 에서
동일한 crawlers dict 를 만들어 쓰기 위한 단일 진실 원천.
"""
from __future__ import annotations


def build_crawlers() -> dict:
    """5개 사이트 크롤러 인스턴스 dict 반환.

    pipeline.run_pipeline() 의 ``crawlers`` 인자에 그대로 사용 가능.
    sources.py refetch 의 dict 와 동일 키 사용.
    """
    from .lemouton import LemoutonCrawler
    from .musinsa import MusinsaCrawler
    from .ssf import SsfCrawler
    from .lotteon import LotteCrawler
    from .ss_lemouton import SsLemoutonCrawler
    from .ssg import SsgCrawler
    from .hmall import HmallCrawler
    return {
        'lemouton': LemoutonCrawler(),
        'musinsa': MusinsaCrawler(),
        'ssf': SsfCrawler(),
        'lotteon': LotteCrawler(),
        'lotteimall': LotteCrawler(),   # 롯데아이몰(SSR) — LotteCrawler 가 도메인 라우팅으로 처리
        'ss_lemouton': SsLemoutonCrawler(),
        'ssg': SsgCrawler(),
        'hmall': HmallCrawler(),
    }
