# -*- coding: utf-8 -*-
"""주문 내역 탭 — 5번 레이아웃(요약+표) · 안전 OFF(연결됨·검증대기) 검증."""
import pathlib

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from flask import Flask

from webapp.routes import orders as om
from lemouton.markets import capabilities as cap

TPL = pathlib.Path(om.__file__).parents[1] / "templates"


def _render(tab, **ctx):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(str(TPL)),
    ]))
    base = dict(tab=tab, subtabs=om.SUBTABS, active="orders_" + tab)
    base.update(ctx)
    return env.get_template("orders/index.html").render(**base)


def test_sample_has_both_markets():
    mks = {o["mk"] for o in om._SAMPLE_ORDERS}
    assert "쿠팡" in mks and "스마트스토어" in mks


def test_extra_gate_default_off(monkeypatch):
    monkeypatch.delenv("LEMOUTON_MARKET_EXTRA", raising=False)
    assert cap.market_extra_enabled() is False       # 안전 OFF 기본


def test_list_tab_layout():
    html = _render("list", live_enabled=False, orders=om._SAMPLE_ORDERS,
                   st_label=om._ST_LABEL, kpi_new=2, kpi_wait=1, kpi_done=2, kpi_sum=774000)
    for s in ["신규주문", "발송대기", "발송완료", "주문 합계",   # KPI 요약
              "안전 OFF", "LEMOUTON_MARKET_EXTRA",              # 안전 OFF 배너
              "송장입력", "쿠팡", "스마트스토어", "774,000"]:      # 표·마켓·금액 포맷
        assert s in html, s


def test_list_send_button_disabled():
    html = _render("list", live_enabled=False, orders=om._SAMPLE_ORDERS,
                   st_label=om._ST_LABEL, kpi_new=0, kpi_wait=0, kpi_done=0, kpi_sum=0)
    assert "disabled" in html                          # 발송 버튼 비활성


def test_list_empty_state_when_live_no_orders():
    html = _render("list", live_enabled=True, orders=[], st_label=om._ST_LABEL,
                   kpi_new=0, kpi_wait=0, kpi_done=0, kpi_sum=0)
    assert "아직 표시할 실주문이 없어요" in html
    assert "안전 OFF" not in html                       # live=on → 배너 숨김


def test_route_registered():
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/orders/" in rules
