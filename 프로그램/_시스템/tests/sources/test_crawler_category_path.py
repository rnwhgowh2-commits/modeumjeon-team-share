"""크롤 결과에 소싱처 카테고리 경로가 실려 오는지."""
from dataclasses import asdict

from lemouton.sourcing.crawlers.base import CrawlResult


def test_크롤결과에_카테고리경로_필드가_있고_기본값은_빈문자열():
    r = CrawlResult(source='musinsa', product_url='https://x', product_name_raw='테스트', options=[])
    assert r.category_path == ''
    assert 'category_path' in asdict(r)      # asdict → JSON → 확장까지 자동 전파되는 경로
