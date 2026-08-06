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
    assert j['total'] == {'qty': 0, 'revenue': 0, 'count': 0,
                          'settle': None, 'settle_missing': 0}, \
        '주문이 없으면 0 — 정산은 값이 없으니 None(0 으로 지어내지 않는다)'
    assert j['cancels'] == {'count': 0, 'amount': 0}
    assert j['markets'] == [] and j['recent'] == [] and j['weeks'] == []
    assert j['margin_link'] == '/orders/?tab=margin', \
        '실현 마진(순마진)은 재계산하지 않고 마진 계산기로 보낸다'
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


# ══════════════════════════════════════════════════════════════════════════
#  2차 — 주별 집계 · 정산 원천 · 배지 합집합 · 캐시 · 쿼리 수
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def sold_world(world):
    """world 에 「구성(세트) 연동 + 주문 3건」을 더한다.

    주문 → SKU 매칭은 price_diff._target_index(SetChannel⋈SetChannelOption) 가
    하므로, 세트 채널을 실제로 만들어 둔다(매칭 규칙을 시험이 흉내 내지 않는다).
    """
    from datetime import date, timedelta

    from shared.db import SessionLocal
    from lemouton.markets.models_orders import MarketOrderLine
    from lemouton.orders.fulfillment import SETTLE_FIELD
    from lemouton.sets.models import ProductSet, SetChannel, SetChannelOption

    code, skus = world['code'], world['skus']
    s = SessionLocal()
    uids = []
    made = {}
    try:
        pset = ProductSet(model_code=code, name=f'세트-{code}')
        s.add(pset)
        s.flush()
        ch = SetChannel(set_id=pset.id, market='smartstore',
                        account_key='default', market_product_id='SS-777',
                        status='linked')
        s.add(ch)
        s.flush()
        s.add(SetChannelOption(channel_id=ch.id, canonical_sku=skus[0],
                               market_option_id='VI-777', status='matched'))
        made = {'set_id': pset.id, 'ch_id': ch.id}
        s.commit()

        # 서로 다른 두 주(월요일 기준)에 걸친 주문 — 하나는 정산값 없음
        today = date.today()
        d_new = today.isoformat()
        d_old = (today - timedelta(days=14)).isoformat()
        base = {'판매처': '스마트스토어', '상품명': '타워테스트',
                '옵션': '블랙 250', '_pd_market_option_id': 'VI-777',
                '쇼핑몰별칭': '계정1'}
        specs = [
            ('twr-o1', d_new, '배송완료', 2, 100000, 90000),
            ('twr-o2', d_old, '배송완료', 1, 50000, None),
            ('twr-o3', d_new, '취소완료', 1, 50000, 45000),
        ]
        for no, day, status, qty, amount, settle in specs:
            uid = f'{no}-{code}'
            row = dict(base, 오픈마켓주문번호=no, 수량=str(qty),
                       상품금액=str(amount), 주문상태=status,
                       주문일=f'{day} 10:00')
            if settle is not None:
                row[SETTLE_FIELD] = str(settle)
            # 상품분만 든 옛 칸은 일부러 채워 둔다 — 이걸 대신 쓰면 시험이 깨진다
            row['정산예정금액'] = '11111'
            s.add(MarketOrderLine(line_uid=uid, market='smartstore',
                                  order_no=no, order_date=f'{day} 10:00',
                                  status=status, account='계정1', row=row))
            uids.append(uid)
        s.commit()
        yield {'code': code, 'skus': skus, 'week_new': d_new, 'week_old': d_old}
    finally:
        s.rollback()
        s.query(MarketOrderLine).filter(
            MarketOrderLine.line_uid.in_(uids or [''])).delete(
                synchronize_session=False)
        if made:
            s.query(SetChannelOption).filter(
                SetChannelOption.channel_id == made['ch_id']).delete()
            s.query(SetChannel).filter(SetChannel.id == made['ch_id']).delete()
            s.query(ProductSet).filter(ProductSet.id == made['set_id']).delete()
        s.commit()
        s.close()


