# -*- coding: utf-8 -*-
"""폴리시 — 팝업 160% 확대 + 진입 버튼 흰 카드 통일 잠금."""
import pathlib

from webapp.routes import marketplace_guide as mg

TPL = pathlib.Path(mg.__file__).parents[1] / "templates"


def test_popup_enlarged_160():
    assert "zoom:1.6" in (TPL / "marketplace_guide" / "add.html").read_text(encoding="utf-8")
    assert "zoom:1.6" in (TPL / "marketplace_guide" / "map.html").read_text(encoding="utf-8")


def test_manual_buttons_unified_white():
    html = (TPL / "accounts" / "upload.html").read_text(encoding="utf-8")
    # 옛 네이비 「데이터 코드 지도」 버튼 스타일 제거 → 두 버튼 흰 카드로 통일
    assert "background:#0A2540;border:1px solid #0A2540" not in html
    # 두 진입 버튼은 유지
    assert 'data-guide-modal="/marketplace-guide/add?bare=1"' in html
    assert 'data-guide-modal="/marketplace-guide/map?bare=1"' in html
