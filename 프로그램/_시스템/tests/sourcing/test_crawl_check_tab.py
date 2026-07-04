import os

import pytest

# webapp/templates 절대 경로 — tests/sourcing/ 에서 ../../webapp/templates
_TMPL_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "webapp", "templates")
)


@pytest.fixture
def client(monkeypatch):
    """sourcing_guide 블루프린트만 띄운 테스트 클라이언트. ENVIRONMENT=test 로 admin 게이트 우회.
    로컬 SQLite 에 테이블이 없는 워크트리 환경을 위해 Base.metadata.create_all() 선행."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    # 모든 모델을 먼저 등록해야 create_all() 이 테이블을 생성한다
    for _m in (
        "lemouton.sourcing.models",
        "lemouton.sourcing.models_pricing",
        "lemouton.sources.models",
        "lemouton.templates.models",
        "lemouton.inventory.models",
        "lemouton.mapping.models",
        "webapp.icon_store_model",
    ):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base, engine, _apply_lightweight_migrations
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()      # [2026-06-30] SourcingSource is_builtin·crawl_guide 보강

    from flask import Flask
    from webapp.routes import sourcing_guide as sg
    app = Flask(__name__, template_folder=_TMPL_DIR)
    app.register_blueprint(sg.bp)
    app.config.update(TESTING=True)
    # base.html / sidebar.html 에서 필요한 컨텍스트 변수 — 테스트 앱에는 context_processor 없으므로
    # 모든 sidebar 변수를 안전한 더미값으로 globals 주입.
    _dummy_mode_icons = {'bundles': {'emoji': '📦', 'color': ''}, 'inventory': {'emoji': '🏷', 'color': ''}}
    app.jinja_env.globals.update(
        sidebar_layout={},
        sidebar_badge_values={'unmapped': 0, 'failed': 0},
        sidebar_mode_icons=_dummy_mode_icons,
        sidebar_unmapped_count=0,
        sidebar_failed_count=0,
    )
    return app.test_client()


def test_crawl_check_full_page_200(client):
    r = client.get("/sourcing-guide/crawl-check")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "재고 정합성 검사" in body
    assert "가격 정합성 검사" in body
    assert "품절둔갑" in body
    assert "999·센티넬" in body
    assert "귀책" in body


def test_crawl_check_bare_sets_sameorigin(client):
    r = client.get("/sourcing-guide/crawl-check?bare=1")
    assert r.status_code == 200
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"


def test_overview_has_crawl_check_card(client):
    r = client.get("/sourcing-guide/")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'data-guide-modal="/sourcing-guide/crawl-check?bare=1"' in body
    assert "크롤링 검사" in body
