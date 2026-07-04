# -*- coding: utf-8 -*-
"""accounts/upload.html — 판매처 매뉴얼 진입 버튼 + 모달 기구 include."""
import pathlib

from webapp.routes import marketplace_guide as mg

UPLOAD = pathlib.Path(mg.__file__).parents[1] / "templates" / "accounts" / "upload.html"


def _html():
    return UPLOAD.read_text(encoding="utf-8")


def test_add_button():
    html = _html()
    assert 'data-guide-modal="/marketplace-guide/add?bare=1"' in html
    assert "판매처 추가·업데이트" in html


def test_map_button():
    html = _html()
    assert 'data-guide-modal="/marketplace-guide/map?bare=1"' in html
    assert "데이터 코드 지도" in html


def test_page_modal_included():
    html = _html()
    assert "sourcing_guide/_page_modal.html" in html
