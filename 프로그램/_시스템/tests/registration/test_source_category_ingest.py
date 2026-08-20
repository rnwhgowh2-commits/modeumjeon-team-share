"""소싱처 카테고리 사전 적재 — 처음 보면 추가, 다시 보면 카운트만."""
import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.registration.models import SourceCategory
from lemouton.registration import source_category_ingest as ing


def _mem():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_처음_본_경로는_추가되고_깊이와_리프이름이_채워진다():
    s = _mem()
    now = datetime.datetime(2026, 7, 23, 10, 0, 0)
    assert ing.ingest_path(s, 'musinsa', '신발>스니커즈>여성운동화', now=now) is True
    row = s.query(SourceCategory).one()
    assert (row.leaf_name, row.depth, row.product_count) == ('여성운동화', 3, 1)


def test_같은_경로를_또_보면_행은_그대로고_카운트만_오른다():
    s = _mem()
    t1 = datetime.datetime(2026, 7, 23, 10, 0, 0)
    t2 = datetime.datetime(2026, 7, 23, 11, 0, 0)
    ing.ingest_path(s, 'musinsa', '신발>스니커즈>여성운동화', now=t1)
    assert ing.ingest_path(s, 'musinsa', '신발>스니커즈>여성운동화', now=t2) is False
    row = s.query(SourceCategory).one()
    assert row.product_count == 2 and row.last_seen_at == t2
    assert s.query(SourceCategory).count() == 1


def test_빈_경로는_저장하지_않는다():
    s = _mem()
    for bad in ('', '   ', None, '>>'):
        assert ing.ingest_path(s, 'musinsa', bad, now=datetime.datetime(2026, 7, 23)) is False
    assert s.query(SourceCategory).count() == 0
    # 이유: 파싱 실패를 '카테고리 없음'이라는 사실로 둔갑시키지 않는다(추측 금지)


def test_경로_조각의_앞뒤_공백은_정리되고_구분자는_통일된다():
    s = _mem()
    ing.ingest_path(s, 'ssf', ' 신발 > 스니커즈 ', now=datetime.datetime(2026, 7, 23))
    assert s.query(SourceCategory).one().path == '신발>스니커즈'


# ── Task 3: 크롤 수신 2경로 배선 ──────────────────────────────────────────
"""수신 2경로(POST /api/sources/parse · POST /api/sources/crawl-result)가
카테고리 경로를 사전에 적재하는지, 빈 값이면 기존 상품 값을 지우지 않는지."""
import os as _os
from unittest.mock import patch

from flask import Flask
from sqlalchemy import create_engine as _create_engine
from sqlalchemy.orm import Session as _Session

from lemouton.sources.models import SourceProduct
from lemouton.sources.service import upsert_source_product

_os.environ.setdefault('ENVIRONMENT', 'test')


def _route_engine():
    eng = _create_engine('sqlite://')
    Base.metadata.create_all(eng)
    return eng


def test_parse_라우트가_파서_결과의_카테고리경로를_사전에_적재한다():
    """POST /api/sources/parse — payload.category_path 를 source_categories 에 적재."""
    eng = _route_engine()
    import webapp.routes.api_sources_parse as mod
    from lemouton.sourcing.crawlers.base import CrawlResult

    class _FakeCrawler:
        def parse_html(self, html, url):
            return CrawlResult(source='lemouton', product_url=url,
                                product_name_raw='테스트상품', options=[],
                                category_path='신발>스니커즈>여성운동화')

    app = Flask(__name__)
    app.register_blueprint(mod.bp)
    app.config.update(TESTING=True)
    with patch.object(mod, 'SessionLocal', side_effect=lambda: _Session(eng)), \
         patch('lemouton.sourcing.crawlers.build_crawlers',
               return_value={'lemouton': _FakeCrawler()}):
        client = app.test_client()
        r = client.post('/api/sources/parse', json={
            'source_key': 'lemouton',
            'url': 'https://lemouton.example/goods/1',
            'html': '<html>x</html>',
        })
    assert r.status_code == 200, r.get_data(as_text=True)
    q = _Session(eng)
    try:
        row = q.query(SourceCategory).filter_by(source_id='lemouton').one()
        assert row.path == '신발>스니커즈>여성운동화'
        assert row.product_count == 1
    finally:
        q.close()


def test_crawl_result_라우트가_카테고리경로를_적재하고_상품컬럼에도_기록한다():
    """POST /api/sources/crawl-result — items[].category_path → SourceProduct 컬럼 +
    사전(source_categories) 둘 다 갱신."""
    eng = _route_engine()
    url = 'https://ssfshop.example/goods/2'
    seed = _Session(eng)
    upsert_source_product(seed, site='ssf', url=url)
    seed.commit()
    seed.close()

    import webapp.routes.api_pricing as mod
    app = Flask(__name__)
    app.register_blueprint(mod.bp)
    app.config.update(TESTING=True)
    with patch.object(mod, 'SessionLocal', side_effect=lambda: _Session(eng)):
        client = app.test_client()
        r = client.post('/api/sources/crawl-result', json={'items': [{
            'url': url, 'price': 10000, 'stock': 5, 'status': 'ok',
            'category_path': '의류>아우터>코트',
        }]})
    assert r.status_code == 200, r.get_data(as_text=True)
    q = _Session(eng)
    try:
        sp = q.query(SourceProduct).filter_by(site='ssf').one()
        assert sp.category_path == '의류>아우터>코트'
        row = q.query(SourceCategory).filter_by(source_id='ssf').one()
        assert row.path == '의류>아우터>코트'
    finally:
        q.close()


def test_crawl_result_카테고리경로가_비어있으면_기존값을_지우지_않는다():
    """무스톰프 — items[].category_path 가 없거나 공백이면 SourceProduct.category_path 보존."""
    eng = _route_engine()
    url = 'https://ssfshop.example/goods/3'
    seed = _Session(eng)
    sp = upsert_source_product(seed, site='ssf', url=url)
    sp.category_path = '의류>아우터>코트'
    seed.commit()
    seed.close()

    import webapp.routes.api_pricing as mod
    app = Flask(__name__)
    app.register_blueprint(mod.bp)
    app.config.update(TESTING=True)
    with patch.object(mod, 'SessionLocal', side_effect=lambda: _Session(eng)):
        client = app.test_client()
        r = client.post('/api/sources/crawl-result', json={'items': [{
            'url': url, 'price': 10000, 'stock': 5, 'status': 'ok',
            'category_path': '   ',
        }]})
    assert r.status_code == 200, r.get_data(as_text=True)
    q = _Session(eng)
    try:
        sp = q.query(SourceProduct).filter_by(site='ssf').one()
        assert sp.category_path == '의류>아우터>코트'
        assert q.query(SourceCategory).count() == 0
    finally:
        q.close()
