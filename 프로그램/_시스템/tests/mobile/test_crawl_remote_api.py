# -*- coding: utf-8 -*-
"""폰 크롤 리모컨 API — 상태 조회 / 자동 on-off / 지금 한 바퀴.

크롤 자체는 로컬 PC 원칙 그대로다. 서버는 '할 일' 표시만 바꾼다.
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    # 모바일 blueprint 는 ENVIRONMENT=team-share-dev 게이트 안에서만 등록된다
    # (app.py 의 기존 _mobile_bp 와 같은 자리). 안 켜면 /mobile/* 이 통째로 404 라
    # '리모컨이 안 붙었다'가 아니라 '게이트가 닫혔다'로 헛짚게 된다. 라이브가 이 값이다.
    monkeypatch.setenv('ENVIRONMENT', 'team-share-dev')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_상태를_물으면_필요한_칸이_다_온다(client):
    r = client.get('/mobile/crawl/api/status')
    assert r.status_code == 200
    d = r.get_json()
    assert d['ok'] is True
    for key in ('pc', 'auto_enabled', 'waiting', 'laps_today', 'last_lap_at'):
        assert key in d, f'{key} 칸이 없다'
    assert 'online' in d['pc']


def test_퍼센트는_지어내지_않는다(client):
    """분모·분자의 단위가 달라 정확한 퍼센트를 낼 수 없다 — 아예 안 준다."""
    d = client.get('/mobile/crawl/api/status').get_json()
    assert 'percent' not in d


def test_자동크롤을_켜고_끌_수_있다(client):
    r = client.post('/mobile/crawl/api/auto', json={'enabled': True})
    assert r.status_code == 200 and r.get_json()['auto_enabled'] is True
    assert client.get('/mobile/crawl/api/status').get_json()['auto_enabled'] is True

    r = client.post('/mobile/crawl/api/auto', json={'enabled': False})
    assert r.get_json()['auto_enabled'] is False
    assert client.get('/mobile/crawl/api/status').get_json()['auto_enabled'] is False


def test_한_바퀴를_시키면_자동크롤도_같이_켜진다(client):
    """꺼져 있으면 서버가 할 일 목록을 비워버려 PC 가 아무것도 안 집어간다."""
    client.post('/mobile/crawl/api/auto', json={'enabled': False})
    r = client.post('/mobile/crawl/api/run-lap', json={})
    assert r.status_code == 200
    d = r.get_json()
    assert d['ok'] is True
    assert d['auto_enabled'] is True
    # 응답의 auto_enabled 는 붙박이 값이라 그것만 보면 아무것도 안 지킨다.
    # 진짜로 켜졌는지는 저장된 설정을 되물어야 안다.
    assert client.get('/mobile/crawl/api/status').get_json()['auto_enabled'] is True, \
        '응답만 True 고 실제 설정은 안 켜졌다'


def test_한_바퀴는_가짜_완료기록을_남기지_않는다(client):
    """start_new_lap(record=True) 면 돌지도 않은 바퀴가 '완료'로 박힌다."""
    before = client.get('/mobile/crawl/api/status').get_json()['laps_today']
    client.post('/mobile/crawl/api/run-lap', json={})
    after = client.get('/mobile/crawl/api/status').get_json()['laps_today']
    assert after == before, '누르기만 했는데 바퀴 수가 늘었다'
