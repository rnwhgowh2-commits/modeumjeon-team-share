# -*- coding: utf-8 -*-
"""[TEST] 「📦 송장 작업」 송장 UI — 화면 요소 존재 · 식별자 전달.

시안 6번(행마다 인라인 편집): 체크박스로 고른 줄만 택배사·송장칸이 살아나고,
엑셀로 채운 줄과 직접 입력한 줄이 색으로 구분된다.

★ [2026-07-24] 송장 도구는 「주문 내역」 → 「송장 작업」으로 옮겼다.
  주문 내역은 조회 전용이라 같은 요소가 **없어야** 한다(아래 부재 검사).
"""
import pathlib

import pytest
from flask import Flask
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from webapp.routes import orders as om

TPL = pathlib.Path(om.__file__).parents[1] / "templates"


def _render(tab):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(str(TPL)),
    ]))
    # Flask 밖에서 렌더하는 틀이라 url_for 가 없다 — 실제 앱과 같은 모양의 대역을 심는다
    #   (화면이 정적 JS 를 <script src="{{ url_for('static', ...) }}"> 로 부르기 시작했다).
    env.globals["url_for"] = lambda endpoint, **kw: "/%s/%s" % (endpoint, kw.get("filename", ""))
    return env.get_template("orders/index.html").render(
        tab=tab, subtabs=om.SUBTABS, active="orders_" + tab,
        cfg=om.TAB_CONFIG.get("list"), live_enabled=False, rows=[],
        export_markets=["coupang"], all_columns=om._oe.ALL_COLUMNS,
        col_meta=om._oe.columns_meta())


def _render_list_tab():
    """송장 도구가 **없어야 하는** 화면(조회 전용)."""
    return _render("list")


def _render_ship_tab():
    """송장 도구가 **있어야 하는** 화면."""
    return _render("ship")


class TestInvoiceUiPresent:
    def test_toolbar_and_checkbox_exist(self):
        html = _render_ship_tab()
        assert 'id="invbar"' in html          # 표 위 송장 툴바
        assert 'id="invfile"' in html         # 엑셀 파일 입력
        assert "inv-ck" in html               # 행 체크박스 클래스
        assert "엑셀 업로드" in html

    def test_주문내역엔_송장도구가_없다(self):
        """주문 내역은 조회 전용 — 송장 도구가 남아 있으면 위상이 다시 섞인다."""
        html = _render_list_tab()
        assert 'id="invbar"' not in html
        assert 'id="invfile"' not in html
        assert 'id="mangoCard"' not in html      # 더망고 대조 카드
        assert 'id="oviewTabs"' not in html      # 전체주문·배송검사·자동전환 뷰 탭
        assert 'id="checkView"' not in html
        assert 'id="autoView"' not in html
        assert 'id="dmbars"' not in html         # 왼쪽 분류 막대

    def test_배송검사_탭은_없어졌다(self):
        """같은 일을 하는 화면이 두 벌이라 어디서 뭘 하는지 알 수 없었다."""
        assert 'inspect' not in {t['key'] for t in om.SUBTABS}

    def test_send_is_single_button_guarded_by_confirm(self):
        """사용자 요청으로 「미리보기」 버튼 제거 — 확인창이 화면상 마지막 방어선."""
        html = _render_ship_tab()
        assert 'id="invsend"' in html
        assert 'id="invprev"' not in html          # 미리보기 버튼 없음
        assert "confirm(" in html
        assert "되돌리기 어렵습니다" in html

    def test_hint_has_no_dangling_preview_reference(self):
        """없는 버튼(「미리보기」)을 가리키는 안내 문구가 남아 있으면 안 된다(모순 표기 금지)."""
        html = _render_ship_tab()
        assert "전송은 미리보기로 먼저 확인" not in html

    def test_toolbar_buttons_do_not_wrap_to_two_lines(self):
        """「엑셀 업로드」가 두 줄로 접히지 않게."""
        html = _render_ship_tab()
        assert ".o7 .ibar .gbtn{white-space:nowrap;}" in html

    def test_only_sendable_markets_are_checkable(self):
        """전송 함수 없는 마켓은 화면에서도 체크 못 하게(거짓 기대 방지)."""
        html = _render_ship_tab()
        assert "SENDABLE" in html
        assert "coupang:1" in html and "smartstore:1" in html
        assert "lotteon:1" in html            # 발송처리(apiNo=137) 구현 완료
        assert "eleven11:1" in html           # reqdelivery + 로젠 코드 00002 실측 확정
        assert "auction:1" in html and "gmarket:1" in html   # ESM 발송처리 구현 완료

    def test_screen_sendable_matches_server(self):
        """화면 목록이 서버보다 좁으면 **그 마켓 주문이 조용히 사라진다**.

        실제로 옥션·G마켓이 그랬다 — 서버는 보낼 수 있는데 화면이 빼버렸다.
        """
        import re

        from lemouton.markets.invoice_send import SUPPORTED_SEND

        html = _render_ship_tab()
        m = re.search(r"var SENDABLE=\{([^}]*)\}", html)
        assert m, "SENDABLE 선언을 못 찾음"
        screen = {k.strip() for k in re.findall(r"(\w+)\s*:\s*1", m.group(1))}
        assert screen == set(SUPPORTED_SEND)

    def test_row_color_classes_distinguish_excel_and_manual(self):
        html = _render_ship_tab()
        for cls in ("r-xl", "r-hand", "r-bad", "r-sent"):
            assert cls in html


