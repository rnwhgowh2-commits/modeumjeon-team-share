# -*- coding: utf-8 -*-
"""옵션 생성 순서·축 프리셋 (2026-08-12 · 노션 옵션 a·b).

사장님이 정하신 순서 — ①색상모음전/모델모음전 → ②옵션축 → ③브랜드 → ④매트릭스의 이름.

여기서 못 박는 것
  · 프리셋으로 고른 축이 **저장되어**, 큰 창(옵션 조합 생성)이 그 이름으로 열린다.
    (창을 새로 만들지 않는 것이 이 설계의 핵심이다 — 두 벌이 되면 갈린다)
  · 프리셋 밖의 축 구성은 받지 않는다.
  · 브랜드 없이는 못 만든다.
"""
import uuid

import pytest


@pytest.fixture
def client():
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _make(client, **kw):
    # [2026-08-19 ui-verify 감사] 옵션함 이름이 겹치면 이제 두 번째부터 거절된다
    #   (중복이름 저장 금지) — 이 파일의 시험 여럿이 같은 이름으로 이 창구를 부르므로
    #   매번 다른 이름을 준다. 시험은 이름 값 자체를 검사하지 않는다.
    body = {'name': f'프리셋 검사함 {uuid.uuid4().hex[:8]}', 'brand': '르무통'}
    body.update(kw)
    return client.post('/optgen/api/option-box', json=body)


@pytest.mark.parametrize('axes', [['모델'], ['모델', '색상'],
                                  ['모델', '색상', '사이즈']])
def test_모델_모음전_세_축을_다_만들_수_있다(client, axes):
    """[2026-08-13 사장님 확정] 모델 모음전을 **연다.**

    🔴 한때 「준비 중」으로 막아 뒀는데 **막는 자리가 틀렸다.**
       옵션을 3축으로 만드는 것 자체는 온전하다 — 축 값 3개가 다 남고
       SKU·옵션명도 서로 다르다(실측).
       겹치는 건 **마켓 전송**뿐이다(옵션 이름이 색상+사이즈 두 칸이라).
       그래서 막이는 전송에 둔다 → tests/test_formatter_axis_collision.py
    마켓별로 몇 축으로 쪼개 보낼지는 **상품가공 「정책 생성」** 몫이다(노션 그대로).
    """
    r = _make(client, axes=axes)
    assert r.status_code == 200, r.get_data(as_text=True)
    code = r.get_json()['code']
    j = client.get(f'/api/bundles/{code}/source-urls').get_json()
    assert [s['axis_name'] for s in (j.get('axis_steps') or [])] == axes


def test_큰_창에서도_모델_축을_저장할_수_있다(client):
    """축이 **실제로 저장되는 곳**은 큰 창(조합 생성)이다 — 여기도 열려 있어야 한다."""
    code = _make(client, axes=['모델', '색상']).get_json()['code']
    r = client.post(f'/api/bundles/{code}/options/combo', json={
        'steps': [{'axis_name': '모델', 'values': ['메이트']},
                  {'axis_name': '색상', 'values': ['블랙']}],
        'selected': [['메이트', '블랙']],
    })
    assert r.status_code == 200, r.get_data(as_text=True)


def test_옛_축이름은_큰_창에서_계속_저장된다(client):
    """라이브에 「단계1·단계2」 매트릭스가 실재한다 — 프리셋을 여기서 강제하면 저장이 죽는다."""
    code = _make(client, axes=['색상', '사이즈']).get_json()['code']
    r = client.post(f'/api/bundles/{code}/options/combo', json={
        'steps': [{'axis_name': '단계1', 'values': ['가']},
                  {'axis_name': '단계2', 'values': ['나']}],
        'selected': [['가', '나']],
    })
    assert r.status_code == 200, r.get_data(as_text=True)


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
