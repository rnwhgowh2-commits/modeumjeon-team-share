# -*- coding: utf-8 -*-
"""옵션함 지우기 — 잘못 만든 묶음을 되돌린다.

🔴 지우는 건 되돌릴 수 없다. 그래서 막을 것을 확실히 막는다.
   · 판매용 모음전은 **절대** 못 지운다 (옵션함만)
   · 그 묶음으로 만든 상품이 있으면 못 지운다 (상품이 옵션을 잃는다)
   · 파생 묶음이 딸려 있으면 못 지운다
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _make(client, name='지울것'):
    return client.post('/optgen/api/option-box',
                       json={'name': name, 'brand': '르무통'}).get_json()['code']


def test_옵션함을_지우면_사라진다(client):
    code = _make(client)
    r = client.delete(f'/optgen/api/option-box/{code}')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['ok'] is True
    assert client.get(f'/optgen/box/{code}').status_code == 404


def test_지우면_안에_있던_옵션도_같이_사라진다(client):
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option
    code = _make(client, '옵션있는것')
    s = SessionLocal()
    try:
        s.add(Option(canonical_sku='SKU-DEL00001', model_code=code,
                     color_code='블랙', size_code='250'))
        s.commit()
    finally:
        s.close()
    r = client.delete(f'/optgen/api/option-box/{code}')
    assert r.status_code == 200
    assert r.get_json()['deleted_options'] == 1
    s = SessionLocal()
    try:
        assert s.get(Option, 'SKU-DEL00001') is None
    finally:
        s.close()


def test_판매용_모음전은_못_지운다(client):
    """🔴 여기가 뚫리면 팔고 있는 상품이 통째로 날아간다."""
    import uuid
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model
    code = f'파는것_{uuid.uuid4().hex[:8]}'
    s = SessionLocal()
    try:
        s.add(Model(model_code=code, model_name_raw=code, brand='르무통'))
        s.commit()
        r = client.delete(f'/optgen/api/option-box/{code}')
        assert r.status_code == 400
        assert '판매' in r.get_json()['error']
        assert s.get(Model, code) is not None      # 그대로 살아 있어야 한다
    finally:
        s.query(Model).filter_by(model_code=code).delete()
        s.commit()
        s.close()


def test_없는_것을_지우라면_없다고_말한다(client):
    r = client.delete('/optgen/api/option-box/U19700101-000000')
    assert r.status_code == 404


def test_그_묶음으로_만든_상품이_있으면_못_지운다(client):
    """상품이 옵션을 잃으면 마켓에 빈 상품이 남는다."""
    from shared.db import SessionLocal
    from lemouton.matrix.models import BundleMatrixLink, MatrixOption
    code = _make(client, '상품만든것')
    s = SessionLocal()
    try:
        mo = s.query(MatrixOption).filter_by(model_code=code).first()
        s.add(BundleMatrixLink(model_code=code, matrix_option_id=mo.id))
        s.commit()
    finally:
        s.close()
    r = client.delete(f'/optgen/api/option-box/{code}')
    assert r.status_code == 400
    assert '상품' in r.get_json()['error']


def test_지운_뒤_목록에서도_빠진다(client):
    code = _make(client, '목록에서빠질것')
    client.delete(f'/optgen/api/option-box/{code}')
    html = client.get('/optgen?tab=option').get_data(as_text=True)
    assert code not in html


def test_지울_표_목록을_사람이_적지_않는다(client):
    """🔴 라이브에서 걸린 것 — 손으로 나열했다가 bundle_option_steps 를 빠뜨려
    PostgreSQL 이 삭제를 거부했다. 로컬 SQLite 는 그 제약을 강제하지 않아
    테스트로도 안 잡힌다. 그래서 **목록을 표 정의에서 뽑는지**를 지킨다.
    """
    from webapp.routes.optgen import _model_code_children
    names = {t.name for t in _model_code_children()}
    # 실제로 참조하는 표들이 빠짐없이 잡혀야 한다
    assert 'options' in names
    assert 'bundle_source_urls' in names
    assert 'matrix_options' in names
    assert 'bundle_option_steps' in names          # 라이브에서 빠뜨렸던 그 표
    assert len(names) >= 8


def test_자식_표부터_지우는_순서다():
    """부모(모델)를 먼저 지우면 제약에 걸린다."""
    from webapp.routes.optgen import _model_code_children
    order = [t.name for t in _model_code_children()]
    assert order.index('matrix_options') < order.index('options'), \
        'options 는 matrix_options 를 참조하므로 뒤에 와야 한다(뒤집어 지우면 먼저 지워짐)'
