# -*- coding: utf-8 -*-
"""옵션 생성 순서·축 프리셋 (2026-08-12 · 노션 옵션 a·b).

사장님이 정하신 순서 — ①색상모음전/모델모음전 → ②옵션축 → ③브랜드 → ④매트릭스의 이름.

여기서 못 박는 것
  · 프리셋으로 고른 축이 **저장되어**, 큰 창(옵션 조합 생성)이 그 이름으로 열린다.
    (창을 새로 만들지 않는 것이 이 설계의 핵심이다 — 두 벌이 되면 갈린다)
  · 프리셋 밖의 축 구성은 받지 않는다.
  · 브랜드 없이는 못 만든다.
"""
import pytest


@pytest.fixture
def client():
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _make(client, **kw):
    body = {'name': '프리셋 검사함', 'brand': '르무통'}
    body.update(kw)
    return client.post('/optgen/api/option-box', json=body)


@pytest.mark.parametrize('axes', [['모델'], ['모델', '색상'],
                                  ['모델', '색상', '사이즈'], ['색상', '모델명']])
def test_모델_축은_아직_못_만든다(client, axes):
    """🔴 [2026-08-13 감사] 모델 값을 담을 칸이 없다 —
       1축은 color_code, 2축은 size_code 에 모델명이 들어가고,
       3축은 어디에도 안 들어가 **마켓 옵션 이름이 겹친다**(실측).
       격자·마켓 축 정책이 정해질 때까지 만들기 자체를 막는다."""
    r = _make(client, axes=axes)
    assert r.status_code == 400, r.get_data(as_text=True)
    assert '모델' in (r.get_json() or {}).get('error', '')


def test_큰_창에서도_모델_축은_못_만든다(client):
    """🔴 축이 **실제로 저장되는 곳**은 큰 창(조합 생성)이다.
       만들기 창만 막으면 여기로 그대로 빠져나간다 — 감사에서 실측된 구멍."""
    code = _make(client, axes=['색상', '사이즈']).get_json()['code']
    r = client.post(f'/api/bundles/{code}/options/combo', json={
        'steps': [{'axis_name': '모델', 'values': ['메이트']},
                  {'axis_name': '색상', 'values': ['블랙']}],
        'selected': [['메이트', '블랙']],
    })
    assert r.status_code >= 400, r.get_data(as_text=True)
    assert '모델' in (r.get_json() or {}).get('error', '')


def test_옛_축이름은_큰_창에서_계속_저장된다(client):
    """라이브에 「단계1·단계2」 매트릭스가 실재한다 — 프리셋을 여기서 강제하면 저장이 죽는다."""
    code = _make(client, axes=['색상', '사이즈']).get_json()['code']
    r = client.post(f'/api/bundles/{code}/options/combo', json={
        'steps': [{'axis_name': '단계1', 'values': ['가']},
                  {'axis_name': '단계2', 'values': ['나']}],
        'selected': [['가', '나']],
    })
    assert r.status_code == 200, r.get_data(as_text=True)


def test_색상모음전_2축도_저장된다(client):
    code = _make(client, axes=['색상', '사이즈']).get_json()['code']
    j = client.get(f'/api/bundles/{code}/source-urls').get_json()
    assert [s['axis_name'] for s in (j.get('axis_steps') or [])] == ['색상', '사이즈']


def test_프리셋에_없는_축_구성은_거절한다(client):
    """조용히 받아 두면 화면에 없는 구성이 데이터에만 생긴다."""
    r = _make(client, axes=['재질', '용량'])
    assert r.status_code == 400
    assert '축 구성' in (r.get_json() or {}).get('error', '')


def test_브랜드가_비면_거절한다(client):
    r = client.post('/optgen/api/option-box', json={'name': '무브랜드'})
    assert r.status_code == 400
    assert '브랜드' in (r.get_json() or {}).get('error', '')


def test_축을_안_주면_예전처럼_그냥_만들어진다(client):
    """옛 흐름(축 없이 만들고 큰 창에서 짜기)을 막지 않는다."""
    r = _make(client)
    assert r.status_code == 200
    j = client.get(f"/api/bundles/{r.get_json()['code']}/source-urls").get_json()
    assert not (j.get('axis_steps') or [])
