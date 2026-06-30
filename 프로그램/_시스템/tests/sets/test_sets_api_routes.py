"""sets_api 라우트 등록 스모크 — Flask url_map 검증(오프라인, DB 호출 없음)."""
from flask import Flask

from webapp.routes.sets_api import bp


def _rules():
    app = Flask(__name__)
    app.register_blueprint(bp)
    return {r.rule for r in app.url_map.iter_rules()}


def test_blueprint_registers_expected_routes():
    rules = _rules()
    expected = {
        "/api/sets/flow",
        "/api/sets/dashboard",
        "/api/sets/linked",
        "/api/sets/<int:set_id>/detail-matrix",
        "/api/sets/channel/<int:channel_id>/preview",
        "/api/sets/channel/<int:channel_id>/send",
        "/api/sets/<int:set_id>/recrawl-sources",
        "/api/sets/<int:set_id>/history",
        "/api/sets/<int:set_id>/alerts",
        "/api/sets/bundle/<code>/options",
        "/api/sets/upload-accounts",
        "/api/sets/search-bundles",
        "/api/sets",
        "/api/sets/<int:set_id>",
        "/api/sets/<int:set_id>/options",
        "/api/sets/<int:set_id>/channels",
        "/api/channels/<int:channel_id>/product",
        "/api/channels/<int:channel_id>",
        "/api/channels/<int:channel_id>/link",
    }
    missing = expected - rules
    assert not missing, f"라우트 누락: {missing}"


def test_blueprint_name():
    assert bp.name == "sets_api"
