# -*- coding: utf-8 -*-
"""Task 4 — crawl_log.js (소싱처 × URL) 카드 분리 content-marker 검증.

JS를 실제로 실행하지 않고 소스 텍스트 레벨만 검증.
"""
import pathlib

CRAWL_LOG = (
    pathlib.Path(__file__).parent.parent.parent
    / "webapp" / "static" / "crawl_log.js"
)


def _src():
    return CRAWL_LOG.read_text(encoding="utf-8")


def test_file_exists():
    assert CRAWL_LOG.exists(), "crawl_log.js 파일 없음"


# ── 핵심 그루핑 키 ────────────────────────────────────────────────────

def test_url_card_key_function_defined():
    """urlCardKey(sk, url) 함수 선언 존재 — 복합 카드 키 생성 핵심."""
    src = _src()
    assert "function urlCardKey" in src, "urlCardKey 함수 선언 없음"


def test_card_key_uses_pipe_separator():
    """sk + '|' + url 패턴으로 키 생성 (소싱처|URL 구분)."""
    src = _src()
    assert "sk + '|' + url" in src, "sk+'|'+url 복합 키 패턴 없음"


def test_get_url_source_function_defined():
    """getUrlSource(b, sk, url) — URL 카드 버킷 조회/생성."""
    src = _src()
    assert "function getUrlSource" in src, "getUrlSource 함수 선언 없음"


# ── 라벨 파생 ─────────────────────────────────────────────────────────

def test_label_for_url_function_defined():
    """labelForUrl(sk, url, b) — DATA 기반 라벨 + fallback(N번호)."""
    src = _src()
    assert "function labelForUrl" in src, "labelForUrl 함수 선언 없음"


def test_derive_source_columns_used_for_labels():
    """window.deriveSourceColumns 을 라벨 파생에 사용."""
    src = _src()
    assert "window.deriveSourceColumns" in src, "window.deriveSourceColumns 참조 없음"


def test_fallback_label_uses_source_labels():
    """DATA 없을 때 SOURCE_LABELS[sk] + '(N)' 패턴 fallback."""
    src = _src()
    assert "SOURCE_LABELS[sk]" in src, "SOURCE_LABELS[sk] fallback 없음"


# ── 이터레이터 ────────────────────────────────────────────────────────

def test_ordered_url_cards_function_defined():
    """orderedUrlCards(b) — renderDetail 용 카드 목록 생성."""
    src = _src()
    assert "function orderedUrlCards" in src, "orderedUrlCards 함수 선언 없음"


def test_all_cards_for_sk_function_defined():
    """allCardsForSk(b, sk) — source-done / finish 에서 일괄 마감용."""
    src = _src()
    assert "function allCardsForSk" in src, "allCardsForSk 함수 선언 없음"


# ── 이벤트 핸들러에서 URL 카드 사용 ──────────────────────────────────

def test_item_done_uses_get_url_source():
    """item-done 핸들러가 getUrlSource 를 호출 (sk+url 카드 버킷)."""
    src = _src()
    assert "getUrlSource(b, sk, _url2)" in src, \
        "item-done 핸들러가 getUrlSource 를 사용하지 않음"


def test_item_retried_uses_get_url_source():
    """item-retried 핸들러가 getUrlSource 를 호출."""
    src = _src()
    assert "getUrlSource(b, sk, _urlR)" in src, \
        "item-retried 핸들러가 getUrlSource 를 사용하지 않음"


# ── renderDetail ─────────────────────────────────────────────────────

def test_render_detail_uses_ordered_url_cards():
    """renderDetail 이 SOURCE_ORDER.forEach 대신 orderedUrlCards 를 호출."""
    src = _src()
    assert "orderedUrlCards(b)" in src, "renderDetail 이 orderedUrlCards 를 사용하지 않음"


def test_render_detail_uses_card_label():
    """renderDetail 이 카드 라벨로 cardLabel 변수를 사용."""
    src = _src()
    assert "cardLabel" in src, "renderDetail 이 cardLabel 을 사용하지 않음"


# ── source-done / finish 일괄 마감 ────────────────────────────────────

def test_source_done_uses_all_cards_for_sk():
    """source-done 핸들러가 allCardsForSk 로 URL 분리 카드를 일괄 마감."""
    src = _src()
    assert "allCardsForSk(b, sk)" in src, \
        "source-done 핸들러가 allCardsForSk 를 사용하지 않음"


def test_finish_marks_all_source_keys():
    """finish 핸들러가 Object.keys(b.sources) 전체를 마감 (URL 분리 카드 포함)."""
    src = _src()
    assert "Object.keys(b.sources).forEach" in src, \
        "finish 핸들러가 Object.keys(b.sources).forEach 를 사용하지 않음"


# ── 단일 URL 소싱처 격리 ─────────────────────────────────────────────

def test_single_url_no_suffix():
    """단일 URL 소싱처 → 라벨에 번호 suffix 없음 (total <= 1 조건)."""
    src = _src()
    assert "total <= 1" in src or "total<=1" in src, \
        "단일 URL suffix 없음 처리(total<=1) 조건 없음"


# ── buildFinishHTML / renderRailMin 집계 수정 ────────────────────────

def test_build_finish_html_uses_ordered_url_cards():
    """buildFinishHTML 이 orderedUrlCards 로 ok/fail 집계."""
    src = _src()
    assert "orderedUrlCards(b).forEach" in src, \
        "buildFinishHTML 이 orderedUrlCards 를 사용하지 않음"


def test_url_cards_progress_function_defined():
    """urlCardsProgress(b) — bundleProgress 보조 함수."""
    src = _src()
    assert "function urlCardsProgress" in src, "urlCardsProgress 함수 선언 없음"
