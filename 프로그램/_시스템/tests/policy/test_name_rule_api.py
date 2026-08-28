# -*- coding: utf-8 -*-
"""상품명 규칙 세트 창구 — 만들기·고치기·고르기·미리보기.

🔴 이 파일이 지키는 것
  ① 미리보기가 **전송과 같은 엔진**을 쓴다. 화면이 「이렇게 나갑니다」라고 해 놓고
     실제로 다른 이름이 나가면, 사장님은 틀린 걸 확인할 방법이 없다.
  ② 조립 순서를 비운 채로 저장하면 상품명이 통째로 사라진다 — 창구에서 막는다.
"""
import json
import os

import pytest

os.environ.setdefault('DISABLE_AUTH', '1')


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from tests.design.conftest import _build_isolated_app, _원래대로_되돌리기
    app, temp_engine, temp_session, o_e, o_s = _build_isolated_app(tmp_path, monkeypatch)

    import sys as _sys
    for _m in list(_sys.modules.values()):
        if _m is None:
            continue
        try:
            if getattr(_m, 'SessionLocal', None) is o_s:
                monkeypatch.setattr(_m, 'SessionLocal', temp_session)
        except Exception:       # noqa: BLE001
            pass

    with app.test_client() as c:
        c._Session = temp_session
        yield c
    _원래대로_되돌리기(temp_engine, temp_session, o_e, o_s)
    temp_engine.dispose()


def _만들기(client, **body):
    body.setdefault('name', '기본 조립')
    body.setdefault('token_order', ['brand', 'origin_name'])
    return client.post('/api/name-rules', json=body)


# ── 만들기 ────────────────────────────────────────────────────────────────

def test_규칙_세트를_만든다(client):
    r = _만들기(client)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['ok'] is True
    assert r.get_json()['id'] > 0


def test_이름이_비면_안_만든다(client):
    r = _만들기(client, name='   ')
    assert r.status_code == 400
    assert '이름' in r.get_json()['message']


def test_조립_순서가_비면_안_만든다(client):
    """🔴 빈 조립 순서로 저장하면 그 규칙을 쓰는 정책의 상품명이 통째로 사라진다."""
    r = _만들기(client, token_order=[])
    assert r.status_code == 400
    assert '조립' in r.get_json()['message']


def test_모르는_조각은_임의_텍스트로_받아준다(client):
    """조각 이름이 아니면 그 글자를 그대로 붙인다 — 「정품」 같은 말을 넣는 용도."""
    r = _만들기(client, token_order=['brand', '정품', 'origin_name'])
    assert r.status_code == 200


# ── 목록·고치기 ───────────────────────────────────────────────────────────

def test_목록에_나온다(client):
    _만들기(client, name='갑 규칙')
    _만들기(client, name='을 규칙')
    j = client.get('/api/name-rules').get_json()
    assert {x['name'] for x in j['rules']} == {'갑 규칙', '을 규칙'}


def test_고치면_남는다(client):
    rid = _만들기(client).get_json()['id']
    r = client.post(f'/api/name-rules/{rid}',
                    json={'name': '고친 이름', 'token_order': ['origin_name']})
    assert r.status_code == 200
    j = client.get('/api/name-rules').get_json()
    got = [x for x in j['rules'] if x['id'] == rid][0]
    assert got['name'] == '고친 이름'
    assert got['token_order'] == ['origin_name']


def test_고칠_때도_조립_순서를_못_비운다(client):
    rid = _만들기(client).get_json()['id']
    r = client.post(f'/api/name-rules/{rid}', json={'token_order': []})
    assert r.status_code == 400


def test_없는_규칙을_고치려_하면_404(client):
    r = client.post('/api/name-rules/99999', json={'name': 'x'})
    assert r.status_code == 404


# ── 정책에 붙이기 ─────────────────────────────────────────────────────────

def _정책(client, name='시험 정책'):
    return client.post('/api/policies', json={'name': name}).get_json()['id']


def test_정책에_규칙을_붙이고_뗀다(client):
    rid = _만들기(client).get_json()['id']
    pid = _정책(client)

    r = client.post(f'/api/policies/{pid}/name-rule', json={'name_rule_id': rid})
    assert r.status_code == 200

    from lemouton.policy.models import MarketPolicy
    s = client._Session()
    try:
        assert s.get(MarketPolicy, pid).name_rule_id == rid
    finally:
        s.close()

    # 뗀다 — null 은 「규칙 안 씀」이고, 그러면 정책 값을 그대로 쓴다.
    r = client.post(f'/api/policies/{pid}/name-rule', json={'name_rule_id': None})
    assert r.status_code == 200
    s = client._Session()
    try:
        assert s.get(MarketPolicy, pid).name_rule_id is None
    finally:
        s.close()


