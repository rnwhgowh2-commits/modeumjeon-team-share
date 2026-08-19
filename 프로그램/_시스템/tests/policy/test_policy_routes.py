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

    # ★ 두 번째 테스트부터는 라우트 모듈들이 **이미 import 돼 있어** 모듈 최상단의
    #   `from shared.db import SessionLocal` 이 첫 앱의 연결을 붙잡고 있다.
    #   shared.db 만 갈아 끼우면 그 사본들은 안 바뀐다 — 지워진 임시 DB 를 보게 되고,
    #   화면이 404 로 뜨는데 테스트 하나만 돌리면 통과해 원인을 찾기 어렵다.
    #   그래서 **옛 SessionLocal 을 들고 있는 모듈을 전부** 갈아 끼운다.
    import sys as _sys
    for _m in list(_sys.modules.values()):
        if _m is None:
            continue
        try:
            if getattr(_m, 'SessionLocal', None) is o_s:
                monkeypatch.setattr(_m, 'SessionLocal', temp_session)
        except Exception:       # noqa: BLE001 — __getattr__ 이 있는 특수 모듈
            pass

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


# ── 「정책 적용」 하위탭 (노션 하위탭 ②) ────────────────────────────────
#   [2026-08-12] 노션 「a. 상품 정책 적용 → 정책 적용」 개명 반영.

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
    assert '정책 적용' in body
    assert '상품 정책 적용' not in body, '옛 이름이 남아 있다'
    # [2026-08-12 확정 D3] 번호는 동그라미 배지로 뺐다 — 글자는 그대로 남는다
    assert '상품 고르기' in body and '정책 고르기' in body
    assert '<span class="stepno">①</span>' in body
    assert '<span class="stepno wait" id="stepno2">②</span>' in body


# ── [2026-08-12 사장님 확정 D3] 「① 상품 → ② 정책」 직렬 느낌 ──────────────
#   노션: 「사용자 입장에서 둘이 병렬 같아서 직렬(순서) 느낌이 나도록 할 것」

def test_상품을_고르기_전에는_정책판이_자고_있다(client):
    """번호만 크게 쓰면 「읽어야」 아는 순서다 — 재워 둬야 읽지 않아도 느껴진다."""
    body = client.get('/policies/apply').get_data(as_text=True)
    assert 'class="ap-col asleep" id="polcol"' in body, '정책 판이 처음부터 깨어 있다'
    assert '왼쪽에서 상품을 먼저 고르면 여기가 깨어납니다' in body


def test_상품을_고르면_정책판이_깨어난다(client):
    """깨우는 자리는 upd() 한 곳뿐이어야 한다 — 흩어 놓으면 한쪽만 안 깨는 상태가 난다."""
    body = client.get('/policies/apply').get_data(as_text=True)
    assert "classList.toggle('asleep', !awake)" in body
    assert 'const awake = n > 0;' in body


def test_자는_동안에도_정책_만들러는_갈_수_있다(client):
    """🔴 판 전체를 막으면 정책이 하나도 없을 때 만들러 갈 길이 사라진다 —
    빈 화면 안내문이 바로 그 단추를 가리키므로, 막으면 안내가 거짓말이 된다."""
    body = client.get('/policies/apply').get_data(as_text=True)
    assert '.ap-col.asleep .ap-list{filter:grayscale(1);pointer-events:none}' in body, \
        '목록만 막아야 한다'
    assert '.ap-col.asleep .ap-bar' not in body, '찾기·만들러 가기 줄까지 막았다'


def test_적용_화면에_정책이_나온다(client):
    _new_policy(client, '적용용정책', brand='르무통')
    body = client.get('/policies/apply').get_data(as_text=True)
    assert '적용용정책' in body


def test_상품고르기_8칸_헤더가_나온다(client):
    body = client.get('/policies/apply').get_data(as_text=True)
    for label in ('NO', '옵션매트릭스', '소싱처', '판매처', '소싱처 수집', '판매처 수집'):
        assert f'<th>{label}</th>' in body or f'<th style="width:30px">{label}</th>' in body


def test_상품고르기_정책상태_필터칩이_나온다(client):
    body = client.get('/policies/apply').get_data(as_text=True)
    assert 'data-applied="yes"' in body
    assert 'data-applied="no"' in body


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