class TestToolbarLeftAndDragDrop:
    """툴바는 왼쪽 고정(가로 스크롤해도 보임) · 표 전체가 드롭존."""

    def test_toolbar_is_left_aligned_and_sticky(self):
        html = _render_ship_tab()
        assert "justify-content:flex-start" in html   # 양끝 정렬 아님 → 버튼이 왼쪽
        assert "position:sticky" in html and "left:0" in html

    def test_table_is_a_drop_zone_with_overlay(self):
        html = _render_ship_tab()
        assert 'id="droprel"' in html and 'id="dropov"' in html
        assert "여기에 놓으세요" in html

    def test_drag_drop_and_click_share_one_upload_path(self):
        """드래그앤드롭과 「엑셀 업로드」 클릭이 같은 함수로 들어간다(동작 불일치 방지)."""
        html = _render_ship_tab()
        assert "function uploadInvoiceFile" in html
        assert html.count("uploadInvoiceFile(") >= 3   # 정의 + 클릭 + 드롭

    def test_only_xlsx_accepted(self):
        html = _render_ship_tab()
        assert "\\.xlsx$" in html                      # 확장자 검사

    def test_drop_outside_table_does_not_open_file(self):
        """표 밖에 떨어뜨렸을 때 브라우저가 파일을 열어 작업 내용이 날아가지 않게."""
        html = _render_ship_tab()
        assert "document.addEventListener(t,function(e){if(hasFile(e))e.preventDefault();});" in html

    def test_hint_tells_user_drag_is_possible(self):
        """올리는 곳이 눈에 보여야 한다 — ① 카드의 끌어놓기 칸."""
        html = _render_ship_tab()
        assert 'id="xlDz"' in html
        assert "끌어놓기" in html


