# -*- coding: utf-8 -*-
"""스캔 페이지 렌더 스모크 — 엔진 이관(2026-08-05) 후 Jinja 깨짐·번들 누락 방지."""
import os

import pytest


@pytest.fixture(scope="module")
def client():
    # ★ setdefault 금지 — 다른 테스트 모듈이 ENVIRONMENT 를 선점하면 모바일 BP
    #   미등록으로 전체 실행에서만 실패한다. 강제 설정 + 원복.
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


@pytest.mark.parametrize("path", ["/mobile/scan", "/mobile/scan-batch?mode=in",
                                  "/mobile/scan-batch?mode=out"])
def test_scan_page_renders_with_local_bundles(client, path):
    r = client.get(path)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # 로컬 번들 4종이 걸려 있어야 하고, CDN 잔재가 없어야 한다
    for needle in ["vendor/zxing-browser-0.1.5.min.js",
                   "vendor/zxing-library-0.21.0.min.js",
                   "vendor/zbar-wasm-inlined-0.10.1.js",
                   "js/scan_engine.js"]:
        assert needle in html, f"{path} 에 {needle} 누락"
    assert "unpkg.com" not in html, f"{path} 에 CDN 잔재"
    assert "jsdelivr.net" not in html, f"{path} 에 CDN 잔재"
    assert "ScanEngine.start" in html


def test_vendor_files_served(client):
    for path in ["/static/vendor/zxing-browser-0.1.5.min.js",
                 "/static/vendor/zxing-library-0.21.0.min.js",
                 "/static/vendor/zbar-wasm-inlined-0.10.1.js",
                 "/static/js/scan_engine.js"]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert len(r.data) > 5_000, f"{path} 내용이 비정상적으로 작음"
