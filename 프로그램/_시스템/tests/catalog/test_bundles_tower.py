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
    # 서랍 — 「어디까지 왔나」 한 판(막대 + 4상태 + 손 볼 것) + 브랜드·정렬
    for mark in ('어디까지 왔나', '손 볼 것', 'stg-block', 'stg-bar',
                 'twr-stats', 'twr-brands', 'twr-sort'):
        assert mark in html, mark
    for mark in ('상품 생성', '상품 생성 + 정책 적용',
                 '상품 생성 + 마켓 등록 (판매중) ※ 정책 미적용',
                 '상품 생성 + 정책 적용 + 마켓 등록 (판매중)'):
        assert mark in html, mark
    # 현황 네모 카드와 브랜드 밑 상태 목록은 없어졌다(같은 거르기가 두 곳에 있으면 갈린다)
    for gone in ('<div class="twr-stat ', 'id="twr-status"', '<div class="twr-st">상태</div>'):
        assert gone not in html, gone
    # 본 표 — 시안 열 구성 + 이 상품 줄
    for mark in ('매입 → 판매', '최근 30일 판매', '올라간 마켓',
                 f'data-code="{world["code"]}"', '자세히 보기'):
        assert mark in html, mark
    # 이 상품은 크롤 실패 1 + 품절 1 + 정책 없음 1 = 손 볼 것 ⚠
    i = html.find(f'data-code="{world["code"]}"')
    assert 'data-issues="3"' in html[i:i + 400]
    # 마켓 등록(쿠팡)은 있고 정책은 없다 → 4번 상태
    assert 'data-stage="4"' in html[i:i + 400]


def test_마켓에_안_올라간_상품은_판매중이_아니다(client, world):
    """🔴 되돌아오면 안 되는 버그.

    예전 판정은 `판매 중 = 상품번호(display_no) 있는 것`이었다. 상품번호는 만들 때
    무조건 붙어서 **마켓에 하나도 안 올라간 상품까지 「판매 중」**으로 나왔다
    (사장님 실측 — 90개 중 90개가 판매 중, 옆칸 「올라간 마켓」은 전부 회색).
    """
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model
    from webapp.routes import bundles_tower as T

    code = f'미등록상품_{uuid.uuid4().hex[:8]}'
    s = SessionLocal()
    try:
        # 상품번호는 붙어 있다 — 그런데도 판매중이면 안 된다
        s.add(Model(model_code=code, model_name_raw=code, model_name_display=code,
                    brand='르무통', display_no='M20260806-000001'))
        s.commit()
        with T._cache_lock:
            T._sales_cache.clear()
            T._price_cache = None
        html = client.get('/bundles').get_data(as_text=True)
        i = html.find(f'data-code="{code}"')
        assert i > 0, '새 상품이 목록에 안 보인다'
        row = html[i:i + 900]
        assert 'data-stage="1"' in row, row[:300]
        assert 'data-selling="0"' in row, row[:300]
        assert '판매중' not in row.split('</tr>')[0].split('올라간')[0]
    finally:
        s.query(Model).filter(Model.model_code == code).delete()
        s.commit()
        s.close()