class Test축소_2026_07_30:
    """4단계 → 2덩어리. 택배사 엑셀 하나로 3분류하고 버튼 하나로 보낸다."""

    def test_업로드_칸은_하나뿐이다(self):
        """두 곳에서 올리게 하면 「왜 두 번 올려?」가 된다(사장님 지적)."""
        html = _render_ship_tab()
        assert 'id="xlDz"' in html
        assert 'id="invup"' not in html          # 전송 띠의 「📄 엑셀 업로드」 제거

    def test_더망고는_화면에서만_뺐다(self):
        """경로는 살려 둔다 — 되돌릴 수 있어야 한다."""
        html = _render_ship_tab()
        assert 'id="mangoCard"' in html                       # DOM 엔 있고
        assert ".o7.ship #mangoCard,.o7.ship #step2{display:none;}" in html   # 안 보인다

    def test_세갈래로_가른다(self):
        html = _render_ship_tab()
        for t in ("발송 대상", "이중송장", "확인불가"):
            assert t in html
        assert 'id="clsTabs"' in html and 'id="unkWrap"' in html

    def test_전송_버튼은_표_아래_하나다(self):
        html = _render_ship_tab()
        assert 'id="sendBar"' in html
        assert html.count('id="invsend"') == 1

    def test_택배사는_한_번만_고른다(self):
        """칸마다 또 고르게 하면 어긋난 채로 나간다."""
        html = _render_ship_tab()
        assert 'id="cxBar"' in html
        assert "inv-cr\"" not in html            # 행마다 있던 택배사 선택 상자 제거

    def test_전송결과_세_상태가_남아있다(self):
        """R4 — 확인됨 / 번호 다름 / 확인 대기."""
        html = _render_ship_tab()
        for t in ("확인됨", "번호 다름", "확인 대기", "문제만 보기"):
            assert t in html
        assert "마켓 값이 진짜" in html

    def test_7일_요약이_감시에_붙어있다(self):
        html = _render_ship_tab()
        assert "flow-daily.json" in html
        assert "지켜본 결과" in html
        assert "날짜를 누르면" in html

    def test_감시칸은_자식이_둘이어야_한다(self):
        """자식을 여럿 두고 grid-row 로 넘기면 빈 행마다 gap 이 붙어 칸이 늘어난다."""
        html = _render_ship_tab()
        assert 'class="wleft"' in html
        assert "#d7wrap{grid-column:2;grid-row:1/99;}" not in html


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


class Test단일흐름_2026_07_30:
    """사장님 확정 흐름 — 엑셀 올린다 → 주문 찾아온다 → 갈라 본다 → 미입력에 넣어 보낸다.

    화면이 미리 주문을 불러 둘 필요가 없다. 「주문 내역」에서 물려받은 조회 도구
    (마켓·기간·찾기·엑셀 양식·내보내기)는 송장 보내는 일과 무관하다.
    """

    def test_조회_도구칸이_안_보인다(self):
        html = _render_ship_tab()
        assert 'class="side" hidden' in html          # 마켓·기간·엑셀 양식·내보내기
        assert ".o7.ship #kpis" in html               # 금액 카드도 숨김

    def test_찾기는_표_위에_따로_있다(self):
        """도구칸을 감췄으니 찾기만 표 옆으로 꺼내 둔다(아이디는 겹치지 않게)."""
        html = _render_ship_tab()
        assert 'id="shipSrch"' in html
        assert html.count('id="srch"') == 1           # 도구칸 것 하나뿐 — 중복 아이디 금지

    def test_엑셀_전엔_아래가_접혀_있다(self):
        html = _render_ship_tab()
        assert 'id="step3" style="display:none"' in html

    def test_마켓을_미리_조회하지_않는다(self):
        """기간으로 미리 불러오면 화면만 느리고, 좁게 잡으면 놓친다."""
        html = _render_ship_tab()
        assert "if(SHIP){loading=false;renderLoadBar();render();return;}" in html

    def test_엑셀_내보내기_안내가_안_남아있다(self):
        """없는 버튼을 가리키는 안내가 남으면 모순 표기다(표 아래 안내문)."""
        html = _render_ship_tab()
        assert "「엑셀 내보내기」는 <b>지금 화면에 보이는 주문 그대로</b>" not in html
        assert "「엑셀 내보내기」는 <b>지금 화면에 보이는 주문 그대로</b>" in _render_list_tab()


