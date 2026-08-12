# -*- coding: utf-8 -*-
"""옵션 만들기 화면이 **기존 모음전도** 받아준다.

🔴 라이브에서 드러난 구멍 — `/optgen/box/<code>` 가 새로 만든 옵션함만 열고
   기존 모음전 172개는 404 였다. 그래서 설계서 **규칙 12(같은 기능의 입구는 하나)**
   를 적용할 수 없었다. 기존 상품은 여전히 옛 화면에서만 옵션을 고칠 수 있었다.

🔴 다만 **파는 것과 안 파는 것은 화면에서 갈라 보여야 한다** — 안 그러면
   지금 팔리고 있는 상품을 「아직 판매 안 함」으로 오해한다.
🔴 지우기는 **여전히 옵션함만** 된다 — 파는 상품이 지워지면 큰일이다.
"""
import uuid

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture
def sellable():
    """판매용 모음전 하나 — 테스트가 끝나면 지운다(테스트 DB 는 파일로 공유된다)."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model
    code = f'파는모음전_{uuid.uuid4().hex[:8]}'
    s = SessionLocal()
    try:
        s.add(Model(model_code=code, model_name_raw=code,
                    model_name_display=code, brand='르무통',
                    display_no='M20260801-999999'))
        s.commit()
        yield code
    finally:
        s.query(Model).filter_by(model_code=code).delete()
        s.commit()
        s.close()


def test_기존_모음전도_옵션_화면이_열린다(client, sellable):
    r = client.get(f'/optgen/box/{sellable}')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert sellable in r.get_data(as_text=True)


def test_파는_것은_판매중으로_보인다(client, sellable):
    """🔴 「아직 판매 안 함」으로 뜨면 팔리는 상품을 안 팔린다고 오해한다."""
    html = client.get(f'/optgen/box/{sellable}').get_data(as_text=True)
    assert '판매 중' in html
    assert '아직 판매 안 함' not in html


def test_옵션함은_아직_판매_안_함으로_보인다(client):
    code = client.post('/optgen/api/option-box',
                       json={'name': '표시확인용', 'brand': '르무통'}).get_json()['code']
    html = client.get(f'/optgen/box/{code}').get_data(as_text=True)
    assert '아직 판매 안 함' in html
    client.delete(f'/optgen/api/option-box/{code}')


def test_파는_상품은_여전히_못_지운다(client, sellable):
    """🔴 여기가 뚫리면 팔고 있는 상품이 통째로 날아간다."""
    r = client.delete(f'/optgen/api/option-box/{sellable}')
    assert r.status_code == 400
    assert '판매' in r.get_json()['error']


def test_없는_코드는_그대로_없다고_한다(client):
    assert client.get('/optgen/box/__없는코드__zzz').status_code == 404


def test_상품생성_목록에서_옵션_고치러_갈_수_있다(client):
    """한 곳에서 열 수 있어야 「입구는 하나」가 된다."""
    html = client.get('/optgen?tab=product').get_data(as_text=True)
    assert '/optgen/box/' in html
