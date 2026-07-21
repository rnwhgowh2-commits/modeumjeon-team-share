# -*- coding: utf-8 -*-
"""폴리시 — 팝업 160% 확대 + 진입 버튼 흰 카드 통일 잠금."""
import pathlib

from webapp.routes import marketplace_guide as mg

TPL = pathlib.Path(mg.__file__).parents[1] / "templates"


def test_popup_enlarged_160():
    # 위저드(add)는 입력칸 중심이라 160% 확대 유지.
    assert "zoom:1.6" in (TPL / "marketplace_guide" / "add.html").read_text(encoding="utf-8")


def test_datamap_fits_popup_width():
    # map(데이터 코드 지도)은 마켓 가로탭+좌영역탭+2열로 넓고 조밀 → 1560px 넓은 팝업(.gpm.wide)에서
    # 158%로 통째 확대하되 max-width 를 950(≈1501/1.58)으로 잡아 렌더 폭 ≈1500px 안에 들어가게 한다.
    html = (TPL / "marketplace_guide" / "map.html").read_text(encoding="utf-8")
    assert "zoom:1.6" not in html       # 160%는 가로 스크롤 → 금지
    assert "zoom:1.58" in html          # 158% 확대(사용자 선택)
    assert "max-width:950px" in html    # 950*1.58≈1501 → 1560px 넓은 팝업 안에 들어감


def test_manual_buttons_unified_white():
    html = (TPL / "accounts" / "upload.html").read_text(encoding="utf-8")
    # 옛 네이비 「데이터 코드 지도」 버튼 스타일 제거 → 두 버튼 흰 카드로 통일
    assert "background:#0A2540;border:1px solid #0A2540" not in html
    # 두 진입 버튼은 유지
    assert 'data-guide-modal="/marketplace-guide/add?bare=1"' in html
    assert 'data-guide-modal="/marketplace-guide/map?bare=1"' in html
