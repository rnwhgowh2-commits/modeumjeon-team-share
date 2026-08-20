import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from shared.db import Base
for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models", "lemouton.sets.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass
from lemouton.sets.models import ProductSet, SetProduct
from lemouton.sets import source_update_service as srv


@pytest.fixture
def db():
    eng = create_engine("sqlite://"); Base.metadata.create_all(eng)
    s = Session(eng); yield s; s.close()


def _seed_set(db, model_codes):
    ps = ProductSet(name="테스트셋", model_code=model_codes[0])
    db.add(ps); db.flush()
    for i, mc in enumerate(model_codes):
        db.add(SetProduct(set_id=ps.id, model_code=mc, quantity=1, sort_order=i))
    db.commit(); return ps


def _fake_crawl(calls, ret_by_model):
    def _fn(session, *, model_code, crawlers=None, progress_cb=None):
        calls.append(model_code)
        return ret_by_model.get(model_code, {"total": 0, "ok": 0, "error": 0, "no_crawler": 0, "per_source": {}})
    return _fn


def test_crawls_each_distinct_model(db):
    ps = _seed_set(db, ["MOD_A", "MOD_B"])
    calls = []
    fn = _fake_crawl(calls, {
        "MOD_A": {"total": 2, "ok": 2, "error": 0, "no_crawler": 0, "per_source": {"ssf": {"ok": 2, "error": 0, "no_crawler": 0}}},
        "MOD_B": {"total": 1, "ok": 1, "error": 0, "no_crawler": 0, "per_source": {"ssg": {"ok": 1, "error": 0, "no_crawler": 0}}},
    })
    r = srv.update_set_sources(db, set_id=ps.id, crawlers={}, crawl_fn=fn)
    assert calls == ["MOD_A", "MOD_B"]
    assert r["ok"] is True
    assert r["totals"] == {"total": 3, "ok": 3, "error": 0, "no_crawler": 0}
    assert r["per_source"]["ssf"]["ok"] == 2 and r["per_source"]["ssg"]["ok"] == 1
    assert r["need_extension"] is False
    assert [m["model_code"] for m in r["models"]] == ["MOD_A", "MOD_B"]


def test_dedupes_repeated_model(db):
    ps = _seed_set(db, ["MOD_A", "MOD_A"])
    calls = []
    fn = _fake_crawl(calls, {})
    srv.update_set_sources(db, set_id=ps.id, crawlers={}, crawl_fn=fn)
    assert calls == ["MOD_A"]


def test_need_extension_when_no_crawler(db):
    ps = _seed_set(db, ["MOD_A"])
    calls = []
    fn = _fake_crawl(calls, {
        "MOD_A": {"total": 3, "ok": 1, "error": 0, "no_crawler": 2, "per_source": {"musinsa": {"ok": 0, "error": 0, "no_crawler": 2}}},
    })
    r = srv.update_set_sources(db, set_id=ps.id, crawlers={}, crawl_fn=fn)
    assert r["need_extension"] is True
    assert r["totals"]["no_crawler"] == 2


def test_unknown_set_returns_error(db):
    fn = _fake_crawl([], {})
    r = srv.update_set_sources(db, set_id=99999, crawlers={}, crawl_fn=fn)
    assert r["ok"] is False and "구성" in r["error"]
