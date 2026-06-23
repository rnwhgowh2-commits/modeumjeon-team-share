# -*- coding: utf-8 -*-
"""Task 2 — deriveSourceColumns 콘텐츠 마커 검증.

_matrix_v3.html 에 두 헬퍼 함수와 bundle_source_url_id 참조가 존재하는지 확인.
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
