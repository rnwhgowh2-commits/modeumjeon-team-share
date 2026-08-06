# -*- coding: utf-8 -*-
"""포장 스캔 화면 렌더·진입점 시험.

🔴 「만든 화면을 메뉴에 넣는 걸 빼먹어 두 달간 주소를 직접 쳐야 했다」는 이 저장소의
   실제 이력이다. 화면이 열리는 것과 **들어갈 길이 있는 것**을 같이 못 박는다.
"""
import os

import pytest


@pytest.fixture(scope="module")
def client():
    saved = {k: os.environ.get(k) for k in ("ENVIRONMENT", "DISABLE_AUTH")}
    os.environ["ENVIRONMENT"] = "team-share-dev"
    os.environ["DISABLE_AUTH"] = "1"
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_화면이_열린다(client):
    r = client.get("/mobile/scan-ship")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # 로컬 번들 스캔 엔진을 쓴다(CDN 의존 금지 — 2026-08-05 확정)
    for needle in ["vendor/zxing-browser-0.1.5.min.js",
                   "vendor/zbar-wasm-inlined-0.10.1.js",
                   "js/scan_engine.js", "ScanEngine.start"]:
        assert needle in html, needle
    assert "unpkg.com" not in html and "jsdelivr.net" not in html
    # 서버 API 를 부른다
    assert "/mobile/api/scan-orders" in html
    assert "/mobile/api/scan-ship" in html


def test_홈에서_들어갈_길이_있다(client):
    """주소를 직접 쳐야 하는 화면을 만들지 않는다."""
    r = client.get("/mobile")
    assert r.status_code == 200
    assert "/mobile/scan-ship" in r.get_data(as_text=True)


def test_경고를_화면이_띄우게_되어_있다(client):
    """서버가 준 warning 을 조용히 버리면 장부가 실물과 어긋난 채 굳는다."""
    html = client.get("/mobile/scan-ship").get_data(as_text=True)
    assert "j.warning" in html
