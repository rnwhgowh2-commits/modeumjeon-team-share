# -*- coding: utf-8 -*-
"""2층 계정 설정 저장 API — 「판매처 관리」가 쓰는 창구.

🔴 이 파일이 지키는 것
  ① 「안 정함」과 「0원」을 가른다 — 빈 칸은 NULL, 0 은 0.
  ② 그 마켓에 없는 칸은 **거부**한다 — 오타가 조용히 저장되면 「왜 안 먹지」가 된다.
  ③ 자격증명은 여기로 안 들어온다 — 시크릿 단일 원천은 .env 다.
"""
import os

import pytest

os.environ.setdefault('DISABLE_AUTH', '1')


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """test_policy_routes.py 와 같은 격리 방식 — 라이브 DB 를 건드리지 않는다."""
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


def _account(client, market='coupang', key='르무통_본계'):
    from lemouton.sourcing.models_v2 import UploadAccount
    s = client._Session()
    try:
        acc = UploadAccount(account_key=f'{key}_{market}', display_name=key,
                            market=market, env_prefix=f'{key}_{market}'.upper())
        s.add(acc)
        s.commit()
        return acc.id
    finally:
        s.close()


# ── 저장·조회 왕복 ────────────────────────────────────────────────────────
def test_저장하고_다시_읽는다(client):
    aid = _account(client)
    r = client.post(f'/accounts/api/settings/{aid}',
                    json={'columns': {'as_phone': '0507-1234-5678', 'return_fee': 5000}})
    assert r.status_code == 200 and r.get_json()['ok'] is True

    got = client.get(f'/accounts/api/settings/{aid}').get_json()
    assert got['columns']['as_phone'] == '0507-1234-5678'
    assert got['columns']['return_fee'] == 5000


def test_없는_계정은_404(client):
    assert client.get('/accounts/api/settings/999999').status_code == 404
    assert client.post('/accounts/api/settings/999999', json={}).status_code == 404


# ── 🔴 안 정함 vs 0원 ────────────────────────────────────────────────────
def test_빈_칸은_안_정함으로_저장된다(client):
    """화면에서 칸을 비우는 게 「안 정함으로 되돌리기」의 유일한 방법이다."""
    aid = _account(client)
    client.post(f'/accounts/api/settings/{aid}', json={'columns': {'return_fee': 5000}})
    client.post(f'/accounts/api/settings/{aid}', json={'columns': {'return_fee': ''}})

    assert client.get(f'/accounts/api/settings/{aid}').get_json()['columns']['return_fee'] is None


def test_0원은_0으로_저장된다(client):
    """🔴 무료 반품(0원)과 미설정은 다른 뜻이다 — 0 을 비움으로 바꾸면 안 된다."""
    aid = _account(client)
    client.post(f'/accounts/api/settings/{aid}', json={'columns': {'return_fee': 0}})

    assert client.get(f'/accounts/api/settings/{aid}').get_json()['columns']['return_fee'] == 0


def test_안_정한_칸은_null_로_내려온다(client):
    aid = _account(client)
    got = client.get(f'/accounts/api/settings/{aid}').get_json()
    assert got['columns']['return_fee'] is None
    assert got['extra'] == {}


# ── 🔴 허용 키 ───────────────────────────────────────────────────────────
def test_그_마켓_전용칸은_저장된다(client):
    aid = _account(client, market='lotteon', key='르무통_롯데')
    r = client.post(f'/accounts/api/settings/{aid}', json={'extra': {'owhpNo': 'OW1'}})
    assert r.status_code == 200

    assert client.get(f'/accounts/api/settings/{aid}').get_json()['extra']['owhpNo'] == 'OW1'


def test_다른_마켓_칸은_400으로_거부한다(client):
    """🔴 오타·엉뚱한 칸이 조용히 저장되면 「왜 안 먹지」로 한참 헤맨다."""
    aid = _account(client, market='coupang')
    r = client.post(f'/accounts/api/settings/{aid}', json={'extra': {'owhpNo': 'OW1'}})
    assert r.status_code == 400
    assert '쿠팡' in r.get_json()['error']


def test_공통칸_오타도_400(client):
    aid = _account(client)
    r = client.post(f'/accounts/api/settings/{aid}', json={'columns': {'retrunFee': 5000}})
    assert r.status_code == 400
    assert 'retrunFee' in r.get_json()['error']


def test_거부되면_아무것도_저장되지_않는다(client):
    """일부만 저장되면 화면과 실제가 어긋난다."""
    aid = _account(client, market='coupang')
    client.post(f'/accounts/api/settings/{aid}',
                json={'columns': {'return_fee': 5000}, 'extra': {'owhpNo': 'BAD'}})

    got = client.get(f'/accounts/api/settings/{aid}').get_json()
    assert got['extra'] == {}


# ── 화면이 쓸 정보 ───────────────────────────────────────────────────────
def test_그_마켓에서_쓸_수_있는_칸_목록을_알려준다(client):
    """화면이 무슨 칸을 그릴지 서버에 물어본다 — 두 벌로 관리하면 갈린다."""
    aid = _account(client, market='auction', key='르무통_옥션')
    got = client.get(f'/accounts/api/settings/{aid}').get_json()
    assert got['market'] == 'auction'
    assert 'shippingPlaceNo' in got['allowed']
    assert 'owhpNo' not in got['allowed']


def test_자격증명은_이_API_로_안_들어간다(client):
    """🔴 시크릿 단일 원천은 .env — DB 이중 저장 금지."""
    aid = _account(client)
    r = client.post(f'/accounts/api/settings/{aid}', json={'extra': {'secretKey': 'x'}})
    assert r.status_code == 400


# ── [Task 4] 새 계정에 기본 배송비 ────────────────────────────────────────
def test_새_계정을_만들면_기본_배송비가_들어간다(client):
    """사장님 확정 — 반품 5,000(편도) · 교환 10,000(왕복)."""
    r = client.post('/accounts/api/upload/accounts', json={
        'account_key': '르무통_신규_coupang', 'display_name': '르무통 신규',
        'market': 'coupang', 'env_prefix': 'LEMOUTON_NEW_COUPANG',
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    aid = r.get_json()['id']

    got = client.get(f'/accounts/api/settings/{aid}').get_json()
    assert got['columns']['return_fee'] == 5000
    assert got['columns']['exchange_fee'] == 10000


def test_기본값이_안_들어간_칸은_여전히_안_정함이다(client):
    """🔴 기본값을 넣는다고 나머지까지 0 으로 채우면 「안 정함」이 사라진다."""
    r = client.post('/accounts/api/upload/accounts', json={
        'account_key': '르무통_신규2_coupang', 'display_name': '르무통 신규2',
        'market': 'coupang', 'env_prefix': 'LEMOUTON_NEW2_COUPANG',
    })
    aid = r.get_json()['id']

    got = client.get(f'/accounts/api/settings/{aid}').get_json()
    assert got['columns']['as_phone'] is None
    assert got['columns']['jeju_fee'] is None


def test_기존_계정의_안_정한_칸은_안_채운다(client):
    """🔴 나중에 NULL 을 5,000 으로 때우면 「안 정함」이 사라진다."""
    aid = _account(client, key='르무통_기존')
    got = client.get(f'/accounts/api/settings/{aid}').get_json()
    assert got['columns']['return_fee'] is None
