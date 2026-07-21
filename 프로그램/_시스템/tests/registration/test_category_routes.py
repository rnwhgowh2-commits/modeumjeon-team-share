# -*- coding: utf-8 -*-
"""카테고리 사전 라우트 — status·harvest·검색.

[2026-07-22 코드리뷰 수정] harvest 는 백그라운드 스레드로 돈다(Critical: gunicorn sync
워커 60초 타임아웃 회피). POST 는 202+started 만 확인해 주고, 실제 성공/실패는
GET status 의 running/last_error/last_summary 로 폴링해서 읽는다 — 아래 테스트들은
`_run_harvest` 를 monkeypatch 한 뒤 `_wait_until()` 로 백그라운드 스레드가 끝나기를
기다리는 패턴을 공유한다.
"""
import datetime
import threading
import time

import pytest


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
    unique(market,code) 충돌을 막기 위해 이 파일이 심은 행만 정확히 지운다."""
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory
    s = SessionLocal()
    try:
        for market, code in _SEEDED:
            row = s.query(MarketCategory).filter_by(market=market, code=code).first()
            if row is not None:
                s.delete(row)
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
        assert _wait_until(lambda: not cat_routes._harvest_state['eleven11']['running'])
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
        assert _wait_until(lambda: not cat_routes._harvest_state['eleven11']['running'])
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
        assert _wait_until(lambda: not cat_routes._harvest_state['eleven11']['running'])
        _SEEDED.append(('eleven11', 'zzh3'))


def test_harvest_HarvestError는_state_error에_원문으로_노출된다(client, monkeypatch):
    """④ _run_harvest 가 HarvestError 를 던지면 조용히 삼키지 않고 status.last_error 에 원문 사유."""
    from lemouton.registration import category_harvest as ch
    from webapp.routes.bulk import categories as cat_routes

    def boom(market):
        raise ch.HarvestError('IP 미등록 403: 원문사유')

    monkeypatch.setattr(cat_routes, '_run_harvest', boom)
    r = client.post('/bulk/api/categories/harvest/eleven11')
    assert r.status_code == 202
    assert _wait_until(lambda: not cat_routes._harvest_state['eleven11']['running'])
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
    assert _wait_until(lambda: not cat_routes._harvest_state['eleven11']['running'])
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


def test_검색은_사전이_비면_수집안내를_준다(client):
    # 실존하지 않는(영원히 수집될 일 없는) 마켓명 — 실제 마켓명(coupang 등)을 쓰면 Task 12
    # 라이브 수집 이후 사전이 채워져 이 테스트가 영구히 깨진다(시한폭탄, 리뷰 지적).
    r = client.get('/bulk/api/category-search?market=zz-never-harvested&q=운동화')
    data = r.get_json()
    assert data['ok'] is False
    assert '수집' in data['error']       # "설정 탭에서 카테고리 수집 먼저" 안내
