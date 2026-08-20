# -*- coding: utf-8 -*-
"""① 데이터수집 — 계수 「적용」 버튼 (사장님 4번 = 나).

★ 2단계다. dry_run=True(기본)면 **저장하지 않고** 무엇이 바뀌는지만 돌려준다.
  사람이 확인하고 다시 눌러야 실제로 저장된다 (결정 5-B: 확인 후 적용).
"""
import pytest

_BRAND = "적용테스트브랜드"


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
    from lemouton.sources.models import CrawlWeightRule
    s = SessionLocal()
    try:
        for r in s.query(CrawlWeightRule).all():
            if r.scope_key and _BRAND in str(r.scope_key):
                s.delete(r)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()


def _post(client, **over):
    body = {"source_key": "musinsa", "brand": _BRAND, "weight": 2}
    body.update(over)
    return client.post('/bulk/api/collect/apply', json=body)


# ── 미리보기(dry_run) ───────────────────────────────────────────

def test_기본은_저장하지_않는다(client):
    """실수로 눌러도 아무것도 안 바뀌어야 한다."""
    j = _post(client).get_json()
    assert j["ok"] is True
    assert j["applied"] is False


def test_무엇이_바뀌는지_알려준다(client):
    j = _post(client).get_json()
    assert j["scope_type"] in ("brand", "source")
    assert j["weight"] == 2
    assert _BRAND in j["label"]


def test_브랜드가_없으면_소싱처_전체(client):
    j = _post(client, brand="(브랜드 미지정)").get_json()
    assert j["scope_type"] == "source"
    assert j["scope_key"] == "musinsa"


# ── 실제 적용 ───────────────────────────────────────────────────

def test_dry_run_False면_저장된다(client):
    j = _post(client, dry_run=False).get_json()
    assert j["applied"] is True
    assert j["saved_weight"] == 2


def test_저장한_계수가_규칙에_남는다(client):
    _post(client, dry_run=False, weight=3)
    from shared.db import SessionLocal
    from lemouton.sources.crawl_schedule import list_weight_rules
    s = SessionLocal()
    try:
        assert list_weight_rules(s)["brand"].get(_BRAND) == 3
    finally:
        s.close()


def test_다시_적용하면_덮어쓴다(client):
    _post(client, dry_run=False, weight=2)
    _post(client, dry_run=False, weight=4)
    from shared.db import SessionLocal
    from lemouton.sources.crawl_schedule import list_weight_rules
    s = SessionLocal()
    try:
        assert list_weight_rules(s)["brand"].get(_BRAND) == 4
    finally:
        s.close()


# ── 🔴 위험한 값은 경고를 단다 ──────────────────────────────────

def test_계수0은_크롤제외라고_경고한다(client):
    """실수로 누르면 그 대상이 영영 안 긁힌다."""
    j = _post(client, weight=0).get_json()
    assert j["safe"] is False
    assert "크롤 제외" in j["warning"]


def test_계수는_5로_깎인다(client):
    """스케줄러가 min(5, ...) 로 접는다 — 화면과 실제가 어긋나면 안 된다."""
    assert _post(client, weight=99).get_json()["weight"] == 5


# ── 입력 검증 ───────────────────────────────────────────────────

def test_소싱처가_비면_400(client):
    assert _post(client, source_key="").status_code == 400


def test_계수가_숫자가_아니면_400(client):
    assert _post(client, weight="많이").status_code == 400
