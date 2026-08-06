# -*- coding: utf-8 -*-
"""「모음전 상품관리」 컨트롤타워 (시안 v8) — 겉 목록 + 탭 API.

지켜야 할 것:
  · /bundles 목록이 서랍(현황 4장)·본 표 마크업을 서버 렌더로 담는다
  · summary API — 없는 상품은 404, 있는 상품은 KPI·마켓·할 일·메타 형태
  · sales API — days 파라미터가 먹고(1~365), 형태가 고정된다
  · matrix API — matrix._rows_for 값과 **같아야** 한다(재계산 금지의 증거)
  · crawl-now — 크롤 큐(CrawlJob)에 priority 50 잡이 실제로 들어간다
"""
import uuid

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture
def world():
    """상품 1(옵션 2색×2사이즈) + 소싱처 2곳(정상·실패) + 마켓 등록 1건."""
    import app as appmod                     # noqa: F401 — 모델 등록 + 테이블 생성
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
    from lemouton.sourcing.models import BundleSourceUrl, CrawlJob, Model, Option
    from lemouton.uploader.models import MarketRegistration

    tag = uuid.uuid4().hex[:8]
    code = f'타워테스트_{tag}'
    skus = [f'SKU-TWR{tag[:4].upper()}{i}' for i in range(4)]
    s = SessionLocal()
    made = {'sp': [], 'so': []}
    try:
        s.add(Model(model_code=code, model_name_raw='타워테스트',
                    model_name_display='타워테스트', brand='르무통',
                    category='스니커즈', display_no=f'M20260806-{tag[:6]}'))
        for i, sku in enumerate(skus):
            s.add(Option(canonical_sku=sku, model_code=code,
                         color_code='블랙' if i < 2 else '네이비',
                         size_code=str(250 + (i % 2) * 10)))
        s.flush()

        sp1 = SourceProduct(site='musinsa', url=f'https://musinsa.test/twr{tag}',
                            last_status='ok')
        sp2 = SourceProduct(site='ssf', url=f'https://ssf.test/twr{tag}',
                            last_status='error')
        s.add_all([sp1, sp2])
        s.flush()
        so1 = SourceOption(source_product_id=sp1.id, color_text='블랙',
                           size_text='250', current_stock=7, current_price=61320)
        so2 = SourceOption(source_product_id=sp2.id, color_text='블랙',
                           size_text='260', current_stock=0, current_price=63900)
        s.add_all([so1, so2])
        s.flush()
        s.add(OptionSourceLink(canonical_sku=skus[0], source_option_id=so1.id))
        s.add(OptionSourceLink(canonical_sku=skus[1], source_option_id=so2.id))
        made['sp'] = [sp1.id, sp2.id]
        made['so'] = [so1.id, so2.id]
        s.add(BundleSourceUrl(model_code=code, source_key='lotteon',
                              url=f'https://lotteon.test/twr{tag}'))
        s.add(MarketRegistration(canonical_sku=skus[0], market='coupang',
                                 market_product_id='CP-1', last_synced_price=84550,
                                 last_synced_stock=7, status='synced'))
        s.commit()
        yield {'code': code, 'skus': skus}
    finally:
        s.rollback()
        s.query(CrawlJob).filter(CrawlJob.model_code == code).delete()
        s.query(MarketRegistration).filter(
            MarketRegistration.canonical_sku.in_(skus)).delete()
        s.query(BundleSourceUrl).filter(
            BundleSourceUrl.model_code == code).delete()
        s.query(OptionSourceLink).filter(
            OptionSourceLink.source_option_id.in_(made['so'] or [-1])).delete()
        s.query(SourceOption).filter(SourceOption.id.in_(made['so'] or [-1])).delete()
        s.query(SourceProduct).filter(SourceProduct.id.in_(made['sp'] or [-1])).delete()
        s.query(Option).filter(Option.model_code == code).delete()
        s.query(Model).filter(Model.model_code == code).delete()
        s.commit()
        s.close()


@pytest.fixture(autouse=True)
def _fresh_caches():
    """목록 열 캐시(60초)가 시험끼리 값을 물려주지 않게 비운다."""
    from webapp.routes import bundles_tower as T
    with T._cache_lock:
        T._sales_cache.clear()
        T._price_cache = None
    yield
    with T._cache_lock:
        T._sales_cache.clear()
        T._price_cache = None


# ── ① 겉 목록 ───────────────────────────────────────────────────────────────

def test_목록이_서랍과_표를_담는다(client, world):
    r = client.get('/bundles')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # 서랍 — 현황 숫자판 4장 + 브랜드·상태·정렬
    for mark in ('전체 상품', '판매 중', '손 볼 것', '판매 안 함',
                 'twr-stats', 'twr-brands', 'twr-sort'):
        assert mark in html, mark
    # 본 표 — 시안 열 구성 + 이 상품 줄
    for mark in ('매입 → 판매', '최근 30일 판매', '올라간 마켓',
                 f'data-code="{world["code"]}"', '자세히 보기'):
        assert mark in html, mark
    # 이 상품은 크롤 실패 1 + 품절 1 + 정책 없음 1 = 손 볼 것 ⚠
    i = html.find(f'data-code="{world["code"]}"')
    assert 'data-issues="3"' in html[i:i + 400]


# ── ② 한눈에(summary) ──────────────────────────────────────────────────────