def test_상품목록에_옵션매트릭스_정보가_있다(client):
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.sourcing.models import Option
    _model(client, 'M1', '르무통')
    s = client._Session()
    try:
        s.add(MatrixOption(model_code='M1', kind=KIND_ORIGIN,
                           name='M1 매트릭스', display_no='U20260819-000001'))
        s.add(Option(canonical_sku='M1-BLK-260', model_code='M1',
                     color_code='BLK', size_code='260'))
        s.add(Option(canonical_sku='M1-BLK-270', model_code='M1',
                     color_code='BLK', size_code='270'))
        s.commit()
    finally:
        s.close()
    j = client.get('/api/policies/bundles').get_json()
    row = j['rows'][0]
    assert row['matrix']['name'] == 'M1 매트릭스'
    assert row['matrix']['no'] == 'U20260819-000001'
    assert row['matrix']['sku_count'] == 2


def test_매트릭스_없는_상품은_matrix가_None이다(client):
    _model(client, 'M2', '르무통')
    j = client.get('/api/policies/bundles').get_json()
    assert j['rows'][0]['matrix'] is None


def test_상품목록에_소싱처_연동정보가_있다(client):
    from datetime import datetime, timezone
    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
    from lemouton.sourcing.models import Option
    _model(client, 'M1', '르무통')
    s = client._Session()
    try:
        s.add(Option(canonical_sku='M1-BLK-260', model_code='M1',
                     color_code='BLK', size_code='260'))
        s.flush()
        sp = SourceProduct(site='musinsa', url='https://example.com/1',
                           last_fetched_at=datetime(2026, 8, 19, 13, 0,
                                                     tzinfo=timezone.utc))
        s.add(sp)
        s.flush()
        so = SourceOption(source_product_id=sp.id, color_text='블랙', size_text='260')
        s.add(so)
        s.flush()
        s.add(OptionSourceLink(canonical_sku='M1-BLK-260', source_option_id=so.id))
        s.commit()
    finally:
        s.close()
    j = client.get('/api/policies/bundles').get_json()
    row = j['rows'][0]
    assert '무신사' in row['sourcing']['connected']
    assert row['sourcing']['collected_at'] == '2026-08-19T13:00:00+00:00'


def test_소싱처_연동_없는_상품은_빈_목록이다(client):
    _model(client, 'M2', '르무통')
    j = client.get('/api/policies/bundles').get_json()
    row = j['rows'][0]
    assert row['sourcing']['connected'] == []
    assert row['sourcing']['collected_at'] is None


def test_상품목록에_판매처_연동정보가_있다(client):
    from datetime import datetime, timezone
    from lemouton.sourcing.models import Option
    from lemouton.uploader.models import MarketRegistration
    _model(client, 'M1', '르무통')
    s = client._Session()
    try:
        s.add(Option(canonical_sku='M1-BLK-260', model_code='M1',
                     color_code='BLK', size_code='260'))
        s.add(MarketRegistration(canonical_sku='M1-BLK-260', market='coupang',
                                 market_product_id='12345',
                                 last_success_at=datetime(2026, 8, 19, 13, 20,
                                                          tzinfo=timezone.utc)))
        s.commit()
    finally:
        s.close()
    j = client.get('/api/policies/bundles').get_json()
    row = j['rows'][0]
    assert '쿠팡' in row['selling']['connected']
    assert row['selling']['collected_at'] == '2026-08-19T13:20:00+00:00'


def test_판매처_연동_없는_상품은_빈_목록이다(client):
    _model(client, 'M2', '르무통')
    j = client.get('/api/policies/bundles').get_json()
    row = j['rows'][0]
    assert row['selling']['connected'] == []
    assert row['selling']['collected_at'] is None


def test_필터_정책적용됨만_보여준다(client):
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import apply_to
    _model(client, 'M1', '르무통')
    _model(client, 'M2', '르무통')
    pid = _new_policy(client, '필터정책')
    s = client._Session()
    try:
        apply_to(s, policy=s.get(MarketPolicy, pid), model_codes=['M1'])
        s.commit()
    finally:
        s.close()
    j = client.get('/api/policies/bundles?applied=yes').get_json()
    assert [r['model_code'] for r in j['rows']] == ['M1']


def test_필터_정책미적용만_보여준다(client):
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import apply_to
    _model(client, 'M1', '르무통')
    _model(client, 'M2', '르무통')
    pid = _new_policy(client, '필터정책2')
    s = client._Session()
    try:
        apply_to(s, policy=s.get(MarketPolicy, pid), model_codes=['M1'])
        s.commit()
    finally:
        s.close()
    j = client.get('/api/policies/bundles?applied=no').get_json()
    assert [r['model_code'] for r in j['rows']] == ['M2']