def test_구성에만_붙인_정책도_정책_적용으로_센다(client):
    """🔴 「한 상품에 여러 정책」(구성마다 다른 정책)을 놓치면 안 된다.

    정책은 두 곳에 붙는다 — 상품(BundlePolicyLink)과 **구성(SetPolicyLink)**.
    상품 쪽만 보면, 구성마다 정책을 준 상품이 「상품 생성」(정책 없음)으로 잡히고
    「손 볼 것」도 부풀려진다. 실제로는 그 상품은 정책값으로 마켓에 나간다.
    """
    from shared.db import SessionLocal
    from lemouton.policy.models import MarketPolicy, SetPolicyLink
    from lemouton.sets.models import ProductSet
    from lemouton.sourcing.models import Model
    from webapp.routes import bundles_tower as T

    code = f'구성정책_{uuid.uuid4().hex[:8]}'
    s = SessionLocal()
    pol = st = None
    try:
        s.add(Model(model_code=code, model_name_raw=code, model_name_display=code,
                    brand='르무통', display_no='M20260806-000002'))
        pol = MarketPolicy(name=f'구성정책시험_{code}')
        s.add(pol)
        s.flush()
        st = ProductSet(model_code=code, name='1벌')
        s.add(st)
        s.flush()
        # 상품에는 안 붙이고 **구성에만** 붙인다
        s.add(SetPolicyLink(set_id=st.id, policy_id=pol.id))
        s.commit()
        with T._cache_lock:
            T._sales_cache.clear()
            T._price_cache = None

        with SessionLocal() as chk:
            assert code in T.policy_models(chk, [code]), '구성 정책을 못 봤다'

        html = client.get('/bundles').get_data(as_text=True)
        i = html.find(f'data-code="{code}"')
        assert i > 0
        row = html[i:i + 900]
        # 마켓은 없으니 2번(상품 생성 + 정책 적용)이라야 한다 — 1번이면 놓친 것
        assert 'data-stage="2"' in row, row[:300]
    finally:
        s.rollback()
        if st is not None:
            s.query(SetPolicyLink).filter(SetPolicyLink.set_id == st.id).delete()
            s.query(ProductSet).filter(ProductSet.id == st.id).delete()
        if pol is not None:
            s.query(MarketPolicy).filter(MarketPolicy.id == pol.id).delete()
        s.query(Model).filter(Model.model_code == code).delete()
        s.commit()
        s.close()


def test_행에_정책_id가_실린다(client):
    """[#1072] 「정책 매칭」 카드의 "상품관리에서 보기 →" 가 ?policy=<id> 로 걸러 보이려면
    각 행이 자기 정책 id 를 data-policy 로 들고 있어야 한다."""
    from shared.db import SessionLocal
    from lemouton.policy.models import BundlePolicyLink, MarketPolicy
    from lemouton.sourcing.models import Model
    from webapp.routes import bundles_tower as T

    code = f'정책id행_{uuid.uuid4().hex[:8]}'
    s = SessionLocal()
    pol = None
    try:
        s.add(Model(model_code=code, model_name_raw=code, model_name_display=code,
                    brand='르무통', display_no='M20260806-000003'))
        pol = MarketPolicy(name=f'상품관리링크시험_{code}')
        s.add(pol)
        s.flush()
        s.add(BundlePolicyLink(model_code=code, policy_id=pol.id))
        s.commit()
        pid = pol.id
    finally:
        s.close()
    with T._cache_lock:
        T._sales_cache.clear()
        T._price_cache = None

    html = client.get('/bundles').get_data(as_text=True)
    i = html.find(f'data-code="{code}"')
    assert i > 0
    row = html[i:i + 300]
    assert f'data-policy="{pid}"' in row


def test_정책_거르기_배선이_화면에_있다():
    """[#1072] ?policy= 를 읽어 초기 필터를 걸고, 칩으로 알려주는 배선이 실제로 있는지
    소스로 확인 — JS 는 파이썬 테스트로 실행할 수 없어 문자열 존재로 대신한다."""
    from pathlib import Path
    from webapp.routes import bundles_tower as T
    tpl = Path(T.__file__).resolve().parents[1] / 'templates' / 'bundles' / 'tower.html'
    src = tpl.read_text(encoding='utf-8')
    assert "state.policy" in src
    assert "URLSearchParams" in src
    assert "twr-policy-chip" in src
    assert 'data-policy="{{ it.policy_id or \'\' }}"' in src


