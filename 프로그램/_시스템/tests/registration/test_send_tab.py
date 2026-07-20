# -*- coding: utf-8 -*-
"""대량등록 ③ 데이터전송 탭 — 게이트 요약 + 마켓별 열 + 속도 제한 표기.

시안 12 ③-B안. 사장님 확정: "B. 마켓별 열 · 업로드수 X초 X개 마켓별 수기 설정"
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


# ── 탭 등록 ─────────────────────────────────────────────────────

def test_세_탭이_수집_가공_전송_순서다():
    from webapp.routes.bulk import SUBTABS
    keys = [t['key'] for t in SUBTABS]
    for k in ('collect', 'process', 'send'):
        assert k in keys
    assert keys.index('collect') < keys.index('process') < keys.index('send')


def test_전송_페이지가_200(client):
    r = client.get('/bulk/?tab=send')
    assert r.status_code == 200
    assert 'sd-root' in r.get_data(as_text=True)


# ── 요약 API ────────────────────────────────────────────────────

def test_요약_API가_형태를_준다(client):
    j = client.get('/bulk/api/send/summary').get_json()
    assert 'gate' in j and 'markets' in j and 'limits' in j
    assert 'uploaded' in j['gate'] and 'skipped' in j['gate']


def test_마켓_순서가_사장님_우선순위다(client):
    """스스 → 쿠팡 → 롯데온 → 11번가."""
    ms = [m['market'] for m in client.get('/bulk/api/send/summary').get_json()['markets']]
    order = [m for m in ms if m in ('smartstore', 'coupang', 'lotteon', 'eleven11')]
    assert order[:4] == ['smartstore', 'coupang', 'lotteon', 'eleven11']


def test_마켓마다_속도_제한_문구가_있다(client):
    for m in client.get('/bulk/api/send/summary').get_json()['markets']:
        assert m['rate']['text'], f"{m['market']} 속도 문구가 비었다"


def test_계정이_없으면_보낼_수_없다고_말한다(client):
    """0 을 '무제한'으로 뒤집으면 사고다 — 계정이 없으면 보낼 수단이 없는 것이다."""
    ms = client.get('/bulk/api/send/summary').get_json()['markets']
    for m in ms:
        if m['accounts'] == 0:
            assert m['rate']['no_account'] is True
            assert '보낼 수 없음' in m['rate']['text']


# ── 🔴 초당 1개 상한을 화면이 알아야 한다 ────────────────────────

def test_마켓_API_한도를_같이_준다(client):
    """실제 속도 = 계정 합산과 마켓 한도 중 느린 쪽. 화면이 둘 다 알아야 설명할 수 있다."""
    for m in client.get('/bulk/api/send/summary').get_json()['markets']:
        assert 'market_limit_known' in m['rate']
        assert m['rate']['bound_by'] in ('account', 'market', 'no_account')


def test_확인된_마켓은_한도가_들어있다(client):
    """조사 확인분 — 쿠팡 1초에 5개(게이트웨이 한도). 시드가 안 돌면 여기서 잡힌다.

    2026-07-19 교정: 「60초에 50개」로 넣었었는데 그건 로켓그로스 주문조회 하나의
    한도였다. 업로드는 다른 API 라 게이트웨이 5 req/s 가 맞다.
    """
    ms = {m['market']: m for m in client.get('/bulk/api/send/summary').get_json()['markets']}
    cp = ms.get('coupang')
    if cp:
        assert cp['rate']['market_limit_known'] is True
        assert cp['rate']['market_limit'] == '1초에 5개'


def test_미확인_마켓은_미확인이라고_말한다(client):
    """모르는 걸 '무제한'으로 두면 나중에 그게 확인값인 줄 안다."""
    ms = {m['market']: m for m in client.get('/bulk/api/send/summary').get_json()['markets']}
    ss = ms.get('smartstore')
    if ss:
        assert ss['rate']['market_limit_known'] is False


def test_페이지에_두겹_설명이_들어간다(client):
    html = client.get('/bulk/?tab=send').get_data(as_text=True)
    assert '둘 중 느린 쪽' in html
    assert '미확인' in html


# ── 기존 탭이 안 깨진다 ─────────────────────────────────────────

def test_다른_탭들이_그대로_동작한다(client):
    assert 'pp-root' in client.get('/bulk/?tab=process').get_data(as_text=True)
    assert 'collect-root' in client.get('/bulk/?tab=collect').get_data(as_text=True)
    assert 'bulk-manual-form' in client.get('/bulk/?tab=manual').get_data(as_text=True)