def test_필터_구성단위_정책도_적용됨으로_잡는다(client):
    """SetPolicyLink(구성 단위)로만 붙은 것도 「적용됨」이어야 한다 —
    상품 단위(BundlePolicyLink)만 보면 놓친다."""
    from lemouton.policy.bundles import add_bundle
    from lemouton.sourcing.models import Option
    _model(client, 'M1', '르무통')
    _model(client, 'M2', '르무통')       # 정책 없음 — 필터가 안 걸리면 얘도 같이 나온다
    pid = _new_policy(client, '구성정책')
    s = client._Session()
    try:
        s.add(Option(canonical_sku='M1-BLK-260', model_code='M1',
                     color_code='BLK', size_code='260'))
        s.commit()
        add_bundle(s, model_code='M1', policy_id=pid)
        s.commit()
    finally:
        s.close()
    j = client.get('/api/policies/bundles?applied=yes').get_json()
    assert [r['model_code'] for r in j['rows']] == ['M1']


def test_소싱처_상세_호버카드_API(client):
    from datetime import datetime, timezone
    from lemouton.sourcing.models import BundleRun, Option
    _model(client, 'M1', '르무통')
    s = client._Session()
    try:
        s.add(Option(canonical_sku='M1-BLK-260', model_code='M1',
                     color_code='BLK', size_code='260',
                     color_display='블랙', size_display='260'))
        s.add(BundleRun(model_code='M1', phase='crawl', status='done',
                        started_at=datetime(2026, 8, 19, 13, 0, tzinfo=timezone.utc)))
        s.commit()
    finally:
        s.close()
    j = client.get('/api/policies/product/M1/sourcing-detail').get_json()
    assert j['ok'] is True
    assert j['history'][0]['status'] == 'done'
    assert j['options'][0]['sku'] == 'M1-BLK-260'
    assert 'stock' in j['options'][0]
    assert 'price' in j['options'][0]


def test_소싱처_상세_없는_상품은_404(client):
    r = client.get('/api/policies/product/없음/sourcing-detail')
    assert r.status_code == 404


def test_판매처_상세_호버카드_API(client):
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import apply_to
    from lemouton.sourcing.models import Option
    _model(client, 'M1', '르무통')
    pid = _new_policy(client, '상세정책')
    _fill_common(client, pid)
    s = client._Session()
    try:
        s.add(Option(canonical_sku='M1-BLK-260', model_code='M1',
                     color_code='BLK', size_code='260'))
        s.commit()
        apply_to(s, policy=s.get(MarketPolicy, pid), model_codes=['M1'])
        s.commit()
    finally:
        s.close()
    j = client.get('/api/policies/product/M1/selling-detail').get_json()
    assert j['ok'] is True
    assert any(m['market'] == 'coupang' for m in j['markets'])


def test_판매처_상세_없는_상품은_404(client):
    r = client.get('/api/policies/product/없음/selling-detail')
    assert r.status_code == 404


def test_판매처_상세_이력에_동기화_시각이_있다(client):
    from datetime import datetime, timezone
    from lemouton.sourcing.models import Option
    from lemouton.uploader.models import MarketRegistration
    _model(client, 'M1', '르무통')
    s = client._Session()
    try:
        s.add(Option(canonical_sku='M1-BLK-260', model_code='M1',
                     color_code='BLK', size_code='260'))
        s.add(MarketRegistration(canonical_sku='M1-BLK-260', market='coupang',
                                 market_product_id='1',
                                 last_success_at=datetime(2026, 8, 19, 13, 20,
                                                          tzinfo=timezone.utc)))
        s.commit()
    finally:
        s.close()
    j = client.get('/api/policies/product/M1/selling-detail').get_json()
    hist = {h['market']: h['at'] for h in j['history']}
    assert hist.get('coupang') == '2026-08-19T13:20:00+00:00'
    labels = {h['market']: h['label'] for h in j['history']}
    assert labels.get('coupang') == '쿠팡'


def test_사이드바에_상품_정책_적용이_있다(client):
    body = client.get('/policies').get_data(as_text=True)
    assert '/policies/apply' in body


# ── 상품 상세 「정책 정보」 탭 (노션 F1 · H1) ────────────────────────────

def test_상세_탭_이름이_새_이름이다(client):
    """노션 F1 — 기본·옵션·마켓 → 상품 정보·옵션 정보·정책 정보."""
    _model(client, 'B1', '르무통')
    body = client.get('/bundles/B1').get_data(as_text=True)
    assert '상품 정보' in body
    assert '옵션 정보' in body
    assert '정책 정보' in body


def test_정책_결과_API_붙은_정책이_없으면_안내한다(client):
    _model(client, 'B2', '르무통')
    j = client.get('/api/bundles/B2/policy-result').get_json()
    assert j['ok'] is True
    assert j['policies'] == []
    assert '붙은 정책이 없습니다' in j['reason']


