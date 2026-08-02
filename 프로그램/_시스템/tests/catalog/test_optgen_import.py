# -*- coding: utf-8 -*-
"""내마켓 불러오기 — 이미 파는 상품에서 이름·브랜드를 가져와 옵션함을 만든다.

노션 STEP 1 — 「상품정보(상품명, 브랜드명, 상품번호 등) 조회」
  · 방법1 검색형  · 방법2 마켓 > 계정 > 골라서

🔴 마켓에서 **옵션(색상·사이즈)은 안 가져온다**(사장님 확정). 캐시에 옵션 행이
   아예 없고, 마켓마다 색상 이름이 달라(블랙/BLACK/검정) 자동으로 이으면
   **엉뚱한 색상의 가격**을 가져온다. 축은 「직접 만들기」와 같은 방식으로 짠다.

검색은 이미 있는 것을 쓴다(`/catalog/api/search`) — 다시 만들면 갈린다.
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


#: [2026-08-02] 별도 화면이던 것이 하위탭 ② 안으로 들어왔다(노션 원문 하위탭 3개).
#  옛 주소 `/optgen/import` 는 이 탭으로 보내기만 한다 — 저장해 둔 바로가기를 살린다.
탭 = '/optgen?tab=market'


def test_불러오기_탭이_뜬다(client):
    r = client.get(탭)
    assert r.status_code == 200
    assert '내마켓 불러오기' in r.get_data(as_text=True)


def test_검색칸과_마켓_고르는_칸이_있다(client):
    """노션 방법1(검색형)·방법2(마켓>계정) 둘 다."""
    html = client.get(탭).get_data(as_text=True)
    assert '상품명' in html and '브랜드' in html
    for mk in ('스마트스토어', '쿠팡', '롯데온', '11번가', '옥션', 'G마켓'):
        assert mk in html


def test_옵션은_안_가져온다고_알린다(client):
    """🔴 있는 척하면 사장님이 색상·사이즈가 딸려올 줄 안다."""
    html = client.get(탭).get_data(as_text=True)
    assert '색상·사이즈' in html


def test_옛_주소는_탭으로_보낸다(client):
    """🔴 화면을 둘 다 남기면 같은 기능의 입구가 둘이 된다(설계서 규칙 12)."""
    r = client.get('/optgen/import')
    assert r.status_code == 302
    assert 'tab=market' in r.headers['Location']


def test_불러온_출처를_적어둔다(client):
    """어디서 가져왔는지 안 적어두면 나중에 못 찾는다."""
    from shared.db import SessionLocal
    from lemouton.matrix.models import MatrixOption
    j = client.post('/optgen/api/option-box',
                    json={'name': '불러온상품', 'brand': '나이키',
                          'memo': '불러온 곳: coupang 12345'}).get_json()
    assert j['ok'] is True
    s = SessionLocal()
    try:
        mo = s.query(MatrixOption).filter_by(model_code=j['code']).first()
        assert mo.memo == '불러온 곳: coupang 12345'
    finally:
        s.close()
    client.delete(f"/optgen/api/option-box/{j['code']}")


def test_검색은_있는_것을_쓴다(client):
    """다시 만들면 갈린다 — 기존 검색 창구가 살아 있어야 한다."""
    r = client.get('/catalog/api/search?q=__없는상품__zzz')
    assert r.status_code == 200
    assert 'rows' in r.get_json()
