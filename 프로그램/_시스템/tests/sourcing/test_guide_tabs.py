# -*- coding: utf-8 -*-
"""크롤링 가이드 탭 통합 — 라우트 제거 + map 7탭 + 정본 동기화 검증."""
import pathlib
import pytest
from flask import Flask
from webapp.routes import sourcing_guide as sg

TPL = pathlib.Path(sg.__file__).parent.parent / "templates" / "sourcing_guide"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")   # _admin_only 우회
    app = Flask(__name__)
    app.register_blueprint(sg.bp)
    return app.test_client()


def test_how_to_route_removed(client):
    assert client.get("/sourcing-guide/how-to").status_code == 404


def test_how_to_template_deleted():
    assert not (TPL / "how_to_add.html").exists()


def test_no_how_to_links_in_templates():
    for f in TPL.rglob("*.html"):
        assert "/sourcing-guide/how-to" not in f.read_text(encoding="utf-8"), f.name


def test_map_design_tokens():
    css = (TPL / "map.html").read_text(encoding="utf-8")
    assert "Pretendard" in css
    assert "#191F28" in css and "#6B7684" in css and "#1B64DA" in css and "#DC2626" in css
    assert "klabel" in css            # "핵심" 라벨 클래스
    assert "align-items:center" in css  # 카드 세로 중앙정렬


def test_map_has_seventh_tab():
    html = (TPL / "map.html").read_text(encoding="utf-8")
    assert 'data-s="s7"' in html
    assert "신규추가" in html


def test_tab1_flow_cards():
    html = (TPL / "map.html").read_text(encoding="utf-8")
    s1 = html.split('id="s1"')[1].split('id="s2"')[0]
    assert "크롤러" in s1 and "저장" in s1 and "계산" in s1 and "표시" in s1
    assert "compute_market_price" in s1
    assert "BG_PARSE" in s1


def test_tab2_stock_states_and_glossary():
    html = (TPL / "map.html").read_text(encoding="utf-8")
    s2 = html.split('id="s2"')[1].split('id="s3"')[0]
    assert "API 호출" in s2 and "HTML 파싱" in s2 and "DOM 읽기" in s2
    for k in ["품절", "한정", "충분", "특이사항", "옵션없음", "크롤실패"]:
        assert k in s2, k
    for src in ["무신사", "SSG", "SSF", "롯데온", "스마트", "르무통"]:
        assert src in s2, src
    assert "outOfStock" in s2 and "품절임박" in s2 and "usablInvQty" in s2


def test_tab3_price_methods():
    html = (TPL / "map.html").read_text(encoding="utf-8")
    s3 = html.split('id="s3"')[1].split('id="s4"')[0]
    assert "표면노출가" in s3 and "혜택" in s3
    assert "표면 노출가 − 혜택" in s3 or "표면노출가 − 혜택" in s3
    for src in ["무신사", "SSG", "롯데온"]:
        assert src in s3, src
    assert "api_benefits.py" in s3


def test_tabs_4_5_6():
    html = (TPL / "map.html").read_text(encoding="utf-8")
    # [2026-06-27~28] 보기 탭 8→7 통합: 옛 s5(무결성·폴백금지)가 s4로 병합(s5 제거),
    #   s6='⚠️에러이력 카탈로그'(errcards). '재고 읽는 법'(_resolve_stock·stale)은 s2로 이동.
    s4 = html.split('id="s4"')[1].split('id="s6"')[0]   # s5 제거됨 → 다음 탭은 s6
    assert "window.DATA" in s4 and "완전한 B" in s4 and "source_product_id" in s4
    assert "klabel" in s4
    assert "폴백가 금지" in s4 and "단일 진실원천" in s4   # 옛 s5 무결성 내용도 s4로 병합
    s6 = html.split('id="s6"')[1].split('id="s7"')[0]
    assert "errcards" in s6                       # 에러 이력 카탈로그 카드 컨테이너
    s2 = html.split('id="s2"')[1].split('id="s3"')[0]
    assert "_resolve_stock" in s2 and "stale" in s2


def test_tab7_newsource_flow():
    html = (TPL / "map.html").read_text(encoding="utf-8")
    s7 = html.split('id="s7"')[1].split('id="m-raw"')[0]
    assert "URL 세트" in s7 or "여러" in s7
    assert "혜택 종합" in s7
    assert "상시" in s7 and "조건부" in s7
    for k in ["혜택 변형", "재고 3상태", "옵션 구조"]:
        assert k in s7, k


def test_docs_synced():
    app_root = pathlib.Path(sg.__file__).parents[2]   # 프로그램/_시스템  (routes→webapp→_시스템)
    repo_root = pathlib.Path(sg.__file__).parents[4]  # worktree root     (_시스템→프로그램→root)
    txt = (app_root / "docs" / "크롤링-가이드.md").read_text(encoding="utf-8")
    assert "옵션없음" in txt and "크롤실패" in txt           # 재고 특이사항 동기화
    sop = (repo_root / "docs" / "신규-소싱처-추가-가이드.md").read_text(encoding="utf-8")
    assert "혜택 종합" in sop                               # 4단계 신설 반영
    assert "URL 세트" in sop or "여러" in sop               # 멀티 URL