def test_summary_형태와_정직한_빈값(client, world):
    j = client.get(f'/bundles/api/tower/{world["code"]}/summary').get_json()
    assert j['ok'], j
    k = j['kpi']
    assert k['opts'] == 4 and k['active'] == 4
    assert k['soldout'] == 1, '아는 재고가 0 인 옵션만 품절'
    assert k['stock'] == 7, '아는 재고(>0)의 합'
    assert k['rep_price'] is None, '정책이 없으면 판매가를 지어내지 않는다'
    # 정책이 없으니 6마켓 모두 「가격 비어 있음」
    assert len(j['todo']['price_empty_markets']) == 6
    assert j['todo']['crawl_fail']['urls'] == 1
    assert j['meta']['model_code'] == world['code']
    assert j['meta']['brand'] == '르무통'
    assert len(j['options']) == 4


def test_summary_없는_상품은_404(client):
    r = client.get('/bundles/api/tower/없는상품xyz/summary')
    assert r.status_code == 404


# ── ③ 판매 이력(sales) ─────────────────────────────────────────────────────

def test_sales_days_파라미터와_형태(client, world):
    j = client.get(
        f'/bundles/api/tower/{world["code"]}/sales?days=7&fresh=1').get_json()
    assert j['ok'] and j['days'] == 7
    assert j['total'] == {'qty': 0, 'revenue': 0, 'count': 0}, \
        '주문이 없으면 0 — 값을 지어내지 않는다'
    assert j['cancels'] == {'count': 0, 'amount': 0}
    assert j['markets'] == [] and j['recent'] == []
    assert j['margin_link'] == '/orders/?tab=margin', \
        '정산·실현 마진은 재계산하지 않고 마진 계산기로 보낸다'
    # 범위 밖 days 는 안전한 값으로 잘린다
    j2 = client.get(
        f'/bundles/api/tower/{world["code"]}/sales?days=99999').get_json()
    assert j2['days'] == 365


# ── ④ 옵션 매트릭스 — _rows_for 와 같은 값 ─────────────────────────────────

def test_matrix_API가_rows_for_값과_같다(client, world):
    from shared.db import SessionLocal
    from webapp.routes.matrix import _rows_for
    s = SessionLocal()
    try:
        expect, colors, sizes = _rows_for(s, world['skus'])
    finally:
        s.close()
    j = client.get(f'/bundles/api/tower/{world["code"]}/matrix').get_json()
    assert j['ok'], j
    assert sorted(j['colors']) == sorted(colors)
    assert j['sizes'] == sizes
    got = {c['sku']: c for c in j['cells']}
    assert set(got) == {r['sku'] for r in expect}
    for r in expect:
        c = got[r['sku']]
        assert c['min_final'] == r['min_final'], '최종매입가는 같은 원천이어야 한다'
        assert c['stock'] == r['stock']
        assert c['soldout'] == (r['stock'] == 0)


# ── 소싱처 수집 이력 ───────────────────────────────────────────────────────

def test_sources_주소합집합과_실패(client, world):
    j = client.get(f'/bundles/api/tower/{world["code"]}/sources').get_json()
    assert j['ok'], j
    assert j['total'] == 4
    assert len(j['urls']) == 3, '옵션 매칭 2 + 모델 주소만 1 — URL 합집합'
    assert j['fail'] == 1
    only_addr = [u for u in j['urls'] if u['matched'] == 0]
    assert len(only_addr) == 1, '주소만 붙은 소싱처도 한 줄로 보인다'


# ── 마켓 등록·정책 ─────────────────────────────────────────────────────────

def test_markets_등록실태와_정책없음(client, world):
    j = client.get(f'/bundles/api/tower/{world["code"]}/markets').get_json()
    assert j['ok'], j
    assert j['policy'] is None
    by = {m['market']: m for m in j['markets']}
    assert set(by) == {'coupang', 'smartstore', 'lotteon', 'eleven11',
                      'auction', 'gmarket'}
    cp = by['coupang']
    assert cp['registered'] is True
    assert cp['policy_price'] is None, '정책 없으면 판매가 없음(지어내지 않음)'
    assert len(cp['options']) == 1
    assert cp['options'][0]['last_synced_price'] == 84550
    assert by['smartstore']['registered'] is False


# ── ⑤ 지금 수집(crawl-now) ─────────────────────────────────────────────────

def test_crawl_now가_큐에_잡을_넣는다(client, world):
    from shared.db import SessionLocal
    from lemouton.sourcing.models import CrawlJob
    r = client.post(f'/bundles/api/tower/{world["code"]}/crawl-now')
    j = r.get_json()
    assert j['ok'], j
    s = SessionLocal()
    try:
        jobs = s.query(CrawlJob).filter(
            CrawlJob.model_code == world['code']).all()
        assert len(jobs) == 1
        assert jobs[0].priority == 50
        assert jobs[0].triggered_by == 'tower'
    finally:
        s.close()
    # 같은 대상 미완 잡이 있으면 재사용(기존 dedup 규칙 그대로)
    j2 = client.post(f'/bundles/api/tower/{world["code"]}/crawl-now').get_json()
    assert j2['ok'] and j2['queued'] is False
    s = SessionLocal()
    try:
        assert s.query(CrawlJob).filter(
            CrawlJob.model_code == world['code']).count() == 1
    finally:
        s.close()


def test_crawl_now_없는_상품은_404(client):
    assert client.post('/bundles/api/tower/없는상품xyz/crawl-now').status_code == 404
