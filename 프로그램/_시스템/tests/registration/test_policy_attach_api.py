# -*- coding: utf-8 -*-
"""가공정책에 **소싱처 URL·마켓을 붙이는** API.

화면이 「아래 빨간 줄을 정책에 붙여주세요」라고 안내하면서 정작 붙이는 수단이
없었다 — 사장님이 할 수 없는 일을 시키고 있었다. 그 구멍을 메운다.

━━ 규율 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · 조용한 실패 금지 — 저장이 안 됐으면 **사유**가 응답에 실린다.
  · 없는 정책이면 404 — 고아 행(주인 없는 규칙·구성)을 만들지 않는다.
  · 한 구성은 한 정책에만 — 옮길 때는 **사장님이 알고** 옮긴다(조용한 이동 금지).
"""
import uuid

import pytest

_MARK = "붙이기"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _cleanup():
    """이 파일이 만든 정책·구성을 지운다 (라우트 테스트는 개발 DB 에 실제로 쓴다)."""
    yield
    from shared.db import SessionLocal
    from lemouton.registration.process_policy import ProcessPolicy
    s = SessionLocal()
    try:
        for p in s.query(ProcessPolicy).all():
            if p.name and p.name.startswith(_MARK):
                s.delete(p)         # sources·markets·rules 는 cascade 로 같이 지워진다
        s.commit()
    except Exception:               # noqa: BLE001 — 정리 실패가 테스트를 깨뜨리면 안 된다
        s.rollback()
    finally:
        s.close()


def _policy(client, tag=""):
    nm = f"{_MARK}{tag}-{uuid.uuid4().hex[:8]}"
    j = client.post('/bulk/api/process/policies', json={"name": nm}).get_json()
    return j["id"], nm


def _comp():
    """이번 실행에서만 쓰는 구성(소싱처 × 브랜드) — 다른 실행과 안 겹치게."""
    return ("musinsa", f"{_MARK}브랜드-{uuid.uuid4().hex[:8]}")


# ── 소싱처 붙이기 ───────────────────────────────────────────────

def test_소싱처를_정책에_붙인다(client):
    pid, nm = _policy(client)
    sk, br = _comp()
    r = client.post(f'/bulk/api/process/policies/{pid}/sources',
                    json={"source_key": sk, "brand": br, "url": "https://x/y"})
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True and j["policy_name"] == nm
    assert j["moved_from"] is None


def test_붙인_구성이_목록에_정책과_함께_나온다(client):
    """빨간 줄(정책 없음)이 정상 줄로 바뀌는 근거."""
    pid, nm = _policy(client)
    sk, br = _comp()
    client.post(f'/bulk/api/process/policies/{pid}/sources',
                json={"source_key": sk, "brand": br})
    rows = client.get('/bulk/api/process/policies').get_json()["rows"]
    row = next(r for r in rows if r["source_key"] == sk and r["brand"] == br)
    assert row["policy_id"] == pid
    assert row["policy_name"] == nm


def test_같은_정책에_두_번_붙여도_괜찮다(client):
    pid, _ = _policy(client)
    sk, br = _comp()
    body = {"source_key": sk, "brand": br}
    assert client.post(f'/bulk/api/process/policies/{pid}/sources', json=body).status_code == 200
    r = client.post(f'/bulk/api/process/policies/{pid}/sources', json=body)
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_없는_정책에_붙이면_404이고_고아_구성이_안_생긴다(client):
    from lemouton.registration.process_policy import ProcessPolicySource
    from shared.db import SessionLocal

    sk, br = _comp()
    r = client.post('/bulk/api/process/policies/9999999/sources',
                    json={"source_key": sk, "brand": br})
    assert r.status_code == 404
    assert '정책' in r.get_json()["error"]

    s = SessionLocal()
    try:
        assert s.query(ProcessPolicySource).filter(
            ProcessPolicySource.source_key == sk,
            ProcessPolicySource.brand == br).count() == 0
    finally:
        s.close()


def test_소싱처나_브랜드가_비면_400과_사유(client):
    pid, _ = _policy(client)
    r = client.post(f'/bulk/api/process/policies/{pid}/sources',
                    json={"source_key": "", "brand": "나이키"})
    assert r.status_code == 400
    assert r.get_json()["error"]


# ── 🔴 한 구성은 한 정책에만 — 옮길 땐 알린다 ──────────────────

def test_다른_정책에_붙은_구성은_그냥_안_옮긴다(client):
    """조용한 이동 금지 — 어느 정책에 있는지 말하고 되묻는다."""
    pid_a, nm_a = _policy(client, "A")
    pid_b, _ = _policy(client, "B")
    sk, br = _comp()
    client.post(f'/bulk/api/process/policies/{pid_a}/sources',
                json={"source_key": sk, "brand": br})

    r = client.post(f'/bulk/api/process/policies/{pid_b}/sources',
                    json={"source_key": sk, "brand": br})
    assert r.status_code == 409
    j = r.get_json()
    assert j["ok"] is False
    assert j["need_confirm"] is True
    assert j["current_policy"]["id"] == pid_a
    assert j["current_policy"]["name"] == nm_a
    assert nm_a in j["error"]


