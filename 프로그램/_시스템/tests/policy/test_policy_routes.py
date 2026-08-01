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
                  config=config or {'sourcing_rate': 25})
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


# ── 판매가 전용 화면 (확정 G1 · I2 · J3 · K3) ────────────────────────────

def test_판매가는_소싱품_사입품_두_칸으로_나온다(client):
    pid = _new_policy(client, '판매가화면')
    body = client.get(f'/policies/{pid}?m=smartstore').get_data(as_text=True)
    assert '소싱품' in body
    assert '사입품' in body


def test_판매가에_가격_안전장치_묶음이_있다(client):
    pid = _new_policy(client, '안전장치')
    body = client.get(f'/policies/{pid}?m=smartstore').get_data(as_text=True)
    assert '가격 안전장치' in body
    assert '안 내려갈 값' in body
    assert '사이즈별 가격 통일' in body


def test_안_고른_방식은_흐리게_나온다(client):
    """확정 I2 — 세 칸을 다 보여주되 지금 먹는 칸만 또렷하게."""
    pid = _new_policy(client, '흐리게')
    body = client.get(f'/policies/{pid}?m=smartstore').get_data(as_text=True)
    assert 'pf-dim' in body
    assert '쓰는 값' in body


def test_판매가에_배송비_칸이_없다(client):
    """「배송」 항목에 이미 있다 — 여기 또 만들면 어느 값이 먹는지 알 수 없다.

    ※ 같은 화면에 「배송」 항목도 있으니 **판매가 칸 안에서만** 찾는다.
    """
    import re
    pid = _new_policy(client, '배송비중복')
    body = client.get(f'/policies/{pid}?m=smartstore').get_data(as_text=True)
    m = re.search(r'id="it-price".*?(?=<div class="it |<div class="savebar)', body, re.S)
    assert m, '판매가 항목 블록을 못 찾음'
    assert 'data-k="fee_amount"' not in m.group(0)


def test_옛_값만_있는_정책도_열린다(client):
    """옛 칸(mode/margin_rate)으로 저장된 정책을 열 때 화면이 깨지면 안 된다."""
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import save_item
    pid = _new_policy(client, '옛값정책')
    s = client._Session()
    try:
        p = s.get(MarketPolicy, pid)
        # 옛 저장분 흉내 — 스키마 검사를 거치지 않고 값만 넣는다
        from lemouton.policy.models import MarketPolicyValue
        import json
        s.add(MarketPolicyValue(policy_id=pid, market='smartstore', field_key='price',
                                value=json.dumps({'mode': 'margin_rate', 'margin_rate': 9})))
        s.commit()
    finally:
        s.close()
    r = client.get(f'/policies/{pid}?m=smartstore')
    assert r.status_code == 200
    assert '소싱품' in r.get_data(as_text=True)


# ── 「상품 정책 적용」 하위탭 (노션 하위탭 ②) ────────────────────────────

def _model(client, code, brand='르무통'):
    """※ Model.brand 는 **기본값이 '르무통'** 이고 NOT NULL 이다
    (lemouton/sourcing/models.py:47) — 브랜드 없는 상품을 만들려면 빈 문자열을 준다."""
    from lemouton.sourcing.models import Model
    s = client._Session()
    try:
        s.add(Model(model_code=code, model_name_raw=code, brand=brand))
        s.commit()
    finally:
        s.close()


def test_적용_화면이_열린다(client):
    r = client.get('/policies/apply')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert '상품 정책 적용' in body
    assert '① 상품 고르기' in body
    assert '② 정책 고르기' in body


def test_적용_화면에_정책이_나온다(client):
    _new_policy(client, '적용용정책', brand='르무통')
    body = client.get('/policies/apply').get_data(as_text=True)
    assert '적용용정책' in body


def test_정책은_하나만_고를_수_있다(client):
    """상품 하나에 정책 하나 — 여러 개를 고르게 하면 거짓 기능이 된다."""
    _new_policy(client, '라디오확인')
    body = client.get('/policies/apply').get_data(as_text=True)
    assert 'type="radio" name="pol"' in body


def test_갈아끼움_경고가_있다(client):
    body = client.get('/policies/apply').get_data(as_text=True)
    assert '갈아 끼워집니다' in body


def test_상품목록_API가_브랜드_수를_준다(client):
    _model(client, 'M1', '르무통')
    _model(client, 'M2', '르무통')
    _model(client, 'M3', '나이키')
    _model(client, 'M4', '')
    j = client.get('/api/policies/bundles').get_json()
    assert j['ok'] and j['total'] == 4
    got = {b['name']: b['count'] for b in j['brands']}
    assert got == {'르무통': 2, '나이키': 1, '': 1}


def test_상품목록_브랜드로_걸러낸다(client):
    _model(client, 'M1', '르무통')
    _model(client, 'M2', '나이키')
    j = client.get('/api/policies/bundles?brand=르무통').get_json()
    assert [r['model_code'] for r in j['rows']] == ['M1']


def test_브랜드_없는_상품만_걸러낸다(client):
    _model(client, 'M1', '르무통')
    _model(client, 'M2', '')
    j = client.get('/api/policies/bundles?brand=__none__').get_json()
    assert [r['model_code'] for r in j['rows']] == ['M2']


def test_브랜드_개수는_걸러낸_뒤에도_안_흔들린다(client):
    """단추를 누를 때마다 개수가 바뀌면 무엇을 고른 건지 알 수 없다."""
    _model(client, 'M1', '르무통')
    _model(client, 'M2', '나이키')
    j = client.get('/api/policies/bundles?brand=르무통').get_json()
    got = {b['name']: b['count'] for b in j['brands']}
    assert got == {'르무통': 1, '나이키': 1}


def test_지금_붙은_정책이_보인다(client):
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import apply_to
    _model(client, 'M1', '르무통')
    pid = _new_policy(client, '붙은정책')
    s = client._Session()
    try:
        apply_to(s, policy=s.get(MarketPolicy, pid), model_codes=['M1'])
        s.commit()
    finally:
        s.close()
    j = client.get('/api/policies/bundles').get_json()
    assert j['rows'][0]['policy'] == '붙은정책'


def test_사이드바에_상품_정책_적용이_있다(client):
    body = client.get('/policies').get_data(as_text=True)
    assert '/policies/apply' in body