def test_eighth_tab_is_sync():
    """§8 동기화 탭은 의도된 추가. 과거 되돌린 '소싱처별 혜택 설정'(bs-source) 탭과는 다름."""
    html = (TPL / "map.html").read_text(encoding="utf-8")
    assert 'data-s="s8"' in html          # §8 동기화 탭 (의도됨)
    assert "동기화" in html               # 탭 라벨
    # 과거 되돌린 8번째 탭(소싱처별 혜택 설정 / bs-source)은 여전히 없어야 함
    assert "소싱처별 혜택 설정" not in html
    assert 'id="bs-source"' not in html


# ── Task 1a-3: 혜택 편집기 복원 + 2축·시안2 키워드 UI ──

def test_detail_benefit_editor_restored():
    """sg-inc 컨테이너 재존재, sg-edit-moved 안내 부재."""
    html = (TPL / "detail.html").read_text(encoding="utf-8")
    assert 'id="sg-inc"' in html, "혜택 카드 컨테이너 #sg-inc 없음"
    assert "sg-edit-moved" not in html, "sg-edit-moved 안내가 남아 있음 (제거되어야 함)"


def test_detail_vseg_value_source_axis():
    """값출처 세그먼트(vseg) — 고정값/크롤값 축 존재."""
    html = (TPL / "detail.html").read_text(encoding="utf-8")
    assert "vseg" in html, "값출처 세그먼트(.vseg) 없음"
    assert "고정값" in html and "크롤값" in html, "값출처 레이블(고정값/크롤값) 없음"


def test_detail_ctg_conditional_toggle():
    """조건부 토글(.ctg) 존재."""
    html = (TPL / "detail.html").read_text(encoding="utf-8")
    assert "ctg" in html, "조건부 토글(.ctg) 없음"


def test_detail_cond_panel_and_chips():
    """조건 펼침 패널(.cond) + 적용/제외 칩 영역 존재."""
    html = (TPL / "detail.html").read_text(encoding="utf-8")
    assert "cond" in html, ".cond 패널 없음"
    assert "적용" in html and "제외" in html, "적용/제외 레이블 없음"


def test_detail_no_sg3_side_common_exclude():
    """소싱처 공통제외 패널(#sg-exlist/sg3-side) 제거 확인."""
    html = (TPL / "detail.html").read_text(encoding="utf-8")
    assert 'id="sg-exlist"' not in html, "#sg-exlist 공통제외 패널이 남아 있음"


def test_detail_aa_btn_restored():
    """따라쓰기 버튼(aa-btn) 복원."""
    html = (TPL / "detail.html").read_text(encoding="utf-8")
    assert 'id="aa-btn"' in html, "따라쓰기 버튼 #aa-btn 없음"


def test_detail_js_collect_new_model():
    """detail.js — collect()가 value_source/status/triggers/excludes를 수집."""
    js = (TPL / "detail.js").read_text(encoding="utf-8")
    assert "value_source" in js, "collect()에 value_source 없음"
    assert "status" in js, "collect()에 status 없음"
    assert "triggers" in js, "collect()에 triggers 없음"
    assert "excludes" in js, "collect()에 excludes(per-benefit) 없음"


def test_detail_js_fixed_always_enforced():
    """detail.js — 고정값 선택 시 status='always' 강제 로직 존재."""
    js = (TPL / "detail.js").read_text(encoding="utf-8")
    assert "always" in js, "고정값→always 강제 로직 없음"
    # vseg 전환 핸들러가 fixed 분기를 처리해야 함
    assert "fixed" in js, "fixed 값출처 분기 없음"


# ── 자동갱신 A+B+E ────────────────────────────────────────────────────────

MATRIX_TPL = TPL.parent / "bundles" / "_matrix_v3.html"


def test_matrix_exposes_window_reload_matrix():
    """A — window.reloadMatrix = loadMatrix 가 IIFE 안에 있어야 함."""
    html = MATRIX_TPL.read_text(encoding="utf-8")
    assert "window.reloadMatrix = loadMatrix" in html, \
        "window.reloadMatrix 노출 코드가 없음 (A)"
    assert "window.loadMatrix   = loadMatrix" in html, \
        "window.loadMatrix 별칭 없음 (A)"


def test_matrix_crawl_finish_listener():
    """B — 'moum-crawl-log' finish 리스너가 IIFE 안에서 loadMatrix() 를 호출."""
    html = MATRIX_TPL.read_text(encoding="utf-8")
    assert "moum-crawl-log" in html, "'moum-crawl-log' 리스너 없음 (B)"
    assert "d.type !== 'finish'" in html, "finish 타입 체크 없음 (B)"
    # 리스너 안에서 loadMatrix 호출
    assert "loadMatrix();" in html, "리스너 내 loadMatrix() 호출 없음 (B)"


def test_matrix_storage_listener():
    """E — 'storage' 이벤트 리스너가 moum_matrix_stale 키를 감지."""
    html = MATRIX_TPL.read_text(encoding="utf-8")
    assert "storage" in html, "storage 이벤트 리스너 없음 (E)"
    assert "moum_matrix_stale" in html, "moum_matrix_stale 키 없음 (E)"


def test_detail_js_stale_signal_on_save():
    """E — detail.js PUT 성공 후 moum_matrix_stale 신호 기록."""
    js = (TPL / "detail.js").read_text(encoding="utf-8")
    assert js.count("moum_matrix_stale") >= 2, \
        "detail.js 에 moum_matrix_stale 가 최소 2곳(따라쓰기+저장) 이상 없음 (E)"
