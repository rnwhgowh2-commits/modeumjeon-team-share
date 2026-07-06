# -*- coding: utf-8 -*-
"""주문·정산·문의반품·신규등록 탭 — 5번 레이아웃(요약+표) · 안전 OFF(연결됨·검증대기)."""
import pathlib

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from flask import Flask

from webapp.routes import orders as om
from lemouton.markets import capabilities as cap

TPL = pathlib.Path(om.__file__).parents[1] / "templates"


def _render(tab, live_enabled=False):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(str(TPL)),
    ]))
    cfg = om.TAB_CONFIG.get(tab)
    rows = [] if (live_enabled or not cfg) else cfg["rows"]
    export_markets = ["smartstore"] if tab == "list" else []
    return env.get_template("orders/index.html").render(
        tab=tab, subtabs=om.SUBTABS, active="orders_" + tab,
        cfg=cfg, live_enabled=live_enabled, rows=rows,
        export_markets=export_markets)


def _client():
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    return app.test_client()


def test_extra_gate_default_off(monkeypatch):
    monkeypatch.delenv("LEMOUTON_MARKET_EXTRA", raising=False)
    assert cap.market_extra_enabled() is False


def test_four_dashboard_tabs_configured():
    for t in ["list", "sales", "cs", "register"]:
        c = om.TAB_CONFIG[t]
        assert c["kpis"] and c["cols"] and c["rows"]


@pytest.mark.parametrize("tab,kpi,col", [
    ("list", "신규주문", "주문번호"),
    ("sales", "정산 예정", "정산 예정액"),
    ("cs", "미답변 문의", "내용"),
    ("register", "등록 대기", "카테고리"),
])
def test_tab_renders_layout(tab, kpi, col):
    html = _render(tab)
    assert kpi in html, kpi
    assert col in html, col
    assert "안전 OFF" in html                  # 게이트 OFF 배너
    assert "쿠팡" in html and "스마트스토어" in html


def test_action_button_disabled_when_off():
    html = _render("list")
    assert "disabled" in html                   # 송장입력 비활성


def test_live_on_shows_empty_state():
    html = _render("list", live_enabled=True)
    assert "아직 표시할 실데이터가 없어요" in html
    assert "안전 OFF" not in html                # live=on → 배너 숨김


def test_margin_still_placeholder():
    html = _render("margin")
    assert "후속 구현 예정" in html


def test_routes_registered():
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/orders/" in rules
    assert "/orders/export.xlsx" in rules


def test_list_has_export_button_and_settle_column():
    html = _render("list")
    assert "엑셀 내보내기" in html          # 다운로드 버튼
    assert "정산예정금액" in html            # 표에 정산 열
    assert "최근 7일" in html                # 기간 프리셋 칩


def test_export_downloads_xlsx_for_smartstore(monkeypatch):
    monkeypatch.setattr(om._oe, "order_rows",
                        lambda market, days=7, **k: [{"상품명": "코트", "정산예정금액": 100}])
    r = _client().get("/orders/export.xlsx?market=smartstore&days=7")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["Content-Type"]
    assert r.data[:2] == b"PK"                # xlsx(zip) 바이트


def test_export_rejects_unsupported_market():
    # order_rows 가 ValueError → 400 (추측 데이터 안 만듦)
    r = _client().get("/orders/export.xlsx?market=lotteon&days=7")
    assert r.status_code == 400
