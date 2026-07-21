# -*- coding: utf-8 -*-
"""카테고리 사전 라우트 — status·harvest·검색."""
import datetime

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


def test_harvest_모르는_마켓은_400(client):
    r = client.post('/bulk/api/categories/harvest/nosuch')
    assert r.status_code == 400


def test_harvest_실패는_502와_사유_원문(client, monkeypatch):
    from lemouton.registration import category_harvest as ch
    from webapp.routes.bulk import categories as cat_routes
    def boom(market):
        raise ch.HarvestError('IP 미등록 403: 원문사유')
    monkeypatch.setattr(cat_routes, '_run_harvest', boom)
    r = client.post('/bulk/api/categories/harvest/eleven11')
    assert r.status_code == 502
    assert '원문사유' in r.get_json()['error']


def test_harvest_저장단계_실패도_502와_사유_원문(client, monkeypatch):
    """save_snapshot 이 배치 내 중복코드로 HarvestError 를 던지는 경우도 500 이 아니라 502."""
    from lemouton.registration import category_harvest as ch
    from webapp.routes.bulk import categories as cat_routes
    def fake_rows(market):
        return [{'code': '1', 'name': '가', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '가', 'raw': '{}'},
                {'code': '1', 'name': '가또', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '가또', 'raw': '{}'}]
    monkeypatch.setattr(cat_routes, '_run_harvest', fake_rows)
    r = client.post('/bulk/api/categories/harvest/eleven11')
    assert r.status_code == 502
    assert '중복' in r.get_json()['error']
