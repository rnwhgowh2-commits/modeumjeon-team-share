# -*- coding: utf-8 -*-
"""카테고리 사전 라우트 — status·harvest·검색.

[2026-07-22 코드리뷰 수정] harvest 는 백그라운드 스레드로 돈다(Critical: gunicorn sync
워커 60초 타임아웃 회피). POST 는 202+started 만 확인해 주고, 실제 성공/실패는
GET status 의 running/last_error/last_summary 로 폴링해서 읽는다 — 아래 테스트들은
`_run_harvest` 를 monkeypatch 한 뒤 `_wait_until()` 로 백그라운드 스레드가 끝나기를
기다리는 패턴을 공유한다.

[2026-07-22 코드리뷰 수정 #2] 실행 상태가 모듈 전역 dict 에서 DB 테이블
(MarketCategoryHarvestRun)로 옮겨갔다 — 라이브가 gunicorn 3워커라 dict 는 워커 로컬이었다.
아래 테스트들은 `cat_routes._harvest_state` 대신 `_run_row(market).running` 로 폴링한다.
"""
import datetime
import threading
import time

import pytest


def _run_row(market):
    """실행 상태 행을 DB 에서 읽는다 — 폴링용 헬퍼(매번 새 세션으로 커밋된 값을 본다)."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategoryHarvestRun
    s = SessionLocal()
    try:
        return s.query(MarketCategoryHarvestRun).filter_by(market=market).first()
    finally:
        s.close()


def _running(market):
    row = _run_row(market)
    return bool(row.running) if row else False


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    application = appmod.create_app()
    application.config['TESTING'] = True
    with application.test_client() as c:
        yield c


_SEEDED = []   # [(market, code), ...] — 이번 테스트에서 심은 행. 끝나면 정확히 이것만 지운다.


def _seed(code='1003', market='eleven11', name='여성운동화',
          path='패션잡화>운동화>여성운동화', leaf=True):
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory
    s = SessionLocal()
    s.add(MarketCategory(market=market, code=code, name=name, full_path=path,
                         depth=3, is_leaf=leaf, harvested_at=datetime.datetime(2026, 7, 22)))
    s.commit(); s.close()
    _SEEDED.append((market, code))


def _wait_until(cond, timeout=2.0, step=0.05):
    """조건이 참이 될 때까지 최대 timeout 초 폴링한다 — 백그라운드 harvest 스레드 join 대체."""
    waited = 0.0
    while not cond() and waited < timeout:
        time.sleep(step)
        waited += step
    return cond()


@pytest.fixture(autouse=True)
def _cleanup_categories():
    """market_categories 는 공유 DB(개발기=SQLite, 라이브=Supabase 동일 규약) — 재실행 시
    unique(market,code) 충돌을 막기 위해 이 파일이 심은 행만 정확히 지운다.

    category_harvest_runs 는 market 이 PK(마켓당 최대 1행)라 이 파일이 건드리는 마켓
    (eleven11 이 전부) 행을 매 테스트 후 지운다 — 다음 테스트·다음 실행이 이전 테스트가
    남긴 running/started_at 을 물려받지 않게(예: 스테일 테스트가 심은 running=True 행이
    다른 409 테스트를 오염시키는 것 방지)."""
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory, MarketCategoryHarvestRun
    s = SessionLocal()
    try:
        for market, code in _SEEDED:
            row = s.query(MarketCategory).filter_by(market=market, code=code).first()
            if row is not None:
                s.delete(row)
        for run in s.query(MarketCategoryHarvestRun).filter_by(market='eleven11').all():
            s.delete(run)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _SEEDED.clear()


def test_status가_마켓별_건수와_수집시각을_준다(client):
    _seed()
    r = client.get('/bulk/api/categories/status')
    assert r.status_code == 200
    data = r.get_json()
    m = {row['market']: row for row in data['rows']}
    assert m['eleven11']['total'] >= 1
    assert m['eleven11']['last_harvested'] is not None
    assert set(m) == {'smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon'}
    # 백그라운드 수집 상태 필드도 항상 실린다 — 진행 중인 게 없으면 running=False, 에러 없음.
    assert 'running' in m['eleven11']
    assert 'last_error' in m['eleven11']
    assert 'last_summary' in m['eleven11']


def test_harvest_모르는_마켓은_400(client):
    r = client.post('/bulk/api/categories/harvest/nosuch')
    assert r.status_code == 400


def test_harvest_시작하면_202와_started를_주고_status는_따로_폴링한다(client, monkeypatch):
    """① POST 는 결과를 기다리지 않고 즉시 202+started 만 준다(60초 타임아웃 회피 핵심)."""
    from webapp.routes.bulk import categories as cat_routes
    release = threading.Event()

    def fake_run(market):
        release.wait(timeout=2)   # 라우트가 이미 202 를 응답한 뒤에야 실제로 진행되게 지연
        return [{'code': 'zzh1', 'name': '테스트A', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '테스트A', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        r = client.post('/bulk/api/categories/harvest/eleven11')
        assert r.status_code == 202
        assert r.get_json() == {'ok': True, 'started': True, 'market': 'eleven11'}
        # 응답이 이미 돌아왔다는 것 자체가 동기 대기가 아니었다는 증거 — 그 다음에 풀어준다.
        release.set()
        assert _wait_until(lambda: not _running('eleven11'))
    finally:
        release.set()
        _SEEDED.append(('eleven11', 'zzh1'))


def test_harvest_완료후_status에_summary가_반영된다(client, monkeypatch):
    """② 백그라운드 수집이 끝나면 GET status 의 last_summary 에 결과가 실린다."""
    from webapp.routes.bulk import categories as cat_routes

    def fake_run(market):
        return [{'code': 'zzh2', 'name': '테스트B', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '테스트B', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        r = client.post('/bulk/api/categories/harvest/eleven11')
        assert r.status_code == 202
        assert _wait_until(lambda: not _running('eleven11'))
        r2 = client.get('/bulk/api/categories/status')
        row = {x['market']: x for x in r2.get_json()['rows']}['eleven11']
        assert row['running'] is False
        assert row['last_error'] is None
        assert row['last_summary'] == {'added': 1, 'updated': 0, 'removed': 0, 'total': 1}
    finally:
        _SEEDED.append(('eleven11', 'zzh2'))


def test_harvest_진행중이면_중복_POST는_409(client, monkeypatch):
    """③ 같은 마켓이 이미 수집 중이면 두 번째 POST 는 409(레이스 방지)."""
    from webapp.routes.bulk import categories as cat_routes
    hold = threading.Event()

    def fake_run(market):
        hold.wait(timeout=2)
        return [{'code': 'zzh3', 'name': '테스트C', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '테스트C', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        r1 = client.post('/bulk/api/categories/harvest/eleven11')
        assert r1.status_code == 202
        r2 = client.post('/bulk/api/categories/harvest/eleven11')
        assert r2.status_code == 409
        assert r2.get_json() == {'ok': False, 'error': 'eleven11: 이미 수집이 진행 중입니다'}
    finally:
        hold.set()
        assert _wait_until(lambda: not _running('eleven11'))
        _SEEDED.append(('eleven11', 'zzh3'))


def test_harvest_30분_넘은_스테일_running은_회수해서_202(client, monkeypatch):
    """③-2 [멀티워커 대비] running=True 인데 started_at 이 30분보다 오래됐으면 죽은 실행으로
    보고 새 POST 가 회수한다(409 아님) — 워커 재시작으로 데몬 스레드가 죽으면 running=True
    가 영영 안 지워지는 케이스를 이걸로 구제한다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategoryHarvestRun
    stale_started = datetime.datetime.utcnow() - datetime.timedelta(minutes=31)
    s = SessionLocal()
    try:
        s.add(MarketCategoryHarvestRun(market='eleven11', running=True,
                                        started_at=stale_started, finished_at=None,
                                        summary_json=None, error=None))
        s.commit()
    finally:
        s.close()

    from webapp.routes.bulk import categories as cat_routes
    hold = threading.Event()

    def fake_run(market):
        hold.wait(timeout=2)
        return [{'code': 'zzh4', 'name': '테스트D', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '테스트D', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        r = client.post('/bulk/api/categories/harvest/eleven11')
        assert r.status_code == 202
        assert r.get_json() == {'ok': True, 'started': True, 'market': 'eleven11'}
    finally:
        hold.set()
        assert _wait_until(lambda: not _running('eleven11'))
        _SEEDED.append(('eleven11', 'zzh4'))


def test_harvest_HarvestError는_state_error에_원문으로_노출된다(client, monkeypatch):
    """④ _run_harvest 가 HarvestError 를 던지면 조용히 삼키지 않고 status.last_error 에 원문 사유."""
    from lemouton.registration import category_harvest as ch
    from webapp.routes.bulk import categories as cat_routes

    def boom(market):
        raise ch.HarvestError('IP 미등록 403: 원문사유')

    monkeypatch.setattr(cat_routes, '_run_harvest', boom)
    r = client.post('/bulk/api/categories/harvest/eleven11')
    assert r.status_code == 202
    assert _wait_until(lambda: not _running('eleven11'))
    r2 = client.get('/bulk/api/categories/status')
    row = {x['market']: x for x in r2.get_json()['rows']}['eleven11']
    assert row['running'] is False
    assert '원문사유' in row['last_error']


def test_harvest_저장단계_실패도_state_error에_원문으로_노출된다(client, monkeypatch):
    """save_snapshot 이 배치 내 중복코드로 HarvestError 를 던지는 경우도 500 이 아니라
    status.last_error 로 사유가 노출된다(조용한 500 금지)."""
    from webapp.routes.bulk import categories as cat_routes

    def fake_rows(market):
        return [{'code': 'zzdup', 'name': '가', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '가', 'raw': '{}'},
                {'code': 'zzdup', 'name': '가또', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '가또', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_rows)
    r = client.post('/bulk/api/categories/harvest/eleven11')
    assert r.status_code == 202
    assert _wait_until(lambda: not _running('eleven11'))
    r2 = client.get('/bulk/api/categories/status')
    row = {x['market']: x for x in r2.get_json()['rows']}['eleven11']
    assert row['running'] is False
    assert '중복' in row['last_error']


def test_검색이_사전에서_리프만_경로포함으로_돌려준다(client):
    _seed()   # eleven11 여성운동화 리프
    _seed(code='1002', name='운동화', path='패션잡화>운동화', leaf=False)
    r = client.get('/bulk/api/category-search?market=eleven11&q=운동화')
    data = r.get_json()
    assert data['ok'] is True
    assert [row['code'] for row in data['rows']] == ['1003']       # 리프만
    assert data['rows'][0]['path'] == '패션잡화>운동화>여성운동화'  # 경로 동봉


def test_검색어에_퍼센트가_있으면_LIKE_와일드카드가_아닌_리터럴로_매치한다(client):
    """Minor 4 — q 의 %/_/\\ 를 이스케이프하지 않으면 '90%' 검색이 '90 뒤에 아무거나'로
    번져 무관한 카테고리까지 걸린다. 이스케이프 후에는 리터럴 '90%' 를 포함한 것만 걸린다."""
    _seed(code='zzpct', name='90% 할인 운동화', path='패션잡화>운동화>90% 할인 운동화')
    _seed(code='zzpctx', name='90XYZ 할인 운동화', path='패션잡화>운동화>90XYZ 할인 운동화')
    r = client.get('/bulk/api/category-search', query_string={'market': 'eleven11', 'q': '90%'})
    data = r.get_json()
    assert data['ok'] is True
    assert [row['code'] for row in data['rows']] == ['zzpct']


def test_esm_probe_사이트카테고리와_sd카테고리_원문을_그대로_반환한다(client, monkeypatch):
    """M2 Task 8 Step 1 — 실측 프로브 200 계약(임시 라우트)."""
    from webapp.routes.bulk import categories as cat_routes
    import lemouton.uploader.market_fetch as MF

    monkeypatch.setattr(cat_routes, '_first_env_prefix', lambda session, market: 'ZZ_TEST')

    calls = []

    class _FakeClient:
        def request(self, method, path):
            calls.append((method, path))
            if 'site-cats' in path:
                return {'siteCatCode': '1000', 'siteCatNm': '패션의류'}
            return {'sdCatCode': '01', 'sdCatNm': '패션의류(표준)'}

    monkeypatch.setattr(MF, '_esm_client', lambda market, prefix: _FakeClient())

    r = client.get('/bulk/api/categories/esm-probe',
                   query_string={'market': 'auction', 'code': '1000'})
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    assert data['site_cats'] == {'siteCatCode': '1000', 'siteCatNm': '패션의류'}
    assert data['sd_cats'] == {'sdCatCode': '01', 'sdCatNm': '패션의류(표준)'}
    assert calls == [('GET', '/item/v1/categories/site-cats/1000'),
                     ('GET', '/item/v1/categories/sd-cats/1000')]


def test_esm_probe_모르는_마켓은_400(client):
    r = client.get('/bulk/api/categories/esm-probe',
                   query_string={'market': 'coupang', 'code': '1'})
    assert r.status_code == 400


def test_esm_probe_code_누락은_400(client):
    r = client.get('/bulk/api/categories/esm-probe', query_string={'market': 'auction'})
    assert r.status_code == 400


def test_설정탭에_카테고리사전_카드가_뜬다(client):
    r = client.get('/bulk/?tab=settings')
    assert r.status_code == 200
    assert 'cat-dict-root' in r.get_data(as_text=True)


def test_검색은_사전이_비면_수집안내를_준다(client):
    # 실존하지 않는(영원히 수집될 일 없는) 마켓명 — 실제 마켓명(coupang 등)을 쓰면 Task 12
    # 라이브 수집 이후 사전이 채워져 이 테스트가 영구히 깨진다(시한폭탄, 리뷰 지적).
    r = client.get('/bulk/api/category-search?market=zz-never-harvested&q=운동화')
    data = r.get_json()
    assert data['ok'] is False
    assert '수집' in data['error']       # "설정 탭에서 카테고리 수집 먼저" 안내
