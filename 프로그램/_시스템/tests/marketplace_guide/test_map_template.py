# -*- coding: utf-8 -*-
"""map.html — 흐름 4층·두 갈래·SOP·코드위치·리스크 검증."""
import pathlib

from webapp.routes import marketplace_guide as mg

TPL = pathlib.Path(mg.__file__).parents[1] / "templates" / "marketplace_guide"


def _map():
    return (TPL / "map.html").read_text(encoding="utf-8")


def test_flow_four_layers():
    html = _map()
    for node in ["프로그램", "전송 대기", "판매처 API", "마켓 반영"]:
        assert node in html


def test_two_branches_explicit():
    html = _map()
    assert "신규 상품" in html and "등록" in html
    assert "기존" in html and "연동" in html


def test_code_map_files():
    html = _map()
    for f in ["uploader/runtime.py", "smartstore", "coupang", "MARKET_METADATA"]:
        assert f in html


def test_risk_integrity():
    html = _map()
    assert "LEMOUTON_LIVE_UPLOAD" in html
    assert "0원" in html or "재고" in html


def test_design_tokens():
    html = _map()
    assert "Pretendard" in html and "#191F28" in html
