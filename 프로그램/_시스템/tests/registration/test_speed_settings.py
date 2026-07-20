"""업로드 속도 수기 설정 — 마켓 한도 · 계정별 「X초에 Y개」.

사장님 확정(2026-07-19): "계정별로 X초에 Y개. 그리고 판매처 마켓별로도
API 전송 고려해서 수기로 수정 가능해야 함."

저장 함수(set_market_rate·set_account_rate)는 있었는데 **부르는 곳이 없어서**
손으로 고칠 방법이 아예 없었다. 2026-07-20 배선.
"""
import uuid

import pytest

from lemouton.sourcing.models_v2 import UploadAccount
from shared.db import SessionLocal


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def account():
    """테스트용 업로드 계정 — 끝나면 지운다(개발 DB 오염 방지)."""
    key = f"_t_speed_{uuid.uuid4().hex[:8]}"
    s = SessionLocal()
    try:
        a = UploadAccount(account_key=key, display_name=key, market="lotteon",
                          env_prefix=key.upper(), is_active=True)
        s.add(a)
        s.commit()
        aid = a.id
    finally:
        s.close()
    yield aid
    s = SessionLocal()
    try:
        from lemouton.pricing.settings import AccountUploadPolicy
        p = s.get(AccountUploadPolicy, aid)
        if p is not None:
            s.delete(p)
        row = s.get(UploadAccount, aid)
        if row is not None:
            s.delete(row)
        s.commit()
    finally:
        s.close()


def _get(client):
    r = client.get('/bulk/api/settings/speed')
    assert r.status_code == 200, r.data[:300]
    return {m['market']: m for m in r.get_json()['markets']}


# ── 읽기 ────────────────────────────────────────────────────────

def test_마켓별로_한도와_계정이_보인다(client, account):
    ms = _get(client)
    assert '쿠팡' == ms['coupang']['label']
    assert ms['coupang']['market_limit']['text'] == '1초에 5개'
    assert any(a['account_id'] == account for a in ms['lotteon']['accounts'])


def test_미확인_마켓은_한도가_None(client):
    """모르는 걸 숫자로 채우면 확인된 값인 줄 알게 된다."""
    assert _get(client)['smartstore']['market_limit'] is None


def test_순차필수_여부도_같이_준다(client):
    ms = _get(client)
    assert ms['eleven11']['must_be_sequential'] is True
    assert ms['eleven11']['account_workers'] == 1
    assert ms['coupang']['must_be_sequential'] is False


# ── 마켓 한도 수기 저장 ─────────────────────────────────────────

def test_마켓_한도를_고칠_수_있다(client):
    try:
        r = client.post('/bulk/api/settings/speed',
                        json={'market': 'coupang', 'window_seconds': 2,
                              'max_count': 7})
        assert r.status_code == 200, r.data[:300]
        assert _get(client)['coupang']['market_limit']['text'] == '2초에 7개'
    finally:      # 원래 값(게이트웨이 한도)으로 되돌린다
        client.post('/bulk/api/settings/speed',
                    json={'market': 'coupang', 'window_seconds': 1, 'max_count': 5})


# ── 계정 속도 수기 저장 ─────────────────────────────────────────

def test_계정_속도를_고칠_수_있다(client, account):
    r = client.post('/bulk/api/settings/speed',
                    json={'account_id': account, 'window_seconds': 3,
                          'max_count': 4})
    assert r.status_code == 200, r.data[:300]
    acc = [a for a in _get(client)['lotteon']['accounts']
           if a['account_id'] == account][0]
    assert acc['text'] == '3초에 4개'


# ── 🔴 잘못된 입력은 DB 를 안 건드린다 ──────────────────────────

def test_둘_다_보내면_거부(client, account):
    """어느 쪽을 고쳤는지 모호한 요청을 통과시키면 안 된다."""
    r = client.post('/bulk/api/settings/speed',
                    json={'market': 'coupang', 'account_id': account,
                          'window_seconds': 1, 'max_count': 1})
    assert r.status_code == 400


def test_아무것도_안_보내면_거부(client):
    r = client.post('/bulk/api/settings/speed',
                    json={'window_seconds': 1, 'max_count': 1})
    assert r.status_code == 400


def test_숫자가_아니면_거부(client):
    r = client.post('/bulk/api/settings/speed',
                    json={'market': 'coupang', 'window_seconds': '빠르게',
                          'max_count': 5})
    assert r.status_code == 400


def test_0개는_거부(client):
    """0개 = 아무것도 못 보냄. 저장되면 전송이 조용히 멈춘다."""
    r = client.post('/bulk/api/settings/speed',
                    json={'market': 'coupang', 'window_seconds': 1,
                          'max_count': 0})
    assert r.status_code == 400
    assert _get(client)['coupang']['market_limit']['text'] == '1초에 5개'


# ── 「미확인」으로 되돌리기 ──────────────────────────────────────

def test_마켓_한도를_비우면_미확인으로_돌아간다(client):
    """한 번 넣은 숫자를 못 지우면, 나중에 그게 확인된 값인 줄 알고 쓰게 된다."""
    assert _get(client)['lotteon']['market_limit'] is None      # 원래 미확인
    r = client.post('/bulk/api/settings/speed',
                    json={'market': 'lotteon', 'window_seconds': 2, 'max_count': 3})
    assert r.status_code == 200
    assert _get(client)['lotteon']['market_limit']['text'] == '2초에 3개'

    r = client.post('/bulk/api/settings/speed',
                    json={'market': 'lotteon', 'window_seconds': None,
                          'max_count': None})
    assert r.status_code == 200, r.data[:300]
    assert _get(client)['lotteon']['market_limit'] is None


def test_원래_없던_걸_비워도_괜찮다(client):
    r = client.post('/bulk/api/settings/speed',
                    json={'market': 'smartstore', 'window_seconds': None,
                          'max_count': None})
    assert r.status_code == 200
    assert _get(client)['smartstore']['market_limit'] is None


def test_계정_속도는_비울_수_없다(client, account):
    """계정에는 '미확인'이 없다 — 비우면 속도가 사라진 게 아니라 모호해진다."""
    r = client.post('/bulk/api/settings/speed',
                    json={'account_id': account, 'window_seconds': None,
                          'max_count': None})
    assert r.status_code == 400


def test_없는_계정은_404(client):
    r = client.post('/bulk/api/settings/speed',
                    json={'account_id': 99999999, 'window_seconds': 1,
                          'max_count': 1})
    assert r.status_code == 404