def test_sales_주별_마켓별_집계(client, sold_world):
    """판매 추이 그래프 재료 — 주(월요일 시작) × 마켓별 수량. 취소는 안 센다."""
    from webapp.routes.bundles_tower import _week_start
    j = client.get(
        f'/bundles/api/tower/{sold_world["code"]}/sales?days=60&fresh=1').get_json()
    assert j['ok'], j
    weeks = {w['week']: w['by_market'] for w in j['weeks']}
    w_new = _week_start(sold_world['week_new'])
    w_old = _week_start(sold_world['week_old'])
    assert set(weeks) == {w_new, w_old}, '주문이 있는 주만 — 빈 주를 지어내지 않는다'
    assert weeks[w_new] == {'smartstore': 2}, '취소 1건은 판매 수량에서 빠진다'
    assert weeks[w_old] == {'smartstore': 1}
    # 주는 오름차순으로 나온다(그래프가 왼→오른쪽으로 그린다)
    assert [w['week'] for w in j['weeks']] == sorted(weeks)


def test_sales_정산은_배송비포함_칸에서만_읽는다(client, sold_world):
    """정산 예정 = 「정산예정금(배송비포함)」 합. 상품분 칸으로 대신 채우지 않는다."""
    j = client.get(
        f'/bundles/api/tower/{sold_world["code"]}/sales?days=60&fresh=1').get_json()
    assert j['total']['settle'] == 90000, \
        '값이 있는 판매 1건만 더한다(취소 건·옛 칸은 안 센다)'
    assert j['total']['settle_missing'] == 1, '정산값 없는 판매 1건은 따로 센다'
    mk = {m['market']: m for m in j['markets']}['smartstore']
    assert mk['settle'] == 90000 and mk['settle_missing'] == 1
    assert 'margin' not in j['total'], \
        '실현 마진은 상품 단위로 낼 수 없다 — 링크로만 안내한다'


def test_배지는_3원천_합집합(client, sold_world):
    """MarketRegistration 이 없는 마켓도 세트 연동·마켓 캐시로 「등록됨」이 된다."""
    from shared.db import SessionLocal
    from lemouton.catalog.models import MarketProduct, MarketProductGroup
    from webapp.routes.bundles_tower import _registered_markets

    code = sold_world['code']
    s = SessionLocal()
    grp = None
    try:
        # ③ 마켓 캐시(그룹으로 담은 것) — 옥션
        grp = MarketProductGroup(name='타워 그룹', model_code=code)
        s.add(grp)
        s.flush()
        s.add(MarketProduct(group_id=grp.id, market='auction',
                            account_key='default', market_product_id='AU-1',
                            name='옥션 상품'))
        s.commit()
        got = _registered_markets(s, [code])[code]
        assert 'coupang' in got, '① MarketRegistration'
        assert 'smartstore' in got, '② SetChannel/SetChannelOption'
        assert 'auction' in got, '③ MarketProductGroup → MarketProduct'
        assert 'lotteon' not in got, '근거 없는 마켓까지 켜지지는 않는다'
    finally:
        s.rollback()
        if grp is not None:
            s.query(MarketProduct).filter(
                MarketProduct.group_id == grp.id).delete()
            s.query(MarketProductGroup).filter(
                MarketProductGroup.id == grp.id).delete()
        s.commit()
        s.close()
    # 겉 표 배지와 markets 탭이 같은 판정을 쓴다
    j = client.get(f'/bundles/api/tower/{code}/markets').get_json()
    by = {m['market']: m for m in j['markets']}
    assert by['smartstore']['registered'] is True
    assert by['lotteon']['registered'] is False
    html = client.get('/bundles').get_data(as_text=True)
    i = html.find(f'data-code="{code}"')
    row = html[i:html.find('</tr>', i)]
    assert '스마트스토어 등록됨' in row, '겉 표 배지도 같은 합집합을 쓴다'
    assert '롯데온 미등록' in row, '근거 없는 마켓은 회색 그대로'


