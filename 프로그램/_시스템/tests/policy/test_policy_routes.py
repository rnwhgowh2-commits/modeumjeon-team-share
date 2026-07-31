# -*- coding: utf-8 -*-
"""「정책 생성」 화면 API — 복사 · 브랜드 · 마켓 켜고 끄기 · 넣기 · 불러오기.

화면과 서버가 같은 것을 말하는지 본다. 서버만 되고 화면에 안 나오는 일이
이 프로젝트에서 반복적으로 났다.
"""
import os

import pytest

os.environ.setdefault('DISABLE_AUTH', '1')   # 로그인 벽 우회(솔로 개발용 플래그)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """진짜 앱(create_app)을 임시 SQLite 로 격리해 띄운다.

    ★ 왜 진짜 앱인가 — base.html 이 상단탭·사이드바 같은 공통 문맥을 요구한다.
      최소 Flask 앱으로 템플릿만 렌더하면 그 문맥이 없어 화면 검증이 안 된다.
    ★ 격리 방법·되돌리기는 tests/design/conftest.py 가 실측으로 검증한 그 방식이다
      (라이브와 로컬이 같은 Supabase 를 본다 — 격리가 깨지면 실데이터에 쓴다).
    """
    from tests.design.conftest import _build_isolated_app, _원래대로_되돌리기
    app, temp_engine, temp_session, o_e, o_s = _build_isolated_app(tmp_path, monkeypatch)

    # ★ 두 번째 테스트부터는 webapp.routes.policy 가 **이미 import 돼 있어**
    #   모듈 최상단의 `from shared.db import SessionLocal` 이 첫 앱의 연결을
    #   붙잡고 있다. shared.db 만 갈아 끼우면 이 사본은 안 바뀐다 —
    #   그래서 이 모듈의 이름도 같이 갈아 끼운다(안 그러면 지워진 임시 DB 를 본다).
    import webapp.routes.policy as _pr
    monkeypatch.setattr(_pr, 'SessionLocal', temp_session)

    with app.test_client() as c:
        c._Session = temp_session
        yield c
    _원래대로_되돌리기(temp_engine, temp_session, o_e, o_s)
    temp_engine.dispose()


def _new_policy(client, name, brand=''):
    from lemouton.policy.service import create_policy
    s = client._Session()
    try:
        p = create_policy(s, name=name, brand=brand)
        s.commit()
        return p.id
    finally:
        s.close()


def _fill_common(client, pid, item_key='price', config=None):
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.fields import COMMON_KEY
    from lemouton.policy.service import save_item
    s = client._Session()
    try:
        p = s.get(MarketPolicy, pid)
        save_item(s, policy=p, market=COMMON_KEY, item_key=item_key,
                  config=config or {'margin_rate': 25})
        s.commit()
    finally:
        s.close()


# ── 복사 ────────────────────────────────────────────────────────────────

def test_복사_API(client):
    pid = _new_policy(client, '복사원본')
    r = client.post(f'/api/policies/{pid}/copy', json={})
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] is True
    assert j['name'] == '복사원본 (복사)'


def test_없는_정책은_복사할_수_없다(client):
    r = client.post('/api/policies/99999/copy', json={})
    assert r.status_code == 404


# ── 마켓 켜고 끄기 ──────────────────────────────────────────────────────

def test_마켓_켜고_끄기_API(client):
    pid = _new_policy(client, '마켓토글')
    r = client.post(f'/api/policies/{pid}/markets', json={'markets': ['smartstore']})
    assert r.status_code == 200
    assert r.get_json()['markets'] == ['smartstore']


def test_전부_끄는_것도_받는다(client):
    pid = _new_policy(client, '전부끄기')
    r = client.post(f'/api/policies/{pid}/markets', json={'markets': []})
    assert r.status_code == 200
    assert r.get_json()['markets'] == []


def test_모르는_마켓은_친절히_막는다(client):
    pid = _new_policy(client, '모르는마켓')
    r = client.post(f'/api/policies/{pid}/markets', json={'markets': ['없는마켓']})
    assert r.status_code == 400
    assert '모르는 마켓' in r.get_json()['error']


# ── 넣기 · 불러오기 ─────────────────────────────────────────────────────

def test_넣기_API(client):
    pid = _new_policy(client, '넣기')
    _fill_common(client, pid)
    r = client.post(f'/api/policies/{pid}/push', json={'markets': ['coupang']})
    assert r.status_code == 200
    assert r.get_json()['count'] == 1


def test_불러오기_API(client):
    pid = _new_policy(client, '불러오기')
    _fill_common(client, pid)
    r = client.post(f'/api/policies/{pid}/pull', json={'market': 'coupang'})
    assert r.status_code == 200
    assert r.get_json()['count'] == 1


def test_공통에_아무것도_없으면_넣기는_친절히_막는다(client):
    pid = _new_policy(client, '빈공통')
    r = client.post(f'/api/policies/{pid}/push', json={'markets': ['coupang']})
    assert r.status_code == 400
    assert '먼저 채워' in r.get_json()['error']


# ── 화면 ────────────────────────────────────────────────────────────────

def test_목록_제목이_정책_생성이다(client):
    r = client.get('/policies')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert '정책 생성' in body
    assert '마켓별 정책' not in body


def test_목록에_브랜드_단추가_나온다(client):
    _new_policy(client, '르무통 기본', brand='르무통')
    _new_policy(client, 'TEST')
    body = client.get('/policies').get_data(as_text=True)
    assert '르무통' in body
    assert '브랜드 없음' in body


def test_브랜드로_걸러낸다(client):
    _new_policy(client, '르무통 기본', brand='르무통')
    _new_policy(client, '나이키 기본', brand='나이키')
    body = client.get('/policies?brand=르무통').get_data(as_text=True)
    assert '르무통 기본' in body
    assert '나이키 기본' not in body


def test_브랜드_없음만_따로_걸러낸다(client):
    """빈 문자열로는 「전체」와 못 가른다 — __none__ 으로 고른다.

    ※ 정책 이름을 「르무통 기본」으로 쓰면 안 된다 — 이름 입력칸 안내문구
      (「예: 르무통 기본」)에 걸려 항상 찾아진다.
    """
    _new_policy(client, '브랜드있음정책', brand='르무통')
    _new_policy(client, '브랜드없음정책')
    body = client.get('/policies?brand=__none__').get_data(as_text=True)
    assert '브랜드없음정책' in body
    assert '브랜드있음정책' not in body


def test_목록에_복사_단추가_있다(client):
    _new_policy(client, '복사단추')
    assert '📄 복사' in client.get('/policies').get_data(as_text=True)


def test_상세에_마켓_공통_탭이_있다(client):
    pid = _new_policy(client, '공통탭')
    body = client.get(f'/policies/{pid}').get_data(as_text=True)
    assert '마켓 공통' in body


def test_공통_탭에는_마켓_전용_항목이_안_나온다(client):
    """「위너일 때 가격」은 쿠팡 전용 — 공통에 두면 어디로 넣을지 알 수 없다."""
    pid = _new_policy(client, '공통탭2')
    body = client.get(f'/policies/{pid}?m=common').get_data(as_text=True)
    assert '위너일 때 가격' not in body


def test_쿠팡_탭에는_위너_항목이_나온다(client):
    pid = _new_policy(client, '쿠팡탭')
    body = client.get(f'/policies/{pid}?m=coupang').get_data(as_text=True)
    assert '위너일 때 가격' in body


def test_마켓_탭에는_공통_불러오기_단추가_있다(client):
    pid = _new_policy(client, '불러오기단추')
    body = client.get(f'/policies/{pid}?m=smartstore').get_data(as_text=True)
    assert '공통 불러오기' in body
    assert '전체 불러오기' in body


def test_공통_탭에는_넣을_마켓_고르는_줄이_있다(client):
    pid = _new_policy(client, '넣기줄')
    body = client.get(f'/policies/{pid}?m=common').get_data(as_text=True)
    assert '저장하고 넣기' in body


def test_모르는_마켓을_주소로_넣으면_공통으로_돌아간다(client):
    """주소를 손으로 고쳐도 없는 마켓 화면이 뜨면 안 된다."""
    pid = _new_policy(client, '이상한주소')
    body = client.get(f'/policies/{pid}?m=없는마켓').get_data(as_text=True)
    assert '저장하고 넣기' in body
