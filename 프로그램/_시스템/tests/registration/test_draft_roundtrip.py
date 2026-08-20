# -*- coding: utf-8 -*-
"""수기 입력값이 정말 저장되는지 — 왕복 회귀.

■ 왜 이 테스트가 생겼나
  백로그에 「대량등록 수기 입력값·표면가가 저장되지 않음 (미리보기 전용)」이 오래 남아
  있었다. 2026-07-19 확인해 보니 **이미 저장되고 있었다**(Phase 1B M2 에서 고쳐졌는데
  항목이 안 닫힘). 다시 "저장 안 된다"고 오해하지 않도록 왕복을 테스트로 박는다.

■ final_purchase_price 는 일부러 저장하지 않는다
  최종매입가는 소싱처 가격·혜택에서 **매번 계산**하는 값이다(compute_final_price).
  저장해 두면 소싱처가 값을 바꿨을 때 낡은 숫자가 남아 역마진으로 팔린다.
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


_MARK = "왕복테스트"


@pytest.fixture(autouse=True)
def _cleanup_drafts():
    """이 테스트가 만든 드래프트를 지운다 — 개발 DB(SQLite 파일)에 실제로 쓴다.

    안 치우면 실행할 때마다 쌓여 ④상품관리 화면이 테스트 상품으로 도배된다
    (가공정책 때 실제로 19개까지 쌓였다).
    """
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    s = SessionLocal()
    try:
        for d in s.query(ProductDraft).all():
            if d.name and _MARK in d.name:
                s.delete(d)
        s.commit()
    except Exception:       # noqa: BLE001  — 정리 실패가 테스트를 깨뜨리면 안 된다
        s.rollback()
    finally:
        s.close()


def _make(client, **over):
    body = {
        "name": f"{_MARK} 상품", "brand": "나이키", "sale_price": 47900,
        "normal_price": 59000, "surface_price": 33231,
        "options": [{"color": "블랙", "size": "250", "stock": 5}],
    }
    body.update(over)
    r = client.post('/bulk/api/drafts', json=body)
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    return r.get_json()["draft_id"]


def _read(client, did):
    j = client.get(f'/bulk/api/drafts/{did}').get_json()
    return j.get('draft') or j


def test_기본_입력값이_저장된다(client):
    d = _read(client, _make(client))
    assert d["name"] == f"{_MARK} 상품"
    assert d["brand"] == "나이키"
    assert d["sale_price"] == 47900
    assert d["normal_price"] == 59000


def test_표면가가_저장된다(client):
    """백로그가 「표면가가 저장 안 된다」고 적혀 있었다 — 실제로는 저장된다."""
    assert _read(client, _make(client))["surface_price"] == 33231


def test_옵션이_저장된다(client):
    opts = _read(client, _make(client))["options"]
    assert len(opts) == 1
    assert opts[0]["color"] == "블랙"
    assert opts[0]["size"] == "250"
    assert opts[0]["stock"] == 5


def test_최종매입가는_일부러_저장하지_않는다(client):
    """저장하면 소싱처 가격이 바뀌었을 때 낡은 값이 남아 역마진으로 팔린다.

    이 assert 가 깨졌다면 = 누가 최종매입가를 저장하도록 바꿨다는 뜻이다.
    그 자체가 나쁜 건 아니지만, **낡은 값 갱신 경로**가 같이 들어왔는지 반드시 확인할 것.
    """
    assert _read(client, _make(client)).get("final_purchase_price") is None


def test_수정하면_반영된다(client):
    did = _make(client)
    r = client.put(f'/bulk/api/drafts/{did}', json={"sale_price": 51000,
                                                   "surface_price": 35000})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    d = _read(client, did)
    assert d["sale_price"] == 51000
    assert d["surface_price"] == 35000


def test_목록에_뜬다(client):
    did = _make(client)
    j = client.get('/bulk/api/drafts').get_json()
    rows = j.get('drafts') or j.get('rows') or j
    ids = [x.get('id') for x in rows] if isinstance(rows, list) else []
    assert did in ids
