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
    assert "MOUM_LIVE_UPLOAD" in html
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


def test_status_labels():
    html = _map()
    for s in ["씀", "검증대기", "안 씀"]:   # DM_LBL — 렌더 상태 라벨
        assert s in html


def test_empty_category_placeholder():
    html = _map()
    assert "가져오는 중" in html   # 항목 미수집 카테고리 자리표시(문서 주면 채움)


def test_capabilities_gate_referenced():
    html = _map()
    assert "MOUM_MARKET_EXTRA" in html
    assert "capabilities.py" in html


def test_send_receive_directions():
    html = _map()
    assert "보내기" in html and "받기" in html


def test_new_market_guide_referenced():
    html = _map()
    assert "_새-마켓-추가-가이드.md" in html


def test_map_fetches_data_and_has_work_tabs():
    html = _map()
    assert "/marketplace-guide/map-data.json" in html   # 데이터 구동
    assert "dmWorkTab" in html and "bindWorkRows" in html # 업무탭 렌더
    assert "클레임·CS" in html and "배송·송장" in html    # 업무탭 배치


# ── 단일 진실 원천(JSON) 검증 — 인라인 카탈로그 삭제 후에도 카탈로그가 SOT에 온전함을 보장 ──

def _sot():
    from webapp.marketplace_api_map import load_map
    return load_map()


def test_no_dead_inline_catalog():
    html = _map()
    for token in ["const MKT_CATS", "const ESM_CATS", "const API_STEPS", "const API_HOW",
                  "function dmApiSteps", "function dmFind", "function dmRow(", "function dmSec",
                  "const DM_MARKETS", "const TRANS=", "const TRANS_MK", "const API_CALLS"]:
        assert token not in html, f"죽은 인라인 재등장 금지: {token}"


def test_sot_catalog_covers_all_markets():
    data = _sot()
    by = {}
    for a in data["apis"]:
        by.setdefault(a["market"], []).append(a)
    for mk in ["coupang", "smartstore", "lotteon", "eleven11", "auction", "gmarket"]:
        assert len(by.get(mk, [])) >= 20, f"{mk} 카탈로그 빈약"
        assert all(a.get("category") for a in by[mk]), f"{mk} 카테고리 미기입 항목 존재"


def test_sot_settlement_apis_per_market():
    data = _sot()
    # 옥션·G마켓(ESM)은 정산 API 미접수 상태라 제외(접수되면 추가)
    for mk in ["coupang", "smartstore", "lotteon", "eleven11"]:
        assert any(a["market"] == mk and ("정산" in (a.get("category") or "")
                   or any("정산" in t for t in (a.get("tabs") or [])))
                   for a in data["apis"]), f"{mk} 정산 API 없음"


def test_unassigned_tabs_counter_in_template():
    """마켓별 전체 API 탭에 업무탭 미배정 카운터·마커가 렌더 코드로 존재."""
    html = _map()
    assert "업무탭 미배정" in html
    assert "notabChip" in html
