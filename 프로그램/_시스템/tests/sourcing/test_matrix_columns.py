# -*- coding: utf-8 -*-
"""Task 2 + Fix colKey — deriveSourceColumns 콘텐츠 마커 검증.

_matrix_v3.html 에 두 헬퍼 함수와 bundle_source_url_id 참조가 존재하는지 확인.
Fix A-E: _colKeyOf, data-cell-col-key, colKey breakdown 키 마커도 검증.
JS 를 실제로 실행하지 않고 소스 텍스트 레벨만 검증 (content-marker).
"""
import pathlib

MATRIX = (
    pathlib.Path(__file__).parent.parent.parent
    / "webapp" / "templates" / "bundles" / "_matrix_v3.html"
)


def _src():
    return MATRIX.read_text(encoding="utf-8")


def test_matrix_file_exists():
    assert MATRIX.exists(), "_matrix_v3.html 파일 없음"


def test_derive_source_columns_defined():
    assert "function deriveSourceColumns" in _src(), \
        "deriveSourceColumns 함수 선언 없음"


def test_src_entries_for_col_defined():
    assert "function _srcEntriesForCol" in _src(), \
        "_srcEntriesForCol 함수 선언 없음"


def test_bundle_source_url_id_referenced():
    assert "bundle_source_url_id" in _src(), \
        "bundle_source_url_id 참조 없음"


def test_derive_columns_exposed_on_window():
    assert "window.deriveSourceColumns" in _src(), \
        "window.deriveSourceColumns 노출 없음"


def test_src_entries_for_col_exposed_on_window():
    assert "window._srcEntriesForCol" in _src(), \
        "window._srcEntriesForCol 노출 없음"


def test_render_price_matrix_uses_cols():
    src = _src()
    # renderPriceMatrix 안에서 cols.map(col => renderSiteCell(o, col)) 패턴 존재
    assert "cols.map(col => renderSiteCell" in src, \
        "renderPriceMatrix 가 cols.map(col => renderSiteCell 패턴을 사용하지 않음"


def test_render_site_cell_uses_col_source_id():
    src = _src()
    assert "col.source_id" in src, \
        "renderSiteCell 이 col.source_id 를 사용하지 않음"


# ── Fix A-E 마커 검증 ──────────────────────────────────────────────

def test_col_key_of_helper_defined():
    """Fix helper: _colKeyOf 함수 선언 + window 노출"""
    src = _src()
    assert "function _colKeyOf" in src, "_colKeyOf 함수 선언 없음"
    assert "window._colKeyOf" in src, "window._colKeyOf 노출 없음"


def test_data_cell_col_key_on_tds():
    """Fix A: renderSiteCell 이 data-cell-col-key 를 td 에 추가"""
    src = _src()
    assert "data-cell-col-key" in src, \
        "data-cell-col-key 속성이 td 에 없음 (Fix A 미적용)"


def test_breakdown_key_includes_col_key():
    """Fix C: breakdown 키에 colKey 포함 (sku|src_id|colKey|price 형태)"""
    src = _src()
    # smFetchBreakdowns 에서 colKey 포함 키 생성
    assert "|${colKey}|" in src, \
        "breakdown 키에 colKey 가 없음 (Fix C 미적용)"


def test_lowest_uses_col_key():
    """Fix D: lowestSrcPerOpt 가 source_id 대신 _colKeyOf(lowest) 를 저장"""
    src = _src()
    assert "_colKeyOf(lowest)" in src, \
        "lowestSrcPerOpt 가 _colKeyOf(lowest) 를 저장하지 않음 (Fix D 미적용)"


def test_sm_refresh_fx_reads_col_key_from_td():
    """Fix B: smRefreshFxInPlace 가 pop 부모 td 에서 cellColKey 를 읽음"""
    src = _src()
    assert "cellColKey" in src, \
        "smRefreshFxInPlace 가 cellColKey 를 사용하지 않음 (Fix B 미적용)"


def test_refetch_bsu_id_on_button():
    """Fix E: 재크롤 버튼에 data-refetch-bsu-id 속성 추가"""
    src = _src()
    assert "data-refetch-bsu-id" in src, \
        "재크롤 버튼에 data-refetch-bsu-id 없음 (Fix E 미적용)"


def test_refetch_handler_passes_bsu_id():
    """Fix E: refetch 핸들러가 bsu_id 쿼리파라미터를 API 에 전달"""
    src = _src()
    assert "refetchBsuId" in src, \
        "refetch 핸들러가 bsu_id 를 읽지 않음 (Fix E 미적용)"
    assert "bsu_id=" in src, \
        "refetch 핸들러가 bsu_id 를 API 에 전달하지 않음 (Fix E 미적용)"
