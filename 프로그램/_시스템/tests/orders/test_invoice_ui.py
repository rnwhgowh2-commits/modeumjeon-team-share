# -*- coding: utf-8 -*-
"""[TEST] 「주문 내역」 송장 UI — 화면 요소 존재 · 식별자 전달.

시안 6번(행마다 인라인 편집): 체크박스로 고른 줄만 택배사·송장칸이 살아나고,
엑셀로 채운 줄과 직접 입력한 줄이 색으로 구분된다.
"""
import pathlib

import pytest
from flask import Flask
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from webapp.routes import orders as om

TPL = pathlib.Path(om.__file__).parents[1] / "templates"


def _render_list_tab():
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(str(TPL)),
    ]))
    return env.get_template("orders/index.html").render(
        tab="list", subtabs=om.SUBTABS, active="orders_list",
        cfg=om.TAB_CONFIG.get("list"), live_enabled=False, rows=[],
        export_markets=["coupang"], all_columns=om._oe.ALL_COLUMNS,
        col_meta=om._oe.columns_meta())


class TestInvoiceUiPresent:
    def test_toolbar_and_checkbox_exist(self):
        html = _render_list_tab()
        assert 'id="invbar"' in html          # 표 위 송장 툴바
        assert 'id="invfile"' in html         # 엑셀 파일 입력
        assert "inv-ck" in html               # 행 체크박스 클래스
        assert "엑셀 업로드" in html

    def test_send_is_two_step_preview_then_send(self):
        html = _render_list_tab()
        assert 'id="invprev"' in html and 'id="invsend"' in html
        assert "미리보기" in html

    def test_only_sendable_markets_are_checkable(self):
        """전송 함수 없는 마켓은 화면에서도 체크 못 하게(거짓 기대 방지)."""
        html = _render_list_tab()
        assert "SENDABLE" in html
        assert "coupang:1" in html and "smartstore:1" in html
        assert "lotteon:1" not in html        # 미지원 마켓은 포함하지 않음

    def test_row_color_classes_distinguish_excel_and_manual(self):
        html = _render_list_tab()
        for cls in ("r-xl", "r-hand", "r-bad", "r-sent"):
            assert cls in html


class TestPreviewPassesSendIds:
    @pytest.fixture
    def client(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(om.bp)
        return app.test_client()

    def test_send_ids_reach_the_browser(self, client, monkeypatch):
        """쿠팡 전송 식별자가 preview.json 까지 전달돼야 화면에서 전송할 수 있다."""
        row = {"판매처": "쿠팡", "오픈마켓주문번호": "100", "송장입력": "",
               "_send_ids": {"shipment_box_id": "SB1", "order_sheet_id": "100"}}
        monkeypatch.setattr(om._oe, "combined_order_rows",
                            lambda *a, **k: [row])
        body = client.get("/orders/preview.json?markets=coupang&days=7").get_json()
        assert body["ok"] is True
        assert body["rows"][0]["_send_ids"]["shipment_box_id"] == "SB1"