def test_정책_결과_API_가_마켓_6줄을_준다(client):
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import apply_to
    _model(client, 'B3', '르무통')
    pid = _new_policy(client, '결과정책')
    s = client._Session()
    try:
        apply_to(s, policy=s.get(MarketPolicy, pid), model_codes=['B3'])
        s.commit()
    finally:
        s.close()
    j = client.get('/api/bundles/B3/policy-result').get_json()
    assert j['ok'] is True
    assert [p['name'] for p in j['policies']] == ['결과정책']
    assert len(j['rows']) == 6, '마켓 6곳이 다 나와야 한다'
    assert {r['market'] for r in j['rows']} == {
        'smartstore', 'coupang', 'gmarket', 'auction', 'eleven11', 'lotteon'}


def test_마진율_안_정한_마켓은_지어내지_않는다(client):
    """빈칸을 0%로 읽으면 그 가격이 그대로 마켓에 나간다."""
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import apply_to
    _model(client, 'B4', '르무통')
    pid = _new_policy(client, '빈정책')
    s = client._Session()
    try:
        apply_to(s, policy=s.get(MarketPolicy, pid), model_codes=['B4'])
        s.commit()
    finally:
        s.close()
    j = client.get('/api/bundles/B4/policy-result').get_json()
    for r in j['rows']:
        assert r['ready'] is False
        assert r['price'] is None
        assert r['reason'], '왜 못 냈는지 말해야 한다'


# ── [2026-08-12 사장님 확정 B2] 「체크한 마켓만 가공 활성화」 (노션 정책생성 a) ──

def _set_markets(client, pid, markets):
    r = client.post(f'/api/policies/{pid}/markets', json={'markets': markets})
    assert r.status_code == 200, r.get_data(as_text=True)


def test_안_켠_마켓은_흐려지고_자물쇠가_붙는다(client):
    pid = _new_policy(client, '켠것만')
    _set_markets(client, pid, ['smartstore', 'coupang'])
    body = client.get(f'/policies/{pid}').get_data(as_text=True)
    assert 'mkoff' in body, '안 켠 마켓 표시가 없다'
    assert '🔒' in body
    assert '안 켠 마켓입니다' in body


def test_안_켠_마켓도_탭에_남는다(client):
    """🔴 숨기면 거기 채워 둔 값을 다시 고칠 길이 사라진다 —
    껐다 켜면 살아나야 한다는 게 사장님 뜻이라 「없애기」가 아니라 「위상 낮추기」다."""
    pid = _new_policy(client, '탭유지')
    _set_markets(client, pid, ['smartstore'])
    body = client.get(f'/policies/{pid}').get_data(as_text=True)
    for label in ('쿠팡', 'G마켓', '옥션', '11번가', '롯데온'):
        assert label in body, f'{label} 탭이 사라졌다'
    assert f'/policies/{pid}?m=coupang' in body, '꺼진 마켓으로 갈 길이 막혔다'


def test_껐다_켜도_적어_둔_값은_그대로다(client):
    """끄는 것은 「안 쓴다」이지 「지운다」가 아니다."""
    from lemouton.policy.service import values_for
    pid = _new_policy(client, '값보존')
    _fill_common(client, pid)
    client.post(f'/api/policies/{pid}/push', json={'markets': ['coupang']})
    _set_markets(client, pid, ['smartstore'])          # 쿠팡을 끈다
    s = client._Session()
    try:
        assert values_for(s, pid, 'coupang'), '끄는 순간 값이 사라졌다'
    finally:
        s.close()
    _set_markets(client, pid, ['smartstore', 'coupang'])   # 다시 켠다
    s = client._Session()
    try:
        assert values_for(s, pid, 'coupang'), '다시 켰는데 값이 안 돌아왔다'
    finally:
        s.close()


def test_채움_합계는_켠_마켓만_센다(client):
    """🔴 꺼 둔 마켓을 분모에 두면 100% 가 영영 안 찬다 —
    화면은 「할 일이 남았다」고 말하는데 실제로 할 일은 없는 상태가 된다."""
    from lemouton.policy.service import readiness
    pid = _new_policy(client, '합계')
    _set_markets(client, pid, ['smartstore', 'coupang'])
    s = client._Session()
    try:
        rd = readiness(s, pid)
        want = rd['smartstore']['total'] + rd['coupang']['total']
        all_total = sum(v['total'] for v in rd.values())
    finally:
        s.close()
    body = client.get(f'/policies/{pid}').get_data(as_text=True)
    assert f'<b>{want}</b>' in body, f'켠 2곳 합({want})이 안 보인다'
    assert '켠 <b>2</b>곳만 셉니다' in body
    assert all_total != want, '시험이 아무것도 안 보고 있다(켠 것과 전체가 같다)'


