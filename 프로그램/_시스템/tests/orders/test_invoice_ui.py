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

    def test_send_is_single_button_guarded_by_confirm(self):
        """사용자 요청으로 「미리보기」 버튼 제거 — 확인창이 화면상 마지막 방어선."""
        html = _render_list_tab()
        assert 'id="invsend"' in html
        assert 'id="invprev"' not in html          # 미리보기 버튼 없음
        assert "confirm(" in html
        assert "되돌리기 어렵습니다" in html

    def test_hint_has_no_dangling_preview_reference(self):
        """없는 버튼(「미리보기」)을 가리키는 안내 문구가 남아 있으면 안 된다(모순 표기 금지)."""
        html = _render_list_tab()
        assert "전송은 미리보기로 먼저 확인" not in html

    def test_toolbar_buttons_do_not_wrap_to_two_lines(self):
        """「엑셀 업로드」가 두 줄로 접히지 않게."""
        html = _render_list_tab()
        assert ".o7 .ibar .gbtn{white-space:nowrap;}" in html

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


class TestToolbarLeftAndDragDrop:
    """툴바는 왼쪽 고정(가로 스크롤해도 보임) · 표 전체가 드롭존."""

    def test_toolbar_is_left_aligned_and_sticky(self):
        html = _render_list_tab()
        assert "justify-content:flex-start" in html   # 양끝 정렬 아님 → 버튼이 왼쪽
        assert "position:sticky" in html and "left:0" in html

    def test_table_is_a_drop_zone_with_overlay(self):
        html = _render_list_tab()
        assert 'id="droprel"' in html and 'id="dropov"' in html
        assert "여기에 놓으세요" in html

    def test_drag_drop_and_click_share_one_upload_path(self):
        """드래그앤드롭과 「엑셀 업로드」 클릭이 같은 함수로 들어간다(동작 불일치 방지)."""
        html = _render_list_tab()
        assert "function uploadInvoiceFile" in html
        assert html.count("uploadInvoiceFile(") >= 3   # 정의 + 클릭 + 드롭

    def test_only_xlsx_accepted(self):
        html = _render_list_tab()
        assert "\\.xlsx$" in html                      # 확장자 검사

    def test_drop_outside_table_does_not_open_file(self):
        """표 밖에 떨어뜨렸을 때 브라우저가 파일을 열어 작업 내용이 날아가지 않게."""
        html = _render_list_tab()
        assert "document.addEventListener(t,function(e){if(hasFile(e))e.preventDefault();});" in html

    def test_hint_tells_user_drag_is_possible(self):
        """1번안(표 전체 드롭)은 평소 표시가 없으니 안내 문구로 알린다."""
        html = _render_list_tab()
        assert "표 위로 끌어다 놓아도" in html


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