def test_옮기겠다고_하면_옮기고_어디서_왔는지_알려준다(client):
    pid_a, nm_a = _policy(client, "A")
    pid_b, nm_b = _policy(client, "B")
    sk, br = _comp()
    client.post(f'/bulk/api/process/policies/{pid_a}/sources',
                json={"source_key": sk, "brand": br})

    r = client.post(f'/bulk/api/process/policies/{pid_b}/sources',
                    json={"source_key": sk, "brand": br, "confirm_move": True})
    assert r.status_code == 200
    j = r.get_json()
    assert j["moved_from"] == nm_a
    assert nm_a in j["message"] and nm_b in j["message"]

    rows = client.get('/bulk/api/process/policies').get_json()["rows"]
    row = next(x for x in rows if x["source_key"] == sk and x["brand"] == br)
    assert row["policy_id"] == pid_b          # 두 정책에 동시에 있지 않다
    assert sum(1 for x in rows
               if x["source_key"] == sk and x["brand"] == br) == 1


# ── 소싱처 떼기 ─────────────────────────────────────────────────

def test_소싱처를_뗀다(client):
    pid, _ = _policy(client)
    sk, br = _comp()
    client.post(f'/bulk/api/process/policies/{pid}/sources',
                json={"source_key": sk, "brand": br})
    r = client.delete('/bulk/api/process/sources',
                      json={"source_key": sk, "brand": br})
    assert r.status_code == 200 and r.get_json()["ok"] is True

    rows = client.get('/bulk/api/process/policies').get_json()["rows"]
    assert not any(x["source_key"] == sk and x["brand"] == br
                   and x["policy_id"] is not None for x in rows)


def test_안_붙어_있는_구성을_떼면_404와_사유(client):
    sk, br = _comp()
    r = client.delete('/bulk/api/process/sources',
                      json={"source_key": sk, "brand": br})
    assert r.status_code == 404
    assert r.get_json()["error"]


# ── 마켓 붙이기 ─────────────────────────────────────────────────

def test_마켓을_붙인다(client):
    pid, _ = _policy(client)
    r = client.post(f'/bulk/api/process/policies/{pid}/markets',
                    json={"market": "coupang", "account_key": "본계정"})
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True and j["market"] == "coupang"
    assert j["account_key"] == "본계정"


def test_붙인_마켓이_목록에_보인다(client):
    pid, _ = _policy(client)
    sk, br = _comp()
    client.post(f'/bulk/api/process/policies/{pid}/sources',
                json={"source_key": sk, "brand": br})
    client.post(f'/bulk/api/process/policies/{pid}/markets', json={"market": "smartstore"})
    rows = client.get('/bulk/api/process/policies').get_json()["rows"]
    row = next(x for x in rows if x["source_key"] == sk and x["brand"] == br)
    assert [m["market"] for m in row["markets"]] == ["smartstore"]


def test_모르는_마켓은_400과_사유(client):
    pid, _ = _policy(client)
    r = client.post(f'/bulk/api/process/policies/{pid}/markets', json={"market": "naver"})
    assert r.status_code == 400
    err = r.get_json()["error"]
    assert 'naver' in err and 'coupang' in err          # 무엇이 틀렸고 뭘 쓸 수 있는지


def test_없는_정책에_마켓을_붙이면_404(client):
    r = client.post('/bulk/api/process/policies/9999999/markets',
                    json={"market": "coupang"})
    assert r.status_code == 404


def test_같은_마켓을_두_번_붙여도_괜찮다(client):
    pid, _ = _policy(client)
    body = {"market": "coupang"}
    client.post(f'/bulk/api/process/policies/{pid}/markets', json=body)
    r = client.post(f'/bulk/api/process/policies/{pid}/markets', json=body)
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_마켓을_뗀다(client):
    pid, _ = _policy(client)
    client.post(f'/bulk/api/process/policies/{pid}/markets',
                json={"market": "coupang", "account_key": "본계정"})
    r = client.delete(f'/bulk/api/process/policies/{pid}/markets',
                      json={"market": "coupang", "account_key": "본계정"})
    assert r.status_code == 200 and r.get_json()["ok"] is True

    html = client.get(f'/bulk/process/policy/{pid}').get_data(as_text=True)
    assert '어디에도 올라가지 않습니다' in html      # 다시 마켓 0곳


def test_안_붙어_있는_마켓을_떼면_404(client):
    pid, _ = _policy(client)
    r = client.delete(f'/bulk/api/process/policies/{pid}/markets',
                      json={"market": "coupang"})
    assert r.status_code == 404


# ── 🔴 기존 결함: 없는 정책에도 규칙이 저장됐다 ────────────────

def test_없는_정책에_규칙을_저장하면_404이고_고아_규칙이_안_생긴다(client):
    """[2026-07-24 리뷰 실측] 없는 정책 id 로도 200 이 나고 주인 없는 규칙 행이 남았다."""
    from lemouton.registration.process_policy import ProcessRule
    from shared.db import SessionLocal

    r = client.post('/bulk/api/process/policies/9999999/rules',
                    json={"item_key": "shipping", "config": {"return_fee": 3000}})
    assert r.status_code == 404
    assert '정책' in r.get_json()["error"]

    s = SessionLocal()
    try:
        assert s.query(ProcessRule).filter(ProcessRule.policy_id == 9999999).count() == 0
    finally:
        s.close()


def test_지워진_정책에도_규칙을_저장할_수_없다(client):
    from lemouton.registration.process_policy import ProcessPolicy
    from shared.db import SessionLocal
    from datetime import datetime

    pid, _ = _policy(client)
    s = SessionLocal()
    try:
        s.get(ProcessPolicy, pid).deleted_at = datetime.utcnow()
        s.commit()
    finally:
        s.close()
    r = client.post(f'/bulk/api/process/policies/{pid}/rules',
                    json={"item_key": "shipping", "config": {}})
    assert r.status_code == 404
