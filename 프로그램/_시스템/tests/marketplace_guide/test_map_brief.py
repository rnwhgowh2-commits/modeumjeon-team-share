# -*- coding: utf-8 -*-
"""map-brief — 마켓 1개=마크다운 1장(전수정독 브리핑). SOT 조립·날조 금지 검증."""
import pathlib

import pytest
from flask import Flask

from webapp.routes import marketplace_guide as mg
from webapp.marketplace_api_map import load_map

MARKETS = [m["id"] for m in load_map()["markets"]]
REQUIRED = ["## 1. 개발환경", "## 2. API 카탈로그", "## 3. 정산 계산",
            "## 4. 주문상태 전환", "## 5. 통일 주문상태 전이",
            "## 6. 공식 문서 수집법", "## 7. 과거이력",
            "## 8. 어댑터 프로파일", "## 9. 요약"]


@pytest.mark.parametrize("mid", MARKETS)
def test_brief_has_all_sections(mid):
    from webapp.market_brief import build_brief
    md = build_brief(mid)
    assert md, mid
    for s in REQUIRED:
        assert s in md, f"{mid}: {s} 누락"


def test_brief_unknown_market_is_none():
    from webapp.market_brief import build_brief
    assert build_brief("nope") is None


def test_brief_api_count_matches_sot():
    from webapp.market_brief import build_brief
    data = load_map()
    for mid in MARKETS:
        n = sum(1 for a in data["apis"] if a["market"] == mid)
        assert f"{n}개" in build_brief(mid), mid


def test_brief_no_fabrication_markers():
    # 미접수 마켓(auction)의 정산·주문상태 섹션 본문에 '확인불가'가 실제로 찍히는지(프리앰블 아님)
    from webapp.market_brief import build_brief
    md = build_brief("auction")
    sec3 = md.split("## 3.")[1].split("## 4.")[0]
    sec4 = md.split("## 4.")[1].split("## 5.")[0]
    assert "확인불가" in sec3
    assert "확인불가" in sec4


def test_brief_default_is_compact():
    from webapp.market_brief import build_brief
    compact = build_brief("smartstore")
    full = build_brief("smartstore", full=True)
    assert len(full) > len(compact)
    assert len(compact) < 600_000, f"축약 브리핑이 너무 큼: {len(compact)}"
    assert "생략 — ?full=1" in compact


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(mg.__file__).parents[2].as_posix())
    app.register_blueprint(mg.bp)
    return app.test_client()


def test_brief_route(client):
    r = client.get("/marketplace-guide/map-brief?market=coupang")
    assert r.status_code == 200
    assert "text/markdown" in r.headers.get("Content-Type", "")
    assert "## 2. API" in r.get_data(as_text=True)
    assert client.get("/marketplace-guide/map-brief?market=nope").status_code == 404
