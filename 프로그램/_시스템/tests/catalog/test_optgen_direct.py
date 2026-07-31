# -*- coding: utf-8 -*-
"""「직접 만들기」 — 상품 없이 옵션만 만드는 흐름.

지금까지는 옵션을 만들려면 **먼저 모음전 상품을 골라야** 했다(창이 모음전 안에서만 열림).
이제 「옵션생성 & 상품생성 > 직접 만들기」에서 이름만 적으면 옵션함이 생기고,
그 자리에서 색상·사이즈 창이 바로 열린다.
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


def test_이름을_적으면_옵션함이_생긴다(client):
    r = client.post('/optgen/api/option-box', json={'name': '르무통 메이트'})
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j['ok'] is True
    assert j['name'] == '르무통 메이트'
    assert j['display_no'].startswith('U')
    assert j['code'] == j['display_no']      # 열쇠는 번호 — 이름은 겹칠 수 있다


def test_이름이_비면_거절하고_이유를_말한다(client):
    """조용히 만들어 놓으면 나중에 이름 없는 묶음을 아무도 못 찾는다."""
    r = client.post('/optgen/api/option-box', json={'name': '  '})
    assert r.status_code == 400
    j = r.get_json()
    assert j['ok'] is False
    assert '이름' in j['error']


def test_만든_옵션함_화면이_열린다(client):
    code = client.post('/optgen/api/option-box',
                       json={'name': '메이트'}).get_json()['code']
    r = client.get(f'/optgen/box/{code}')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert '메이트' in html
    assert code in html


def test_없는_옵션함은_없다고_말한다(client):
    r = client.get('/optgen/box/U19700101-000000')
    assert r.status_code == 404


def test_만든_옵션함이_목록에_보인다(client):
    """만들어 놓고 못 찾으면 만든 의미가 없다."""
    client.post('/optgen/api/option-box', json={'name': '목록에보일것'})
    html = client.get('/optgen?tab=option').get_data(as_text=True)
    assert '목록에보일것' in html


def test_판매용_모음전은_옵션함_목록에_안_섞인다(client):
    """옵션함 목록에 파는 상품이 섞이면 어느 게 안 파는 건지 모른다.

    ⚠️ 테스트 DB 는 파일로 공유된다 — 고정 이름을 쓰면 두 번째 실행부터
       중복으로 터진다. 매번 다른 이름을 쓰고 끝나면 지운다.
    """
    import uuid
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model
    code = f'파는모음전_{uuid.uuid4().hex[:8]}'
    s = SessionLocal()
    try:
        s.add(Model(model_code=code, model_name_raw=code, brand='르무통'))
        s.commit()
        html = client.get('/optgen?tab=option').get_data(as_text=True)
        assert code not in html
    finally:
        s.query(Model).filter_by(model_code=code).delete()
        s.commit()
        s.close()


def test_옵션함에는_상품번호가_없다(client):
    """설계서 규칙 3 — M… 은 파는 것에만."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model
    code = client.post('/optgen/api/option-box',
                       json={'name': '번호확인'}).get_json()['code']
    s = SessionLocal()
    try:
        m = s.get(Model, code)
        assert m.is_option_box is True
        assert m.display_no is None
    finally:
        s.close()
