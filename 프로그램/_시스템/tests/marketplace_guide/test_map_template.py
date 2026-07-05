# -*- coding: utf-8 -*-
"""map.html — 흐름 4층·두 갈래·SOP·코드위치·리스크 검증."""
import pathlib

from webapp.routes import marketplace_guide as mg

TPL = pathlib.Path(mg.__file__).parents[1] / "templates" / "marketplace_guide"


def _map():
    return (TPL / "map.html").read_text(encoding="utf-8")


def test_flow_four_layers():
    html = _map()
    for node in ["프로그램", "전송 대기", "판매처 API", "마켓 반영"]:
        assert node in html


def test_two_branches_explicit():
    html = _map()
    assert "신규 상품" in html and "등록" in html
    assert "기존" in html and "연동" in html


def test_code_map_files():
    html = _map()
    for f in ["uploader/runtime.py", "smartstore", "coupang", "MARKET_METADATA"]:
        assert f in html


def test_risk_integrity():
    html = _map()
    assert "LEMOUTON_LIVE_UPLOAD" in html
    assert "0원" in html or "재고" in html


def test_design_tokens():
    html = _map()
    assert "Pretendard" in html and "#191F28" in html


# ── 판매처별 데이터 코드 지도(마켓 가로탭 + 주요 데이터) ──

def test_market_tabs_present():
    html = _map()
    for mk in ["쿠팡", "스마트스토어", "롯데온"]:
        assert mk in html


def test_key_data_tab():
    html = _map()
    assert "주요 데이터" in html          # ⭐ 탭 이름(구 '모아보기')


def test_six_domains_present():
    html = _map()
    for g in ["상품·옵션 등록·관리", "가격·재고·판매상태",
              "조회·연동", "주문·배송", "정산", "고객응대(CS)"]:
        assert g in html


def test_status_four_states():
    html = _map()
    # 됨 / 연결됨(우리코드) / 공식제공(마켓문서엔 있으나 미구현) / 미정의(확인 안 됨)
    for s in ["됨", "연결됨", "공식제공", "미정의"]:
        assert s in html


def test_settlement_official_apis_catalogued():
    html = _map()
    # 정산 그룹에 마켓 공식 정산 엔드포인트 반영(마진 계산용 정산금액·수수료)
    for s in ["건별 정산내역", "수수료 상세", "부가세", "상품별 차감내역", "중개셀러 통합정보"]:
        assert s in html


def test_official_categories_per_market():
    html = _map()
    for c in ["N배송", "문의", "커머스솔루션", "판매자정보"]:      # 네이버 커머스 공식 카테고리
        assert c in html
    for c in ["거래처", "상품속성", "판촉", "클레임", "고객센터", "전시", "스마트픽"]:  # 롯데온 공식 카테고리
        assert c in html


def test_empty_category_placeholder():
    html = _map()
    assert "가져오는 중" in html   # 항목 미수집 카테고리 자리표시(문서 주면 채움)


def test_capabilities_gate_referenced():
    html = _map()
    assert "LEMOUTON_MARKET_EXTRA" in html
    assert "capabilities.py" in html


def test_send_receive_directions():
    html = _map()
    assert "보내기" in html and "받기" in html


def test_new_market_guide_referenced():
    html = _map()
    assert "_새-마켓-추가-가이드.md" in html
