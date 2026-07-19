# -*- coding: utf-8 -*-
"""대량등록 ① 데이터수집 탭 — 라우트·탭 등록·API.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §6
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_데이터수집_탭이_사이드바에_뜬다():
    """SUBTABS 에 없으면 화면에 아예 안 뜬다 — 만들었으면 반드시 등록해야 한다."""
    from webapp.routes.bulk import SUBTABS
    keys = [t['key'] for t in SUBTABS]
    assert 'collect' in keys
    assert keys[0] == 'collect', "데이터수집이 첫 탭이어야 한다(수집 → 가공 → 전송 순서)"


def test_탭_라벨과_설명이_있다():
    from webapp.routes.bulk import SUBTABS
    t = next(x for x in SUBTABS if x['key'] == 'collect')
    assert '데이터수집' in t['label']
    assert t['desc']


def test_데이터수집_페이지가_200(client):
    r = client.get('/bulk/?tab=collect')
    assert r.status_code == 200


def test_페이지에_수집_화면이_들어간다(client):
    html = client.get('/bulk/?tab=collect').get_data(as_text=True)
    assert 'collect-root' in html, "_collect.html 이 include 되지 않았다"


def test_수기등록_탭은_그대로_동작한다(client):
    """새 탭을 넣다가 기존 탭을 깨뜨리지 않았는지."""
    html = client.get('/bulk/?tab=manual').get_data(as_text=True)
    assert 'bulk-manual-form' in html


def test_모르는_탭은_기본_탭으로(client):
    """조용한 빈 화면 금지 — 기존 규칙이 유지되는지."""
    r = client.get('/bulk/?tab=nonexistent')
    assert r.status_code == 200
    assert 'bulk-manual-form' in r.get_data(as_text=True)


def test_등급_API가_200과_형태를_준다(client):
    r = client.get('/bulk/api/collect/grades')
    assert r.status_code == 200
    j = r.get_json()
    assert 'rows' in j
    assert j['granularity'] == 'composition', "상품별이 아니라 구성 평균임을 화면에 알려야 한다"
    assert j['mode'] in ('clock', 'continuous')


def test_등급_API_인자를_안전하게_받는다(client):
    """이상한 값이 와도 500 이 아니라 기본값으로."""
    r = client.get('/bulk/api/collect/grades?laps=abc&days=-5')
    assert r.status_code == 200
    assert r.get_json()['window']['window_days'] >= 1


def test_등급_API_기간을_바꿀_수_있다(client):
    r = client.get('/bulk/api/collect/grades?days=7')
    assert r.get_json()['window']['window_days'] == 7