def test_캐시가_낡으면_옛값을_먼저_주고_뒤에서_갱신한다(client, sold_world):
    """stale-while-revalidate — 요청은 기다리지 않는다(램 아끼려 스레드는 키당 1개)."""
    import time as _t

    from webapp.routes import bundles_tower as T
    code = sold_world['code']
    client.get(f'/bundles/api/tower/{code}/sales?days=60&fresh=1')
    with T._cache_lock:
        assert 60 in T._sales_cache
        # 옛 값이 든 캐시를 「낡음」으로 만든다 — 값도 눈에 띄게 바꿔 둔다
        T._sales_cache[60] = (0.0, {code: {'qty': 999, 'revenue': 0, 'count': 0,
                                           'settle': None, 'settle_missing': 0,
                                           'cancels': {'count': 0, 'amount': 0},
                                           'markets': {}, 'recent': [],
                                           'weeks': {}, 'truncated': False}})
    j = client.get(f'/bundles/api/tower/{code}/sales?days=60').get_json()
    assert j['total']['qty'] == 999, '낡아도 즉시 옛 값을 준다(요청이 안 기다린다)'
    th = T._refresh_threads.get('sales:60')
    assert th is not None, '갱신은 백그라운드 스레드가 맡는다'
    th.join(timeout=30)
    for _ in range(50):                       # 캐시 기록까지 마무리될 짧은 여유
        with T._cache_lock:
            if T._sales_cache[60][0] > 0:
                break
        _t.sleep(0.05)
    j2 = client.get(f'/bundles/api/tower/{code}/sales?days=60').get_json()
    assert j2['total']['qty'] == 3, '뒤에서 갱신된 실제 값으로 바뀐다'


def test_목록_쿼리수가_상품수에_따라_늘지_않는다(client, world):
    """N+1 회귀 감시 — 상품을 늘려도 /bundles 쿼리 수는 그대로여야 한다."""
    import threading
    import uuid as _uuid

    from sqlalchemy import event

    from shared.db import SessionLocal, engine
    from lemouton.sourcing.models import Model
    from webapp.routes import bundles_tower as T

    tid = threading.get_ident()
    box = {'n': 0}

    def _count(*a, **k):
        if threading.get_ident() == tid:      # 백그라운드 갱신은 세지 않는다
            box['n'] += 1

    def measure():
        with T._cache_lock:
            T._sales_cache.clear()
            T._price_cache = None
        box['n'] = 0
        assert client.get('/bundles').status_code == 200
        return box['n']

    event.listen(engine, 'before_cursor_execute', _count)
    extra = []
    try:
        first = measure()
        s = SessionLocal()
        try:
            for i in range(5):
                mc = f'타워부하_{_uuid.uuid4().hex[:8]}'
                extra.append(mc)
                s.add(Model(model_code=mc, model_name_raw=mc,
                            model_name_display=mc, brand='르무통'))
            s.commit()
        finally:
            s.close()
        second = measure()
    finally:
        event.remove(engine, 'before_cursor_execute', _count)
        s = SessionLocal()
        try:
            s.query(Model).filter(Model.model_code.in_(extra or [''])).delete(
                synchronize_session=False)
            s.commit()
        finally:
            s.close()
    assert second == first, (
        f'상품 5개를 더했더니 쿼리가 {first} → {second} 로 늘었다 — N+1 이 살아 있다')
    # 절대 상한은 넉넉히 — 진짜 감시선은 위의 「늘지 않는다」다(다른 시험이 남긴
    # 데이터 양에 따라 흔들리지 않게).
    assert first <= 60, f'목록 한 판이 쿼리 {first}개 — 배치로 묶여 있어야 한다'