class TestUploadFindsOrdersItself:
    """업로드가 **적재분에서 직접 찾는다** — 화면이 보낸 목록에 기대지 않는다."""

    def _client(self):
        from flask import Flask
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(om.bp)
        return app.test_client()

    def test_엑셀_주문번호로_적재분을_뒤진다(self, monkeypatch):
        import io as _io

        seen = {}
        row = {"오픈마켓주문번호": "A1", "판매처": "쿠팡", "송장입력": "송장미입력"}

        def _load(**kw):
            seen.update(kw)
            return [row]

        monkeypatch.setattr(om, "_live_enabled", lambda: False, raising=False)
        from lemouton.markets import order_store
        monkeypatch.setattr(order_store, "load", _load)
        monkeypatch.setattr("lemouton.markets.invoice_excel.parse_invoice_excel",
                            lambda b: [{"order_no": "A1", "invoice_no": "9", "courier": "로젠택배"}])
        j = self._client().post(
            "/orders/invoice/upload",
            data={"file": (_io.BytesIO(b"x"), "a.xlsx")},
            content_type="multipart/form-data").get_json()
        assert j["ok"] is True
        assert seen["order_nos"] == ["A1"]        # 화면이 준 목록이 아니라 엑셀의 번호로
        assert j["rows"] == [row]                 # 찾아온 주문을 화면에 그대로 돌려준다
        assert "A1" in j["matched"]

    def test_왼쪽_단계_목록은_없앴다(self):
        """화면에 ① ② 카드가 이미 순서대로 있는데 같은 말을 236px 써서 또 했다."""
        html = _render_ship_tab()
        assert "snav" not in html
        assert ".o7.ship{grid-template-columns:minmax(0,1fr);}" in html


class TestR5결과_2026_07_31:
    """R5 확정 — 올린 직후 큰 숫자 + 칩 + 갈린 비율 띠, 확인불가는 이유+비슷한 주문."""

    def test_큰숫자와_칩과_띠가_다_있다(self):
        html = _render_ship_tab()
        for cls in ("rsum", "rbig", "rprob", "rmeter", "rfoot"):
            assert cls in html

    def test_칩을_누르면_그_갈래로_간다(self):
        """숫자만 보여주고 왜 그런지 못 보면 문제를 지나친다."""
        html = _render_ship_tab()
        assert 'data-c="dup"' in html and 'data-c="unk"' in html

    def test_확인불가는_번호만_나열하지_않는다(self):
        """번호만 있으면 다음에 뭘 해야 할지 모른다(사장님 지적)."""
        html = _render_ship_tab()
        assert "왜 못 찾았나" in html and "가장 비슷한 우리 주문" in html
        assert "unkbox" not in html          # 옛 번호 나열 상자 제거

    def test_문제건은_안_보낸다고_적혀있다(self):
        html = _render_ship_tab()
        assert "보내지 않습니다" in html


class TestNearestOrders:
    """못 찾은 번호 → 왜 못 찾았나 + 가장 비슷한 우리 주문."""

    CANDS = [("20260729990012", "롯데온", "2026-07-29 10:00"),
             ("20260729990013", "11번가", "2026-07-29 11:00")]

    def _near(self, unmatched):
        from lemouton.markets.invoice_excel import nearest_orders
        return nearest_orders(unmatched, self.CANDS)

    def test_한두자리_오타는_그_주문을_짚어준다(self):
        got = self._near(["20260729991012"])["20260729991012"]
        assert got["near"] == "20260729990012"
        assert got["market"] == "롯데온" and got["order_date"] == "2026-07-29"
        assert got["reason"] == "번호 한두 자리가 달라요"

    def test_모양이_다르면_엑셀_열을_의심한다(self):
        """주문번호가 아닌 열을 잡으면 전부 확인불가로 쏟아진다 — 그 사실을 알려야 한다."""
        got = self._near(["A-2026-0729-77"])["A-2026-0729-77"]
        assert got["reason"] == "번호 모양이 달라요" and got["action"] == "엑셀 열 확인"

    def test_모양은_같은데_없으면_기간을_의심한다(self):
        got = self._near(["20260601000441"])["20260601000441"]
        assert got["reason"] == "우리 주문에 없어요" and got["action"] == "기간 확인"

    def test_안_닮았으면_억지로_안_붙인다(self):
        """엉뚱한 주문을 「이거 아니에요?」라고 하면 잘못 보낸다."""
        got = self._near(["20260601000441"])["20260601000441"]
        assert got["near"] == ""

    def test_후보가_없어도_안_터진다(self):
        from lemouton.markets.invoice_excel import nearest_orders
        got = nearest_orders(["12345"], [])
        assert got["12345"]["near"] == "" and got["12345"]["reason"]
