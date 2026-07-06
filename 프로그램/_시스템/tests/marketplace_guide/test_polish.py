# -*- coding: utf-8 -*-
"""폴리시 — 팝업 160% 확대 + 진입 버튼 흰 카드 통일 잠금."""
import pathlib

from webapp.routes import marketplace_guide as mg

TPL = pathlib.Path(mg.__file__).parents[1] / "templates"


def test_popup_enlarged_160():
    # 위저드(add)는 입력칸 중심이라 160% 확대 유지.
    assert "zoom:1.6" in (TPL / "marketplace_guide" / "add.html").read_text(encoding="utf-8")


def test_datamap_fits_popup_width():
    # map(데이터 코드 지도)은 마켓 가로탭+좌영역탭+2열로 넓고 조밀 → 1040px 팝업에서
    # 160% 확대는 가로 스크롤을 유발한다. 145%로 통째 확대하되 max-width 를 690(≈1000/1.45)
    # 으로 줄여 렌더 폭 ≈1000px → 1040px 팝업 안에 가로 스크롤 없이 들어가게 한다.
    html = (TPL / "marketplace_guide" / "map.html").read_text(encoding="utf-8")
    assert "zoom:1.6" not in html      # 160%는 가로 스크롤 → 금지
    assert "zoom:1.45" in html         # 145% 확대(사용자 선택)
    assert "max-width:690px" in html   # 690*1.45≈1000 → 1040px 팝업 안에 들어감


def test_manual_buttons_unified_white():
    html = (TPL / "accounts" / "upload.html").read_text(encoding="utf-8")
    # 옛 네이비 「데이터 코드 지도」 버튼 스타일 제거 → 두 버튼 흰 카드로 통일
    assert "background:#0A2540;border:1px solid #0A2540" not in html
    # 두 진입 버튼은 유지
    assert 'data-guide-modal="/marketplace-guide/add?bare=1"' in html
    assert 'data-guide-modal="/marketplace-guide/map?bare=1"' in html
