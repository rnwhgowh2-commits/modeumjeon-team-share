import os
from webapp.routes.guide_sync import load_catalog

APP_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

def test_load_catalog_returns_items():
    items = load_catalog(APP_ROOT)
    assert isinstance(items, list)
    assert any(it.get("id") == "S1" for it in items)

def test_load_catalog_missing_file_returns_empty(tmp_path):
    assert load_catalog(str(tmp_path)) == []
