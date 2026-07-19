# -*- coding: utf-8 -*-
"""대량등록 ② 데이터가공 탭 — 라우트·목록 API·정책 추가·상세 페이지.

시안 13 Ⅲ-E안: URL 이 주인공 + 검색/필터 + 정책 추가 버튼(A안)
"""
import uuid

import pytest


def uniq(prefix: str) -> str:
    """정책 이름은 UNIQUE 라 고정 이름을 쓰면 **두 번째 실행부터 400** 이 난다.

    이 라우트 테스트는 개발 DB(SQLite 파일)를 그대로 쓰므로 앞선 실행의 행이 남는다.
    실행마다 다른 이름을 써서 반복 실행에 안전하게 만든다.
    """
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _cleanup_policies():
    """이 파일의 테스트가 만든 정책을 지운다.

    라우트 테스트는 **개발 DB(SQLite 파일)에 실제로 쓴다.** 안 치우면 실행할 때마다
    쓰레기 정책이 쌓이고, 화면의 「소싱처가 안 붙은 정책」 경고가 그걸로 도배된다
    (실제로 19개까지 쌓였다).
    """
    yield
    from shared.db import SessionLocal
    from lemouton.registration.process_policy import ProcessPolicy
    s = SessionLocal()
    try:
        for p in s.query(ProcessPolicy).all():
            if any(p.name.startswith(x) for x in _PREFIXES):
                s.delete(p)
        s.commit()
    except Exception:       # noqa: BLE001  — 정리 실패가 테스트를 깨뜨리면 안 된다
        s.rollback()
    finally:
        s.close()


_PREFIXES = ("추가-", "중복-", "목록확인-", "상세-", "빈정책-", "마켓없는-")


# ── 탭 등록 ─────────────────────────────────────────────────────

def test_데이터가공_탭이_등록되어_있다():
    from webapp.routes.bulk import SUBTABS
    keys = [t['key'] for t in SUBTABS]
    assert 'process' in keys
    assert keys.index('collect') < keys.index('process'), "수집 → 가공 순서여야 한다"


def test_가공_페이지가_200(client):
    r = client.get('/bulk/?tab=process')
    assert r.status_code == 200
    assert 'pp-root' in r.get_data(as_text=True)


# ── 목록 API ────────────────────────────────────────────────────

def test_목록_API가_형태를_준다(client):
    j = client.get('/bulk/api/process/policies').get_json()
    assert 'rows' in j and 'policies' in j and 'counts' in j
    assert len(j['item_labels']) == 13


def test_검색어와_필터를_받는다(client):
    assert client.get('/bulk/api/process/policies?q=nike').status_code == 200
    assert client.get('/bulk/api/process/policies?only=unassigned').status_code == 200


# ── 정책 추가 (A안 버튼) ────────────────────────────────────────

def test_정책을_추가한다(client):
    r = client.post('/bulk/api/process/policies', json={"name": uniq("추가")})
    assert r.status_code == 201
    assert r.get_json()['id']


def test_이름이_비면_400(client):
    r = client.post('/bulk/api/process/policies', json={"name": "  "})
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_같은_이름이면_400과_사유(client):
    nm = uniq("중복")
    client.post('/bulk/api/process/policies', json={"name": nm})
    r = client.post('/bulk/api/process/policies', json={"name": nm})
    assert r.status_code == 400
    assert '이미' in r.get_json()['error']


def test_추가한_정책이_목록에_보인다(client):
    nm = uniq("목록확인")
    client.post('/bulk/api/process/policies', json={"name": nm})
    j = client.get('/bulk/api/process/policies').get_json()
    assert any(p['name'] == nm for p in j['policies'])


# ── 상세 페이지 ─────────────────────────────────────────────────

def test_상세_페이지가_열린다(client):
    nm = uniq("상세")
    pid = client.post('/bulk/api/process/policies',
                      json={"name": nm}).get_json()['id']
    r = client.get(f'/bulk/process/policy/{pid}')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert nm in html
    assert '13항목' in html


def test_없는_정책은_404지만_화면은_설명한다(client):
    """조용한 빈 화면 금지 — 왜 없는지 말해야 한다."""
    r = client.get('/bulk/process/policy/999999')
    assert r.status_code == 404
    assert '없는 정책' in r.get_data(as_text=True)


def test_소싱처가_안_붙은_정책도_알_수_있다(client):
    """URL 중심 목록이라 소싱처 없는 정책은 rows 에 안 나온다.

    그러면 만들어두고 잊은 정책이 영영 안 보인다 — policies 배열의 source_count 로 잡는다.
    """
    nm = uniq("빈정책")
    client.post('/bulk/api/process/policies', json={"name": nm})
    j = client.get('/bulk/api/process/policies').get_json()
    p = next(x for x in j['policies'] if x['name'] == nm)
    assert p['source_count'] == 0
    assert not any(r.get('policy_name') == nm for r in j['rows'])


def test_마켓이_없으면_경고를_띄운다(client):
    """마켓이 안 붙은 정책은 상품이 어디에도 안 올라간다 — 조용히 두면 안 된다."""
    pid = client.post('/bulk/api/process/policies',
                      json={"name": uniq("마켓없는")}).get_json()['id']
    html = client.get(f'/bulk/process/policy/{pid}').get_data(as_text=True)
    assert '어디에도 올라가지 않습니다' in html