def test_없는_규칙은_정책에_못_붙인다(client):
    """🔴 붙는 데 성공하면 화면엔 규칙이 걸린 것처럼 보이는데 아무것도 안 먹는다."""
    pid = _정책(client)
    r = client.post(f'/api/policies/{pid}/name-rule', json={'name_rule_id': 99999})
    assert r.status_code == 400


# ── 미리보기 ──────────────────────────────────────────────────────────────

def test_미리보기가_6마켓_결과를_준다(client):
    j = client.post('/api/name-rules/preview', json={
        'token_order': ['brand', 'origin_name'],
        'sample': {'brand': '나이키', 'name': '에어포스 1'},
    }).get_json()
    assert j['ok'] is True
    assert {r['market'] for r in j['rows']} == {
        'smartstore', 'coupang', 'gmarket', 'auction', 'eleven11', 'lotteon'}
    쿠팡 = [r for r in j['rows'] if r['market'] == 'coupang'][0]
    assert 쿠팡['name'] == '나이키 에어포스 1'


def test_미리보기가_글자수와_바이트수를_같이_준다(client):
    j = client.post('/api/name-rules/preview', json={
        'token_order': ['origin_name'],
        'sample': {'brand': '', 'name': '가나다'},
    }).get_json()
    쿠팡 = [r for r in j['rows'] if r['market'] == 'coupang'][0]
    assert 쿠팡['chars'] == 3
    assert 쿠팡['bytes'] == 9, '한글은 한 글자가 3바이트'


def test_미리보기가_한도를_넘는_마켓을_알려준다(client):
    """11번가 99바이트 — 넘으면 잘리고, 잘렸다는 것을 화면이 보여줘야 한다."""
    j = client.post('/api/name-rules/preview', json={
        'token_order': ['origin_name'],
        'sample': {'brand': '', 'name': '가' * 60},      # 180바이트
    }).get_json()
    십일번가 = [r for r in j['rows'] if r['market'] == 'eleven11'][0]
    assert 십일번가['over'] is True
    assert 십일번가['bytes'] <= 99, '이미 잘린 결과를 보여줘야 한다'
    assert 십일번가['cap_bytes'] == 99


def test_미리보기가_전송과_같은_엔진을_쓴다(client):
    """🔴 화면과 전송이 갈리면 사장님은 틀린 걸 확인할 방법이 없다."""
    from lemouton.registration import process_apply as PA

    body = {'token_order': ['brand', 'origin_name'],
            'sample': {'brand': '나이키', 'name': '에어포스 1'}}
    j = client.post('/api/name-rules/preview', json=body).get_json()

    class _S:
        name = '에어포스 1'
        brand = '나이키'
        source_site = ''
        source_category_path = ''
        options_json = '[]'
        notice_json = '{}'

    for row in j['rows']:
        view, _, _ = PA.apply_rules(
            _S(), {'name': {'token_order': ['brand', 'origin_name']}},
            market=row['market'])
        assert row['name'] == view.name, f"{row['market']} 에서 화면과 전송이 다르다"


def test_미리보기는_아무것도_저장하지_않는다(client):
    client.post('/api/name-rules/preview', json={
        'token_order': ['brand'], 'sample': {'brand': 'X', 'name': 'Y'}})
    assert client.get('/api/name-rules').get_json()['rules'] == []


def test_미리보기도_조립_순서가_비면_막는다(client):
    r = client.post('/api/name-rules/preview',
                    json={'token_order': [], 'sample': {'name': 'X'}})
    assert r.status_code == 400


def test_쓸_수_있는_조각_목록을_준다(client):
    """화면이 단추를 그릴 근거 — 여기 없는 조각을 단추로 내놓으면 안 된다."""
    j = client.get('/api/name-rules/tokens').get_json()
    keys = {t['key'] for t in j['tokens']}
    assert {'brand', 'origin_name', 'model_no', 'product_no', 'category'} <= keys
    for t in j['tokens']:
        assert t['label'] and t['hint'], '단추에 붙일 이름·설명이 있어야 한다'
