# -*- coding: utf-8 -*-
"""주문·정산·문의반품·신규등록 탭 — 5번 레이아웃(요약+표) · 안전 OFF(연결됨·검증대기)."""
import datetime as _dt
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
    export_markets = ["coupang", "lotteon", "smartstore"] if tab == "list" else []
    return env.get_template("orders/index.html").render(
        tab=tab, subtabs=om.SUBTABS, active="orders_" + tab,
        cfg=cfg, live_enabled=live_enabled, rows=rows,
        export_markets=export_markets,
        all_columns=om._oe.ALL_COLUMNS if tab == "list" else [],
        col_meta=om._oe.columns_meta() if tab == "list" else {})


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


def test_list_tab_has_quick_range_buttons():
    html = _render("list", live_enabled=True)
    assert 'id="qchips"' in html            # 빠른 버튼 컨테이너
    assert 'id="qdirect"' in html           # 「직접」 시작~끝 날짜
    assert "버튼 관리" in html               # 관리 진입(모달)
    assert "빠른 기간 버튼 관리" in html      # 관리 모달 제목
    assert "moum_quick_ranges_v1" in html   # 저장 키
    assert "2~3일 전" in html and "지난주" in html and "지난달" in html   # 기본 버튼


def test_parse_range_reads_from_to():
    since, until = om._parse_range({"from": "2026-06-01", "to": "2026-06-10"})
    assert since.date() == _dt.date(2026, 6, 1)
    assert until.date() == _dt.date(2026, 6, 10)
    assert until.hour == 23 and until.minute == 59        # 종료일 하루 전체 포함


def test_parse_range_swaps_reversed_and_clamps():
    since, until = om._parse_range({"from": "2026-06-10", "to": "2026-06-01"})
    assert since.date() == _dt.date(2026, 6, 1) and until.date() == _dt.date(2026, 6, 10)
    s, u = om._parse_range({"from": "2026-01-01", "to": "2026-12-31"})
    assert (u.date() - s.date()).days == 90                # 90일 상한


def test_parse_range_absent_or_bad_is_none():
    assert om._parse_range({}) == (None, None)
    assert om._parse_range({"from": "2026-06-01"}) == (None, None)   # 한쪽만 → None
    assert om._parse_range({"from": "bad", "to": "also-bad"}) == (None, None)


@pytest.mark.parametrize("tab,kpi,col", [
    ("sales", "정산 예정", "정산 예정액"),
    ("cs", "미답변 문의", "내용"),
    ("register", "등록 대기", "카테고리"),
])
def test_tab_renders_layout(tab, kpi, col):
    # list 는 7번(AJAX) 전용 레이아웃이라 별도 테스트. sales/cs/register 는 샘플 레이아웃 유지.
    html = _render(tab)
    assert kpi in html, kpi
    assert col in html, col
    assert "안전 OFF" in html                  # 게이트 OFF 배너
    assert "쿠팡" in html and "스마트스토어" in html


def test_action_button_disabled_when_off():
    html = _render("register")
    assert "disabled" in html                   # 등록 버튼 비활성(샘플 탭)


def test_live_on_shows_empty_state():
    html = _render("sales", live_enabled=True)
    assert "아직 표시할 실데이터가 없어요" in html
    assert "안전 OFF" not in html                # live=on → 배너 숨김


def test_list_is_seven_layout():
    # 7번: 좌측 필터(마켓·기간·주문상태·검색) + 대시보드 + 실주문(preview.json) — 샘플/배너 없음
    html = _render("list")
    for t in ["마켓", "기간", "주문상태", "검색", "엑셀 양식 설정", "엑셀 내보내기",
              "preview.json", "kpis", "tablewrap"]:
        assert t in html, t
    assert "안전 OFF" not in html                # 모순 배너 제거됨
    assert "레이아웃 미리보기(샘플)" not in html


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
    assert "/orders/preview.json" in rules


def test_preview_masks_personal_fields(monkeypatch):
    monkeypatch.setattr(om._oe, "order_rows", lambda market, days=7, **k: [{
        "상품명": "코트", "수령자": "김지현", "구매자": "김지현",
        "수령자전화번호": "01011112222", "구매자번호": "01011112222",
        "주소": "서울 강남구 테헤란로 123 4층", "주문상태": "배송완료"}])
    r = _client().get("/orders/preview.json?market=smartstore&days=7")
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] and j["count"] == 1
    row = j["rows"][0]
    assert row["수령자"] == "김**"              # 이름 마스킹
    assert row["수령자전화번호"].startswith("010") and "****" in row["수령자전화번호"]
    assert "테헤란로" not in row["주소"]         # 상세주소 가림(시/구까지만)
    assert row["주문상태"] == "배송완료" and row["상품명"] == "코트"   # 비개인정보는 그대로


def test_list_has_export_controls():
    html = _render("list")
    assert "엑셀 내보내기" in html          # 다운로드 버튼
    assert "최근 7일" in html                # 기간 프리셋 칩
    assert "정산예정금액" in html            # 양식 열 목록(all_columns)에 포함


def test_export_downloads_xlsx_for_smartstore(monkeypatch):
    monkeypatch.setattr(om._oe, "order_rows",
                        lambda market, days=7, **k: [{"상품명": "코트", "정산예정금액": 100}])
    r = _client().get("/orders/export.xlsx?market=smartstore&days=7")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["Content-Type"]
    assert r.data[:2] == b"PK"                # xlsx(zip) 바이트


def test_export_rejects_unsupported_market():
    # order_rows 가 ValueError → 400 (추측 데이터 안 만듦). 11번가=아직 UI 미노출.
    r = _client().get("/orders/export.xlsx?market=eleven11&days=7")
    assert r.status_code == 400


def test_list_export_offers_three_markets():
    html = _render("list")
    assert "스마트스토어" in html and "롯데온" in html and "쿠팡" in html   # 마켓 선택 칩