def test_네_상태_숫자의_합이_전체와_같다():
    """막대(4토막)와 목록이 어긋나지 않는다는 증거 — 겹치지 않게 나눠 센다."""
    from webapp.routes.bundles_tower import (
        STAGES, STAGE_MADE, STAGE_NOPOLICY_SELL, STAGE_POLICY, STAGE_SELLING,
        stage_of,
    )
    got = [stage_of(p, m) for p in (False, True) for m in (False, True)]
    assert sorted(got) == sorted(STAGES), got
    assert stage_of(False, False) == STAGE_MADE
    assert stage_of(True, False) == STAGE_POLICY
    assert stage_of(False, True) == STAGE_NOPOLICY_SELL
    assert stage_of(True, True) == STAGE_SELLING


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
                          'settle': None, 'settle_missing': 0,
                          'realized': None, 'realized_basis': 0,
                          'purchase': 0, 'pp_missing': 0}, \
        '주문이 없으면 0 — 정산·실현 마진은 값이 없으니 None(0 으로 지어내지 않는다)'
    assert j['cancels'] == {'count': 0, 'amount': 0}
    assert j['markets'] == [] and j['recent'] == [] and j['weeks'] == []
    assert j['margin_link'] == '/orders/?tab=margin', \
        '마진 계산기 링크는 그대로 남긴다(그 화면은 하나도 안 건드린다)'
    assert j['nopp_link'] == '/orders/?tab=list&mg=nopp', \
        '「매입가 미입력」은 그 탭이 열린 채로 주문 내역을 연다'
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
    stamp = T.purchase_stamp()          # 실매입가는 안 건드렸다 — 도장은 그대로 둔다
    with T._cache_lock:
        assert 60 in T._sales_cache
        # 옛 값이 든 캐시를 「낡음」으로 만든다 — 값도 눈에 띄게 바꿔 둔다
        T._sales_cache[60] = (0.0, stamp,
                              {code: {'qty': 999, 'revenue': 0, 'count': 0,
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
        # 🔴 **한 번 미리 열어 둔다(warm-up).** 첫 호출에만 도는 준비 쿼리가 있다
        #    (브랜드 색 덮어쓰기 조회 1 + count 2 — 뒤엔 메모리에 남아 안 돈다).
        #    그걸 안 걷어내면 「첫 호출 25 → 두 번째 22」가 되어, N+1 이 없는데도
        #    이 시험이 흔들린다(2026-08-06 실측 — origin/main 원본에서도 같았다).
        measure()
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


# ══════════════════════════════════════════════════════════════════════════
#  3차 — 실현 마진(정산 − 실매입가) · 매입 원가 용어 (설계서 §6.2·§6.3)
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def real_pp():
    """실매입가를 넣고 빼는 도구 — `order_line_purchases` 가 단일 원천이다."""
    from shared.db import SessionLocal
    from lemouton.markets import purchase_price as PP

    made = []

    def _put(line_uid, price):
        s = SessionLocal()
        try:
            PP.upsert(s, line_uid=line_uid, price=price, source=PP.SOURCE_MANUAL)
            made.append(line_uid)
        finally:
            s.close()

    yield _put

    s = SessionLocal()
    try:
        for uid in made:
            PP.delete(s, uid)
    finally:
        s.close()


def _sales(client, code, days=60):
    return client.get(
        f'/bundles/api/tower/{code}/sales?days={days}&fresh=1').get_json()


def test_실현마진은_정산에서_실매입가를_뺀_값이다(client, sold_world, real_pp):
    """설계서 §6.2 — 실현 마진 = 정산 예정 − 실매입가. 실매입가 있는 줄만 더한다.

    sold_world 의 판매 줄은 2개다(취소 1건은 애초에 안 센다):
      · twr-o1 정산 90,000 · twr-o2 정산 없음
    o1 에만 실매입가 60,000 을 적으면 실현 마진은 30,000 하나뿐이어야 한다.
    """
    code = sold_world['code']
    real_pp(f'twr-o1-{code}', 60000)

    j = _sales(client, code)
    t = j['total']
    assert t['count'] == 2, '취소 1건은 판매 건수에 안 든다'
    assert t['realized'] == 90000 - 60000, '정산 90,000 − 실매입가 60,000'
    assert t['purchase'] == 60000, '더한 실매입가도 그대로 밝힌다'
    assert t['realized_basis'] == 1, '2건 중 1건만 기준 — 화면이 「2건 중 1건 기준」'
    assert t['pp_missing'] == 1, '실매입가 없는 판매 1건은 미입력으로 센다'
    mk = {m['market']: m for m in j['markets']}['smartstore']
    assert (mk['realized'], mk['realized_basis'], mk['pp_missing']) == (30000, 1, 1), \
        '마켓별 행도 합계와 같은 규칙으로 센다'


def test_취소건과_정산없는건은_실현마진에_안_섞인다(client, sold_world, real_pp):
    """취소 주문·정산 못 읽은 주문에 매입가가 있어도 실현 마진을 만들지 않는다.

    · 취소(twr-o3)는 매출에서 뺀 건이라 실현 마진에도 못 들어간다
      (넣으면 「팔지도 않은 것의 마진」이 생긴다)
    · 정산 없는 줄(twr-o2)은 0 으로 채우면 매입가만큼 손실로 둔갑한다
    """
    code = sold_world['code']
    real_pp(f'twr-o2-{code}', 40000)      # 정산 없음
    real_pp(f'twr-o3-{code}', 30000)      # 취소 건

    t = _sales(client, code)['total']
    assert t['realized'] is None, '기준 줄이 하나도 없으면 0 이 아니라 「확인 불가」'
    assert t['realized_basis'] == 0 and t['purchase'] == 0
    assert t['pp_missing'] == 1, 'o1 만 미입력 — o2 는 매입가가 있으니 미입력이 아니다'
    assert t['settle_missing'] == 1, '정산 못 읽은 줄은 이미 여기서 세고 있다'


def test_매입가가_없으면_0이_아니라_미입력_건수다(client, sold_world):
    """🔴 0 채움 금지 — 실매입가가 하나도 없으면 실현 마진은 None 이다."""
    t = _sales(client, sold_world['code'])['total']
    assert t['realized'] is None, '0 이면 「마진 0원」으로 읽힌다 — 지어내지 않는다'
    assert t['realized_basis'] == 0
    assert t['purchase'] == 0, '없는 매입가를 0 원으로 더하지 않는다'
    assert t['pp_missing'] == 2, '판매 2건 모두 실매입가 미입력'
    mk = {m['market']: m for m in _sales(client, sold_world['code'])['markets']}
    assert mk['smartstore']['realized'] is None
    assert mk['smartstore']['pp_missing'] == 2


def test_예상가_사입가로는_실현마진을_만들지_않는다(client, sold_world, monkeypatch):
    """설계서 §4 — 소싱 예상가로 낸 마진은 실적 숫자에 섞지 않는다.

    `resolve_purchase_price`(실매입가 없으면 사입가·소싱 예상가로 내려가는 함수)가
    모든 줄에 값을 준다고 해도 실현 마진은 **여전히 없다**. 판매 이력은
    `get_many`(실매입가 표) 하나만 본다는 것을 못 박는다.
    """
    from lemouton.markets import purchase_price as PP

    def _fake(session, line_uids, **kw):
        return {str(u): {'price': 1000, 'tier': PP.TIER_ESTIMATE,
                         'label': PP.TIER_LABEL[PP.TIER_ESTIMATE]}
                for u in (line_uids or [])}

    monkeypatch.setattr(PP, 'resolve_purchase_price', _fake)
    t = _sales(client, sold_world['code'])['total']
    assert t['realized'] is None, '예상가가 굴러 들어와도 실현 마진은 안 만든다'
    assert t['purchase'] == 0
    assert t['pp_missing'] == 2, '예상가가 있어도 「실매입가 미입력」이다'


def test_미입력_링크는_주문내역_매입가_미입력_탭을_연다(client, sold_world):
    """화면이 「채우러 가기」를 말할 수 있어야 한다 — 주소에 탭까지 실린다."""
    import io

    j = _sales(client, sold_world['code'])
    assert j['nopp_link'] == '/orders/?tab=list&mg=nopp'
    html = io.open('webapp/templates/orders/index.html', encoding='utf-8').read()
    assert "get('mg')" in html, '주문 내역이 주소의 mg 값을 읽어 탭을 연다'
    assert 'mgFilter=mgPending' in html, '첫 조회에 그 탭이 실제로 걸린다'
    twr = io.open('webapp/templates/bundles/tower.html', encoding='utf-8').read()
    assert 'j.nopp_link' in twr and '매입가 미입력 ' in twr, \
        '판매 이력 칸이 그 링크를 건다'


# ── 용어 되돌림 (2026-08-07 사장님 정의 확정) ─────────────────────────────
#  🔴 PR#857 의 「최종매입가 → 순마진 예상가」 전환은 **오적용**이었다. 두 값은 다르다.
#     · 최종매입가   = 소싱처 표면노출가 − 혜택            → **매입 원가**
#     · 순마진 예상가 = 정산예정금(배송비 포함) − 최종매입가 → **마진**
#     매입 원가 자리에 「순마진 예상가」라고 적힌 채 배포돼 라이브에서 돈 화면이
#     틀린 이름을 달고 있었다. 여기서 되돌리고, 다시 뒤집히지 않게 못 박는다.

def _read(path):
    import io
    return io.open(path, encoding='utf-8').read()


#: 매입 원가를 가리키는 화면 자리 — 여기엔 「최종매입가」가 있어야 한다.
COST_LABEL_SITES = {
    'webapp/templates/matrix/index.html': [
        '칸: 최종매입가', '표면가·최종매입가는', '<th class="trr">최종매입가</th>',
        '최종매입가 = 표면가에서 혜택을 뺀',
    ],
    'webapp/templates/matrix/detail.html': [
        '최종매입가</th>', '최저 최종매입가',
    ],
    'webapp/templates/bundles/tower.html': [
        '칸 = 최저 최종매입가', '최종매입가</th>',
        '소싱처 크롤값(최종매입가)',
    ],
    'webapp/templates/bundles/_matrix_v3.html': ['>최종매입가</span>'],
    'webapp/templates/orders/index.html': [
        '원 − 최종매입가 ', '정산예정금·최종매입가가 보입니다',
    ],
}


def test_매입_원가_자리는_최종매입가로_부른다(client):
    """표면가 − 혜택 = 최종매입가. 이 자리에 마진 이름을 달면 안 된다."""
    for path, needles in COST_LABEL_SITES.items():
        html = _read(path)
        for n in needles:
            assert n in html, f'{path} 에 「{n}」 이 없다 — 용어 되돌림이 빠졌다'


def test_매입가_자리에_순마진_예상가라는_말이_없다(client):
    """🔴 뒤집힘 감시 — 매입 원가 화면·매입가 tier 라벨 어디에도 마진 이름이 없어야 한다."""
    for path in list(COST_LABEL_SITES) + [
            'webapp/routes/bundles_tower.py',
            'lemouton/markets/purchase_price.py']:
        assert '순마진 예상가' not in _read(path), \
            f'{path} 에 「순마진 예상가」가 다시 들어왔다 — 매입 원가 자리다'


def test_매입가_tier_라벨_3종(client):
    """주문 「매입가」 열의 세 tier 는 전부 **매입 원가** 이름이다."""
    from lemouton.markets.purchase_price import TIER_LABEL
    assert TIER_LABEL == {'real': '실매입가', 'stock': '사입가',
                          'estimate': '최종매입가'}


def test_되돌림이_코드_식별자를_안_건드렸다(client):
    """문구만 바꾼 것이라야 값이 안 갈린다."""
    assert 'min_final' in _read('webapp/templates/matrix/detail.html')
    assert 'final_price' in _read('webapp/templates/bundles/_matrix_v3.html')
    assert "r['min_final']" in _read('webapp/routes/bundles_tower.py')


def test_되돌림이_실매입가_표기를_안_건드린다(client):
    """🔴 이름을 되돌린다고 실매입가 쪽 문구까지 건드리면 안 된다."""
    orders = _read('webapp/templates/orders/index.html')
    assert "PP_TAG={real:'실매입가'" in orders, '매입가 열 tier 배지는 그대로'
    assert '「구매가격」이 곧 실매입가입니다' in orders, '더망고 엑셀 안내도 그대로'
    assert '실매입가를 아직 안 적은 줄이에요' in orders, '「매입가 미입력」 탭 설명 그대로'
    twr = _read('webapp/templates/bundles/tower.html')
    assert '실현 마진 = 정산 예정 − <b>실매입가</b>' in twr,         '판매 이력은 실현 마진의 원천을 실매입가라고 말한다'
    assert '최종매입가' in twr and '실매입가' in twr,         '매입 원가(예상)와 실매입가 두 이름이 한 화면에서 구분돼 쓰인다'


# ── 등록 카테고리 (PR#810 이 「캐시에 컬럼이 없어」 미구현으로 남긴 칸) ────────────

def test_markets_가_등록_카테고리를_실어_보낸다(client, world):
    """마켓 캐시에 있으면 그 값 그대로. 🔴 롯데온은 「마켓이 안 준다」로 갈라 표시한다."""
    from shared.db import SessionLocal
    from lemouton.catalog.models import MarketProduct, MarketProductGroup

    code = world['code']
    s = SessionLocal()
    grp = None
    try:
        grp = MarketProductGroup(name='카테고리 그룹', model_code=code)
        s.add(grp)
        s.flush()
        s.add(MarketProduct(group_id=grp.id, market='smartstore',
                            account_key='default', market_product_id='SS-CAT',
                            name='스스 상품', category_code='50002322',
                            category_name='패션의류>여성의류>티셔츠'))
        # 롯데온 — 캐시는 있는데 카테고리만 아직 안 채워짐(상세 훑기가 안 닿음)
        s.add(MarketProduct(group_id=grp.id, market='lotteon',
                            account_key='default', market_product_id='LO-CAT',
                            name='롯데온 상품'))
        s.commit()

        j = client.get(f'/bundles/api/tower/{code}/markets').get_json()
        assert j['ok'], j
        by = {m['market']: m for m in j['markets']}
        ss = by['smartstore']
        assert ss['reg_category'] == '50002322'
        assert ss['reg_category_name'] == '패션의류>여성의류>티셔츠'
        assert ss['category_via_detail'] is False
        lo = by['lotteon']
        assert lo['reg_category'] is None and lo['reg_category_name'] is None
        # [2026-08-12 정정] 롯데온은 **목록**에 카테고리가 없을 뿐, 상세엔 온다
        #  (scatNo·dcatLst — 등록이 그 두 필드를 복사해 라이브 성공). 그래서
        #  「마켓이 안 알려줘요」가 아니라 「아직 안 채워짐(상세를 봐야 안다)」이다.
        assert lo['category_via_detail'] is True, \
            '롯데온만 채워지는 경로가 다르다(목록이 아니라 상세) — 화면이 그렇게 말해야 한다'
        assert by['coupang']['category_via_detail'] is False
    finally:
        s.rollback()
        if grp is not None:
            s.query(MarketProduct).filter(
                MarketProduct.group_id == grp.id).delete()
            s.query(MarketProductGroup).filter(
                MarketProductGroup.id == grp.id).delete()
            s.commit()
        s.close()


def test_마켓_등록탭_표에_카테고리_열이_있다():
    """열을 더했으면 펼침 판 colspan 도 같이 커져야 한다(안 그러면 표가 어긋난다)."""
    twr = _read('webapp/templates/bundles/tower.html')
    assert '<th class="l">등록 카테고리</th>' in twr
    assert 'regCategory(m)' in twr
    assert 'colspan="12"' in twr and 'colspan="11"' not in twr
    # 값이 없을 때 **왜 없는지**를 갈라 말한다 — 롯데온은 채우는 경로가 달라 문구도 다르다.
    assert '아직 안 채워짐' in twr and 'category_via_detail' in twr, \
        '없는 이유를 정직하게 말한다'
    assert '「내마켓 불러오기」를 다시 하면 채워져요' in twr


def test_판매집계가_쓰는_칸을_전부_가져온다():
    """🔴 속도 때문에 「필요한 칸만」 가져오게 바꿨다. 한 칸이라도 빠지면
    그 값이 **조용히 사라진다**(line_uid 를 빼면 실현 마진이 통째로 없어진다).

    코드가 실제로 쓰는 칸을 세어, 조회가 그 칸을 전부 고르는지 본다.
    """
    import inspect
    import re

    from webapp.routes import bundles_tower as T

    src = inspect.getsource(T._build_sales_index)
    쓰는칸 = set(re.findall(r'\bln\.(\w+)', src))
    가져오는칸 = set(re.findall(r'MarketOrderLine\.(\w+)', src))
    빠진칸 = 쓰는칸 - 가져오는칸
    assert not 빠진칸, (
        f'조회가 안 가져오는 칸을 쓴다 — 그 값이 조용히 빈다: {sorted(빠진칸)}')
    # 시험이 헛돌지 않게 — 실제로 몇 칸은 세어졌어야 한다
    assert len(쓰는칸) >= 4, f'칸을 못 세었다(정규식이 헛돌았나): {쓰는칸}'


# ══════════════════════════════════════════════════════════════════════════
#  4차 — 판매 이력에 「실매입가」 칸 (노션 2026-08-12
#        「상품 > 판매이력탭 : 매입가 필요 (주문내역 데이터 연동)」)
#
#  🔴 3차와 같은 철칙을 그대로 승계한다 —
#     · 원천은 `order_line_purchases`(실매입가) **하나**. 사입가·소싱 예상가 금지.
#     · 없으면 「확인 불가」. **0 으로 채우지 않는다.**
#  합계·마켓별 `purchase` 는 3차에서 이미 지키고 있다. 여기서는 그 값이 실제로
#  화면에 나오는지와, 새로 붙는 두 자리(최근 주문 · 옵션별 순위)를 지킨다.
# ══════════════════════════════════════════════════════════════════════════

def test_최근주문_줄마다_실매입가가_실린다(client, sold_world, real_pp):
    """최근 주문 표에 매입가 열을 그리려면 줄마다 값이 와야 한다."""
    code = sold_world['code']
    real_pp(f'twr-o1-{code}', 60000)

    recent = {r['sku'] + '|' + r['status']: r for r in _sales(client, code)['recent']}
    vals = [r.get('purchase') for r in _sales(client, code)['recent']]
    assert 60000 in vals, '실매입가를 적은 줄에는 그 값이 실려야 한다'
    assert None in vals, '안 적은 줄은 값이 없다(키만 있고 None)'
    assert 0 not in vals, '🔴 0 은 「0원에 사왔다」로 읽힌다 — 지어내지 않는다'
    assert recent, '표본이 비었다(시험이 헛돌았다)'


def test_최근주문_매입가는_하나도_없으면_전부_None이다(client, sold_world):
    """🔴 0 채움 금지 — 3차 `test_매입가가_없으면_0이_아니라_미입력_건수다` 의 줄 단위 짝."""
    recent = _sales(client, sold_world['code'])['recent']
    assert recent, '최근 주문 표본이 있어야 시험이 뜻을 가진다'
    assert all(r.get('purchase') is None for r in recent)


def test_옵션별_순위에_실매입가가_실린다(client, sold_world, real_pp):
    """많이 팔린 옵션 표에도 매입가를 보여 준다 — 어느 옵션이 남는 장사인지 보려면 필요."""
    code = sold_world['code']
    real_pp(f'twr-o1-{code}', 60000)

    top = _sales(client, code)['top_options']
    assert top, '옵션별 순위가 비었다'
    총매입 = sum(o.get('purchase') or 0 for o in top)
    총기준 = sum(o.get('pp_basis') or 0 for o in top)
    assert 총매입 == 60000
    assert 총기준 == 1, '「N건 중 B건 기준」을 옵션별로도 밝힌다'
    assert sum(o.get('pp_missing') or 0 for o in top) == 1


def test_옵션별_실매입가는_실현마진과_같은_기준이다(client, sold_world, real_pp):
    """🔴 합계와 기준이 갈리면 표끼리 숫자가 안 맞는다.

    정산을 못 읽은 줄(twr-o2)에 매입가를 적어도, 실현 마진에 못 들어가므로
    옵션별 매입가에도 들어가면 안 된다 — 합계(total.purchase)와 같은 규칙.
    """
    code = sold_world['code']
    real_pp(f'twr-o2-{code}', 40000)      # 정산 없는 줄

    j = _sales(client, code)
    assert j['total']['purchase'] == 0, '3차에서 이미 지키는 규칙(대조군)'
    assert sum(o.get('purchase') or 0 for o in j['top_options']) == 0, \
        '옵션별도 정산 있는 줄만 — 합계와 같은 기준이어야 표가 맞는다'


def test_옵션별_실매입가_합은_전체와_같다(client, sold_world, real_pp):
    """표가 서로 어긋나는 것을 잡는 감시 — 옵션이 top8 안에 다 들어가는 표본이다."""
    code = sold_world['code']
    real_pp(f'twr-o1-{code}', 60000)

    j = _sales(client, code)
    assert sum(o.get('purchase') or 0 for o in j['top_options']) == j['total']['purchase']


def test_예상가_사입가는_판매이력_어느_칸에도_안_들어온다(client, sold_world, monkeypatch):
    """3차 `test_예상가_사입가로는_실현마진을_만들지_않는다` 를 **새 칸까지** 넓힌다.

    `resolve_purchase_price`(없으면 사입가·소싱 예상가로 내려가는 함수)가 모든 줄에
    값을 준다고 해도, 최근 주문·옵션별 순위 매입가는 **여전히 비어야** 한다.
    """
    from lemouton.markets import purchase_price as PP

    def _fake(session, line_uids, **kw):
        return {u: {'price': 55000, 'tier': PP.TIER_ESTIMATE, 'label': '최종매입가'}
                for u in line_uids}

    monkeypatch.setattr(PP, 'resolve_purchase_price', _fake)

    j = _sales(client, sold_world['code'])
    assert j['total']['purchase'] == 0
    assert all((o.get('purchase') or 0) == 0 for o in j['top_options'])
    assert all(r.get('purchase') is None for r in j['recent'])


def test_판매이력_표가_실매입가_기준을_밝힌다():
    """🔴 `purchase` 는 **실현 마진을 낸 줄만**의 합이다 — 그냥 「매입가」라고 쓰면
    「이 상품 사는 데 쓴 돈 전부」로 읽힌다. 화면이 그 뜻을 말해야 한다.

    열을 늘리면서 빈 표의 colspan 을 안 고치면 표가 어긋난다 — 같이 못 박는다.
    """
    html = _read('webapp/templates/bundles/tower.html')
    assert '(실현 기준)' in html, '열 이름에 기준을 밝힌다'
    assert '사 오는 데 쓴 돈 전부가 아' in html, '오해를 짚어 주는 캡션이 있어야 한다'
    # 마켓별 8→9 · 최근 주문 6→7 · 옵션별 4→5
    assert 'colspan="9"' in html, '마켓별 표 빈칸이 안 늘었다'
    assert 'colspan="7"' in html, '최근 주문 표 빈칸이 안 늘었다'
    assert 'colspan="5"' in html, '옵션별 표 빈칸이 안 늘었다'
