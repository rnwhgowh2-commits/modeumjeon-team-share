import os
from webapp.routes.guide_sync import load_catalog, catalog_symbol_drift

APP_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

def test_load_catalog_returns_items():
    items = load_catalog(APP_ROOT)
    assert isinstance(items, list)
    assert any(it.get("id") == "S1" for it in items)

def test_load_catalog_missing_file_returns_empty(tmp_path):
    assert load_catalog(str(tmp_path)) == []


def test_symbol_drift_flags_missing_func(tmp_path):
    import json
    (tmp_path / "webapp" / "static").mkdir(parents=True)
    (tmp_path / "a.py").write_text("def other(): pass", encoding="utf-8")
    cat = {"version":1,"items":[
        {"id":"X1","src":"테스트","crawl":"ok","code":{"file":"a.py","func":"do_real"}},
    ]}
    (tmp_path / "webapp" / "static" / "error_catalog.json").write_text(
        json.dumps(cat), encoding="utf-8")
    out = catalog_symbol_drift(str(tmp_path))
    assert out == [{"id":"X1","func":"do_real","file":"a.py","crawl":"ok"}]

def test_symbol_drift_clean_when_present(tmp_path):
    import json
    (tmp_path / "webapp" / "static").mkdir(parents=True)
    (tmp_path / "a.py").write_text("def do_real(): pass", encoding="utf-8")
    cat = {"version":1,"items":[
        {"id":"X1","src":"t","crawl":"ok","code":{"file":"a.py","func":"do_real"}},
    ]}
    (tmp_path / "webapp" / "static" / "error_catalog.json").write_text(
        json.dumps(cat), encoding="utf-8")
    assert catalog_symbol_drift(str(tmp_path)) == []