def test_전부_켜져_있으면_군더더기_안내가_없다(client):
    """안 켠 곳이 없으면 자물쇠 안내는 군더더기다."""
    pid = _new_policy(client, '전부켬')      # 새 정책 = 안 정함 = 전부 켜짐
    body = client.get(f'/policies/{pid}').get_data(as_text=True)
    assert '안 켠 마켓입니다' not in body
    # 🔴 'mkoff' 로만 보면 안 된다 — 그 낱말은 **CSS 규칙에도 늘 있어서**
    #   마켓이 다 켜져 있어도 잡힌다(이 시험이 실제로 그렇게 헛돌았다).
    #   화면 마크업에만 나오는 자물쇠 조각으로 본다.
    assert '<span class="mklock">' not in body, '켜져 있는데 자물쇠가 붙었다'
    assert '켠 <b>6</b>곳만 셉니다' in body


def test_목록의_가격_쓸_수_있음도_켠_마켓만_센다(client):
    """목록 화면의 「쓸 수 있음 N마켓」이 꺼 둔 곳까지 세면 부풀려 보인다."""
    pid = _new_policy(client, '목록집계')
    _set_markets(client, pid, ['smartstore'])
    body = client.get('/policies').get_data(as_text=True)
    assert '쓸 수 있음 6마켓' not in body, '꺼 둔 마켓까지 셌다'


# ── [2026-08-12 사장님 확정 C2] 마켓 탭에서 바로 켜고 끄기 (더망고 캡처 반영) ──

def test_마켓_탭에_켜고_끄는_체크박스가_있다(client):
    """전에는 켜고 끄려면 정책 목록으로 돌아가야 했다."""
    pid = _new_policy(client, '탭체크')
    body = client.get(f'/policies/{pid}?m=coupang').get_data(as_text=True)
    assert 'id="mkon"' in body
    assert '[쿠팡 정책설정]' in body
    assert '상품정보를 보내지 않습니다' in body


def test_마켓_공통_탭에는_체크박스가_없다(client):
    """「마켓 공통」은 진짜 마켓이 아니라 값을 담아두는 자리다 — 켜고 끌 대상이 아니다."""
    pid = _new_policy(client, '공통엔없음')
    body = client.get(f'/policies/{pid}?m=common').get_data(as_text=True)
    assert 'id="mkon"' not in body


def test_꺼진_마켓은_체크가_풀려_있고_화면이_흐려진다(client):
    pid = _new_policy(client, '꺼짐표시')
    _set_markets(client, pid, ['smartstore'])
    off = client.get(f'/policies/{pid}?m=coupang').get_data(as_text=True)
    assert 'mk-off' in off, '흐리게 만드는 표시가 없다'
    assert 'id="mkon" checked' not in off
    on = client.get(f'/policies/{pid}?m=smartstore').get_data(as_text=True)
    assert 'id="mkon" checked' in on


def test_꺼져_있어도_값을_고칠_수_있다(client):
    """🔴 「흐리게만」이다 — 값이 보이는데 손댈 수 없으면 둘 다 잃는다.
    끄는 것은 「안 보낸다」이지 「못 고친다」가 아니다."""
    pid = _new_policy(client, '꺼져도수정')
    _set_markets(client, pid, ['smartstore'])
    body = client.get(f'/policies/{pid}?m=coupang').get_data(as_text=True)
    assert 'pointer-events:none' not in body.split('.mk-off')[1][:400], '입력을 막았다'
    assert '꺼 둔 동안에도 <b>고칠 수 있습니다.</b>' in body
    # 실제로 저장도 되어야 한다
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import save_item, values_for
    s = client._Session()
    try:
        p = s.get(MarketPolicy, pid)
        save_item(s, policy=p, market='coupang', item_key='price',
                  config={'sourcing_rate': 30})
        s.commit()
        assert values_for(s, pid, 'coupang'), '꺼진 마켓에 저장이 막혔다'
    finally:
        s.close()


def test_체크박스는_켠_마켓_목록을_통째로_보낸다(client):
    """이 마켓만 넣고 빼서 통째로 보낸다 — 화면에서 셈하면 어긋난다."""
    pid = _new_policy(client, '통째전송')
    _set_markets(client, pid, ['smartstore'])
    body = client.get(f'/policies/{pid}?m=coupang').get_data(as_text=True)
    assert "const ENABLED = " in body
    assert "'/api/policies/' + PID + '/markets'" in body
    assert 'ck.checked = !ck.checked' in body, '실패해도 안 되돌린다'
