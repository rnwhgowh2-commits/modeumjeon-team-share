import os
from webapp.routes.guide_sync import load_catalog, catalog_symbol_drift, shared_code_map, duplicate_ids, catalog_doc_drift

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


def test_shared_code_map_groups_by_symbol():
    items = [
        {"id":"S1","src":"르무통","code":{"file":"a.py","func":"persist"}},
        {"id":"S2","src":"스마트스토어","code":{"file":"a.py","func":"persist"}},
        {"id":"S9","src":"롯데온","code":{"file":"b.py","func":"only"}},
    ]
    out = shared_code_map(items)
    assert out == {"a.py::persist": ["르무통", "스마트스토어"]}

def test_duplicate_ids():
    items = [{"id":"S1"},{"id":"S1"},{"id":"P3"}]
    assert duplicate_ids(items) == ["S1"]


def test_doc_drift_flags_id_absent_in_md():
    md = "표: S1 르무통 ... P3 SSG ..."
    items = [{"id":"S1","rule":False},{"id":"S2","rule":False},{"id":"P3"}]
    assert catalog_doc_drift(md, items) == ["S2"]

def test_doc_drift_skips_rule_rows():
    items = [{"id":None,"rule":True,"sy":"폴백가 금지"}]
    assert catalog_doc_drift("아무 내용", items) == []
