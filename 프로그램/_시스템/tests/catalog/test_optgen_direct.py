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
    r = client.post('/optgen/api/option-box', json={'name': '르무통 메이트', 'brand': '르무통'})
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j['ok'] is True
    assert j['name'] == '르무통 메이트'
    assert j['display_no'].startswith('U')
    assert j['code'] == j['display_no']      # 열쇠는 번호 — 이름은 겹칠 수 있다


def test_이름이_비면_거절하고_이유를_말한다(client):
    """조용히 만들어 놓으면 나중에 이름 없는 묶음을 아무도 못 찾는다."""
    r = client.post('/optgen/api/option-box', json={'name': '  ', 'brand': '르무통'})
    assert r.status_code == 400
    j = r.get_json()
    assert j['ok'] is False
    assert '이름' in j['error']
    assert j['code'] == 'VALIDATION_ERROR'


def test_같은_브랜드_같은_이름은_거절하고_코드로_알린다(client):
    """[2026-08-19 ui-verify 감사] 사장님 확정 — 중복이름 저장 금지."""
    first = client.post('/optgen/api/option-box',
                        json={'name': '중복확인함', 'brand': '르무통'})
    assert first.status_code == 200, first.get_data(as_text=True)
    dup = client.post('/optgen/api/option-box',
                      json={'name': '중복확인함', 'brand': '르무통'})
    assert dup.status_code == 400, dup.get_data(as_text=True)
    j = dup.get_json()
    assert j['ok'] is False
    assert j['code'] == 'DUPLICATE_NAME'
    assert '중복확인함' in j['error']
    client.delete(f"/optgen/api/option-box/{first.get_json()['code']}")


def test_에러_응답마다_code_필드가_있다(client):
    """[2026-08-19 ui-verify 감사] 호출자가 실패 갈래를 문자열로 가릴 수 있어야 한다."""
    묶음없음 = client.delete('/optgen/api/option-box/U19700101-000000')
    assert 묶음없음.get_json()['code'] == 'NOT_FOUND'

    빈이름 = client.post('/optgen/api/option-box', json={'name': '', 'brand': '르무통'})
    assert 빈이름.get_json()['code'] == 'VALIDATION_ERROR'

    안고른축 = client.post('/optgen/api/option-box',
                        json={'name': '축확인', 'brand': '르무통',
                              'axes': ['색상', '색상', '색상']})
    assert 안고른축.get_json()['code'] == 'INVALID_AXES'


def test_예상못한_오류는_서버_로그에_남는다(client, monkeypatch, caplog):
    """[2026-08-19 ui-verify 감사] 예전엔 클라이언트 응답에만 나가고 서버 로그엔
    아무 흔적이 없었다 — 라이브에서 뭐가 터졌는지 나중에 알 방법이 없었다."""
    import lemouton.matrix.service as service_mod

    def _boom(*a, **kw):
        raise RuntimeError('시험용 예기치 못한 오류')
    # 🔴 라우트가 `create_option_box` 를 함수 안에서 매번 새로 import 하므로
    #    (지연 import), 여기서 갈아끼워도 다음 호출이 그대로 받아 간다.
    monkeypatch.setattr(service_mod, 'create_option_box', _boom)

    import logging
    with caplog.at_level(logging.ERROR, logger='webapp.routes.optgen'):
        r = client.post('/optgen/api/option-box',
                        json={'name': '로그확인', 'brand': '르무통'})
    assert r.status_code == 500
    assert r.get_json()['code'] == 'SERVER_ERROR'
    assert any('옵션함 만들기 실패' in rec.message for rec in caplog.records), \
        '예기치 못한 오류가 서버 로그에 안 남았다'


def test_만든_옵션함_화면이_열린다(client):
    code = client.post('/optgen/api/option-box',
                       json={'name': '메이트', 'brand': '르무통'}).get_json()['code']
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
    client.post('/optgen/api/option-box', json={'name': '목록에보일것', 'brand': '르무통'})
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
                       json={'name': '번호확인', 'brand': '르무통'}).get_json()['code']
    s = SessionLocal()
    try:
        m = s.get(Model, code)
        assert m.is_option_box is True
        assert m.display_no is None
    finally:
        s.close()


def test_상품생성_탭에_묶음_목록이_뜬다(client):
    """고를 것이 안 보이면 상품을 만들 수 없다."""
    html = client.get('/optgen?tab=product').get_data(as_text=True)
    assert '어느 옵션 묶음으로 만들까요' in html


def test_옵션_없는_묶음은_상품생성_목록에_안_뜬다(client):
    """담을 게 없어 눌러도 할 일이 없다."""
    code = client.post('/optgen/api/option-box',
                       json={'name': '빈묶음테스트', 'brand': '르무통'}).get_json()['code']
    html = client.get('/optgen?tab=product').get_data(as_text=True)
    assert '빈묶음테스트' not in html
    client.delete(f'/optgen/api/option-box/{code}')
