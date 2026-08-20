# -*- coding: utf-8 -*-
"""대량등록 ④ 상품관리 탭 — 목록 + 상품별 업데이트 ON/OFF.

설계서 §3-2 「4) 상품관리 탭」 — 더망고 대비 우위 항목.
토글 3개는 ProductDraft 에 이미 있다(모델 주석: "Phase 2 상품관리 탭. 컬럼은 지금 만든다").
"""
import pytest

_MARK = "상품관리테스트"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    s = SessionLocal()
    try:
        for d in s.query(ProductDraft).all():
            if d.name and _MARK in d.name:
                s.delete(d)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()


def _make(client, name_suffix=""):
    r = client.post('/bulk/api/drafts', json={
        "name": f"{_MARK}{name_suffix}", "brand": "나이키",
        "sale_price": 47900, "surface_price": 33231,
        "options": [{"color": "블랙", "size": "250", "stock": 5}]})
    assert r.status_code == 200
    return r.get_json()["draft_id"]


def _find(client, did, **params):
    from urllib.parse import urlencode
    url = '/bulk/api/products' + ('?' + urlencode(params) if params else '')
    rows = client.get(url).get_json()["rows"]
    return next((x for x in rows if x["id"] == did), None)


# ── 탭 ──────────────────────────────────────────────────────────

def test_상품관리_탭이_등록되어_있다():
    from webapp.routes.bulk import SUBTABS
    assert 'products' in [t['key'] for t in SUBTABS]


def test_상품관리_페이지가_200(client):
    r = client.get('/bulk/?tab=products')
    assert r.status_code == 200
    assert 'pr-root' in r.get_data(as_text=True)


# ── 목록 ────────────────────────────────────────────────────────

def test_등록한_상품이_목록에_뜬다(client):
    did = _make(client)
    row = _find(client, did)
    assert row is not None
    assert row["brand"] == "나이키"


def test_표면가와_판매가가_같이_보인다(client):
    """원가 감각 없이 판매가만 보면 역마진을 못 알아챈다."""
    row = _find(client, _make(client))
    assert row["surface_price"] == 33231
    assert row["sale_price"] == 47900


def test_토글은_기본_전부_켜짐(client):
    row = _find(client, _make(client))
    assert row["update_product"] and row["update_price"] and row["update_stock"]


def test_검색이_된다(client):
    did = _make(client, " 검색용")
    assert _find(client, did, q="상품관리테스트") is not None


# ── 🔴 토글 ─────────────────────────────────────────────────────

def test_가격_업데이트를_끌_수_있다(client):
    did = _make(client)
    r = client.post(f'/bulk/api/products/{did}/toggle',
                    json={"field": "update_price", "value": False})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    row = _find(client, did)
    assert row["update_price"] is False
    assert row["update_product"] is True, "다른 축은 안 건드려야 한다"
    assert row["update_stock"] is True


def test_껐다_켤_수_있다(client):
    did = _make(client)
    client.post(f'/bulk/api/products/{did}/toggle',
                json={"field": "update_stock", "value": False})
    client.post(f'/bulk/api/products/{did}/toggle',
                json={"field": "update_stock", "value": True})
    assert _find(client, did)["update_stock"] is True


def test_꺼진_상품은_일부꺼짐_필터에_잡힌다(client):
    """의도치 않게 꺼둔 상품을 찾아낼 수 있어야 한다 — 안 그러면 가격이 영영 안 따라간다."""
    did = _make(client)
    client.post(f'/bulk/api/products/{did}/toggle',
                json={"field": "update_price", "value": False})
    assert _find(client, did, only="off") is not None


def test_모르는_항목은_400(client):
    did = _make(client)
    r = client.post(f'/bulk/api/products/{did}/toggle',
                    json={"field": "update_evrything", "value": False})
    assert r.status_code == 400
    assert '모르는 항목' in r.get_json()["error"]


def test_불리언이_아니면_400(client):
    """'false' 문자열을 참으로 읽으면 끈 줄 알았는데 켜져 있게 된다."""
    did = _make(client)
    r = client.post(f'/bulk/api/products/{did}/toggle',
                    json={"field": "update_price", "value": "false"})
    assert r.status_code == 400


def test_없는_상품은_404(client):
    r = client.post('/bulk/api/products/9999999/toggle',
                    json={"field": "update_price", "value": False})
    assert r.status_code == 404


# ── 최종매입가는 목록에 안 싣는다 ───────────────────────────────

def test_목록은_최종매입가를_주지_않는다(client):
    """저장값이 아니라 매번 계산하는 값이다. 300행마다 엔진을 돌리면 화면이 느려진다.

    대신 그 사실을 note 로 알려 화면이 '왜 없지' 하지 않게 한다.
    """
    row = _find(client, _make(client))
    assert "final_purchase_price" not in row
    j = client.get('/bulk/api/products').get_json()
    assert '계산' in j["note"]


# ── 아홉 탭 전부 ────────────────────────────────────────────────

def test_아홉_탭이_모두_열린다(client):
    from webapp.routes.bulk import SUBTABS
    assert len(SUBTABS) == 9
    for t in SUBTABS:
        assert client.get(f"/bulk/?tab={t['key']}").status_code == 200, t['key']
