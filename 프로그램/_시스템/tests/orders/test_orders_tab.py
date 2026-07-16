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
    # margin 탭 include(orders/_margin.html)는 정적파일 url_for 를 쓴다 — 앱 컨텍스트 없이
    # 렌더하므로 스텁 제공.
    env.globals["url_for"] = lambda *a, **k: "#"
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
    monkeypatch.delenv("MOUM_MARKET_EXTRA", raising=False)
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
    ("register", "등록 대기", "카테고리"),
])
def test_tab_renders_layout(tab, kpi, col):
    # list 는 7번(AJAX) 전용 레이아웃이라 별도 테스트. cs 는 실제 클레임 칸반 전용 레이아웃(아래
    # test_cs_tab_renders_claims_kanban). sales/register 만 샘플 레이아웃 유지.
    html = _render(tab)
    assert kpi in html, kpi
    assert col in html, col
    assert "안전 OFF" in html                  # 게이트 OFF 배너
    assert "쿠팡" in html and "스마트스토어" in html


def test_cs_tab_renders_claims_kanban():
    # cs 탭은 샘플 표 대신 실제 반품·교환·취소 3열 칸반(claims.json 배선)을 렌더한다.
    html = _render("cs")
    assert 'id="cs-board"' in html and 'id="cs-mtabs"' in html
    assert "/orders/cs/claims/ack" in html and "/orders/cs/claims/memo" in html
    assert "/orders/cs/claims.json" in html
    assert "반품·교환·취소" in html and "고객문의" in html
    assert "미답변 문의" not in html            # 구 샘플 레이아웃(TAB_CONFIG['cs']) 미사용


def test_action_button_disabled_when_off():
    html = _render("register")
    assert "disabled" in html                   # 등록 버튼 비활성(샘플 탭)


def test_live_on_shows_empty_state():
    html = _render("sales", live_enabled=True)
    assert "아직 표시할 실데이터가 없어요" in html
    assert "안전 OFF" not in html                # live=on → 배너 숨김


def test_list_is_seven_layout():
    # 7번: 좌측 필터(마켓·기간·검색) + 엑셀 양식(프리셋) + 대시보드 + 실주문(preview.json)
    html = _render("list")
    for t in ["마켓", "기간", "검색", "엑셀 양식", "양식 관리", "엑셀 내보내기",
              "preview.json", "kpis", "tablewrap", "presetSel", "colpop",
              "moum_order_presets_v2", "택배전송용", "마진계산기용"]:
        assert t in html, t
    assert "안전 OFF" not in html                # 모순 배너 제거됨
    assert "레이아웃 미리보기(샘플)" not in html


def test_margin_renders_skeleton():
    # Task C3: margin 탭은 이제 원본 마진계산기 풀페이지를 iframe 으로 임베드한다
    #   (구 B레이아웃 재구현본 id="margin-app" 은 폐기 — 원본 1:1 방향).
    html = _render("margin")
    assert 'id="margin-embed-frame"' in html
    assert '<iframe' in html
    assert "후속 구현 예정" not in html
    # (실제 라우트/src=/orders/margin-embed 는 test_margin_ui_routes.py 가 앱 컨텍스트에서 검증)


def test_routes_registered():
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/orders/" in rules
    assert "/orders/export.xlsx" in rules
    assert "/orders/preview.json" in rules


def test_preview_shows_personal_fields_unmasked(monkeypatch):
    # 사용자 요청(관리자 화면): 구매자·수령자·전화·주소를 마스킹 없이 원본 그대로 노출.
    monkeypatch.setattr(om._oe, "order_rows", lambda market, days=7, **k: [{
        "상품명": "코트", "수령자": "김지현", "구매자": "김지현",
        "수령자전화번호": "01011112222", "구매자번호": "01011112222",
        "주소": "서울 강남구 테헤란로 123 4층", "주문상태": "배송완료"}])
    r = _client().get("/orders/preview.json?market=smartstore&days=7")
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] and j["count"] == 1
    row = j["rows"][0]
    assert row["수령자"] == "김지현" and row["구매자"] == "김지현"       # 마스킹 없음
    assert row["수령자전화번호"] == "01011112222" and "*" not in row["수령자전화번호"]
    assert row["주소"] == "서울 강남구 테헤란로 123 4층"              # 주소 전체(안 끊김)
    assert row["주문상태"] == "배송완료" and row["상품명"] == "코트"


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


def test_shopmine_fee_derivation():
    """샵마인 대조(2026-07-08): 마켓수수료 = 실결제 − 정산예정, 수수료율 = 수수료/총주문.

    4개 마켓 실샘플로 검증. 실결제 없으면(쿠팡) 총주문금액으로. 정산==실결제(롯데온,
    정산 API 없음)면 수수료 공란(0/음수 폴백 금지 — 없는 값 지어내지 않음).
    """
    from lemouton.markets.order_export import _finalize_rows
    cases = [   # (실결제, 정산, 기대 수수료, 기대 율)
        ({"단가": 37400, "수량": 1, "실결제금액": 34830, "정산예정금액": 33146}, 1684, "4.5%"),
        ({"단가": 140000, "수량": 1, "정산예정금액": 123830}, 16170, "11.55%"),   # 쿠팡: 실결제 없음
        ({"단가": 83200, "수량": 1, "실결제금액": 66060, "정산예정금액": 62096}, 3964, "4.76%"),
        ({"단가": 65500, "수량": 1, "실결제금액": 55700, "정산예정금액": 55700}, "", ""),  # 롯데온: 정산=실결제
    ]
    for row, fee, rate in cases:
        _finalize_rows([row])
        assert row["마켓수수료"] == fee, row
        assert row["수수료율"] == rate, row
    # 송장 없으면 '송장미입력', 새 열 존재
    assert cases[0][0]["송장입력"] == "송장미입력"
    assert cases[0][0]["총주문금액"] == 37400


def test_preset_market_fee_wins_over_derivation():
    """빌더가 정산 API 실값으로 마켓수수료를 미리 채우면 파생값 대신 그걸 사용(롯데온 SettleCommission)."""
    from lemouton.markets.order_export import _finalize_rows
    r = {"단가": 100000, "수량": 1, "실결제금액": 100000, "정산예정금액": 90000, "마켓수수료": 8800}
    _finalize_rows([r])
    assert r["마켓수수료"] == 8800                 # 파생(100000-90000=10000) 아닌 실값 8800
    assert r["수수료율"] == "8.8%"                 # 8800/100000
