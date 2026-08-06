# -*- coding: utf-8 -*-
"""정산예정금액 하위탭 — 화면 골격이 뜨는지 (마크업 id 기준 — JS 문자열 검사 함정 회피).

렌더는 test_orders_tab 과 같은 방식(base.html 스텁 + 템플릿 직접 렌더) — 사이드바
컨텍스트 없이도 탭 블록 자체를 검사한다.
"""
import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from webapp.routes import orders as om

TPL = pathlib.Path(om.__file__).parents[1] / "templates"


def _render(tab):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(str(TPL)),
    ]))
    env.globals["url_for"] = lambda *a, **k: "#"
    cfg = om.TAB_CONFIG.get(tab)
    return env.get_template("orders/index.html").render(
        tab=tab, subtabs=om.SUBTABS, active="orders_" + tab,
        cfg=cfg, live_enabled=False, rows=[], export_markets=[],
        all_columns=[], col_meta={})


def test_subtabs_에_정산예정금액이_있다():
    keys = {t["key"] for t in om.SUBTABS}
    assert "settle_plan" in keys
    label = next(t["label"] for t in om.SUBTABS if t["key"] == "settle_plan")
    assert label == "정산예정금액"


def test_탭_화면_골격_마크업이_있다():
    html = _render("settle_plan")
    assert 'id="spn-kpi"' in html          # 요약 카드(총액+색 막대+경고 카드)
    assert 'id="spn-table"' in html        # 본표(확정/미확정 행 분리)
    assert 'id="spn-rules-btn"' in html    # ⚙️ 계산 규칙 단추
    assert 'id="spn-rules-modal"' in html  # 규칙 창
    assert 'id="spn-axis"' in html         # 받는 날/주문일 축 전환
    assert 'id="spn-unit"' in html         # 일/주/월 전환


def test_다른_탭에는_이_블록이_없다():
    html = _render("cs")
    assert 'id="spn-kpi"' not in html
