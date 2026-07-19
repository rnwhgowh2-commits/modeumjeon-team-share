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


def test_계정이_없으면_제한없음이라고_말한다(client):
    """0 을 '초당 0개'로 찍으면 '멈춰 있다'로 오해한다 — 사실대로 말해야 한다."""
    ms = client.get('/bulk/api/send/summary').get_json()['markets']
    for m in ms:
        if m['accounts'] == 0:
            assert m['rate']['unlimited'] is True
            assert '제한 없음' in m['rate']['text']


# ── 🔴 초당 1개 상한을 화면이 알아야 한다 ────────────────────────

def test_계정당_초당1개_상한을_알려준다(client):
    """AccountUploadPolicy.seconds_per_item 이 max(1, int) 라 계정 하나는 초당 1개가 최대다.

    이걸 화면이 모르면 「1초에 10개」를 설정했다고 착각한다.
    """
    j = client.get('/bulk/api/send/summary').get_json()
    assert j['limits']['per_account_max_per_second'] == 1
    assert j['limits']['note']


def test_페이지에_상한_설명이_들어간다(client):
    html = client.get('/bulk/?tab=send').get_data(as_text=True)
    assert '초당 1개가 최대' in html


# ── 기존 탭이 안 깨진다 ─────────────────────────────────────────

def test_다른_탭들이_그대로_동작한다(client):
    assert 'pp-root' in client.get('/bulk/?tab=process').get_data(as_text=True)
    assert 'collect-root' in client.get('/bulk/?tab=collect').get_data(as_text=True)
    assert 'bulk-manual-form' in client.get('/bulk/?tab=manual').get_data(as_text=True)
