# -*- coding: utf-8 -*-
"""원본 묶음 ↔ 거기서 만든 상품의 소싱처 연결 맞추기.

🔴 왜 필요한가 (설계서 규칙 3) — 상품을 만들 때 옵션을 **복사**한다.
   그래서 나중에 원본에서 소싱처를 고쳐도 **이미 만든 상품에는 안 내려간다.**
   같은 「블랙 265」인데 상품마다 다른 소싱처를 보게 되고 **가격·재고가 갈린다.**

옵션끼리 짝짓는 기준은 **축 값**(색상·사이즈)이다 — 열쇠(`canonical_sku`)는
복사하면서 새로 발급되므로 짝을 지을 수 없다.
"""
from lemouton.matrix.derived_sync import axis_key, plan_sync


class _O:
    def __init__(self, sku, color=None, size=None, axis_values_json=None):
        self.canonical_sku = sku
        self.color_code = color
        self.size_code = size
        self.axis_values_json = axis_values_json


def test_짝은_축_값으로_짓는다():
    """열쇠는 복사하며 새로 발급되므로 짝짓기에 못 쓴다."""
    assert axis_key(_O('SKU-A', '블랙', '265')) == ('블랙', '265')
    assert axis_key(_O('SKU-Z', '블랙', '265')) == axis_key(_O('SKU-A', '블랙', '265'))


def test_원본에_있는데_상품에_없으면_더한다():
    origin = {('블랙', '265'): {11, 12}}
    made = {'SKU-NEW1': (('블랙', '265'), {11})}
    plan = plan_sync(origin, made)
    assert plan['add'] == [('SKU-NEW1', 12)]
    assert plan['remove'] == []


def test_상품에만_있는_옛_연결은_뗀다():
    """🔴 옛 주소를 계속 보면 값이 갈린다 — 원본이 진실이다."""
    origin = {('블랙', '265'): {11}}
    made = {'SKU-NEW1': (('블랙', '265'), {11, 99})}
    plan = plan_sync(origin, made)
    assert plan['remove'] == [('SKU-NEW1', 99)]
    assert plan['add'] == []


def test_같으면_아무것도_안_한다():
    origin = {('블랙', '265'): {11, 12}}
    made = {'SKU-NEW1': (('블랙', '265'), {12, 11})}
    plan = plan_sync(origin, made)
    assert plan['add'] == [] and plan['remove'] == []


def test_원본에_없는_옵션은_건드리지_않는다():
    """🔴 지어내지 않는다 — 짝을 못 찾으면 손대지 않고 그대로 알린다."""
    origin = {('블랙', '265'): {11}}
    made = {'SKU-NEW9': (('빨강', '270'), {77})}
    plan = plan_sync(origin, made)
    assert plan['add'] == [] and plan['remove'] == []
    assert plan['unmatched'] == ['SKU-NEW9']


def test_여러_옵션을_한꺼번에():
    origin = {('블랙', '265'): {11}, ('화이트', '260'): {22}}
    made = {'SKU-A': (('블랙', '265'), set()),
            'SKU-B': (('화이트', '260'), {22})}
    plan = plan_sync(origin, made)
    assert plan['add'] == [('SKU-A', 11)]
    assert plan['remove'] == []


import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_먼저_읽기만_하는_창구가_있다(client):
    """맞추기 전에 무엇이 갈렸는지 눈으로 먼저 본다."""
    r = client.get('/api/admin/option-owner/derived-drift')
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] is True
    assert j['applied'] is False
    assert set(['products', 'add', 'remove', 'unmatched']) <= set(j)


def test_맞추는_창구는_지문을_지킨다(client):
    """🔴 소싱처 연결만 맞춘다 — 옵션·주소는 하나도 안 바뀌어야 한다."""
    before = client.get('/api/admin/option-owner/snapshot').get_json()
    r = client.post('/api/admin/option-owner/derived-sync')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['ok'] is True
    after = client.get('/api/admin/option-owner/snapshot').get_json()
    assert before['overall'] == after['overall']
