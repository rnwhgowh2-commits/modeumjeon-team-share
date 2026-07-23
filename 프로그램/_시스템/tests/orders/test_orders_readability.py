# -*- coding: utf-8 -*-
"""주문 내역 가독성 3건 — 정렬 규칙 · 찾기 범위 · 찾기 칸 폭.

전부 화면(템플릿) 안의 문자열이라 렌더 결과를 직접 확인한다.
"""
import pathlib

from webapp.routes import orders as om

TPL = pathlib.Path(om.__file__).parents[1] / "templates" / "orders" / "index.html"
SRC = TPL.read_text(encoding="utf-8")


def test_상태열이_가운데정렬_규칙을_갖는다():
    """PANEL_COLS 가 ctr 로 지정한 열(주문상태·판매처 등)을 실제로 가운데 세운다.

    이 규칙이 없으면 코드 의도(가운데)와 화면(왼쪽)이 어긋난다 — 2026-07-24 실측.
    .ctr 규칙은 .ac-table·.ord5 에만 있고 주문 내역 표에는 없었다.
    """
    assert ".o7 table td.ctr,.o7 table th.ctr{text-align:center;}" in SRC


def test_숫자열_우측정렬_규칙은_그대로다():
    """기존 규칙을 건드리지 않았는지 — 같이 깨지면 금액이 왼쪽으로 붙는다."""
    assert ".o7 td.num,.o7 th.num{text-align:right;font-variant-numeric:tabular-nums;}" in SRC


def test_찾기칸이_안쪽여백까지_폭에_포함한다():
    """box-sizing 이 없으면 width:100% + padding 만큼 왼쪽 칸을 삐져나간다."""
    assert (".o7 .srch{box-sizing:border-box;width:100%;border:1px solid var(--line2);"
            "border-radius:9px;padding:8px 10px;font-size:13px;font-family:inherit;}") in SRC


def test_찾기가_모든_항목을_본다():
    """상품명·수령자 둘만 보면 송장번호·주문번호로 못 찾는다.

    행의 값 전체를 이어 붙여 찾는다. 내부 키(_로 시작)는 화면에 없는 값이라 뺀다.
    """
    assert "function srchHay(r)" in SRC
    assert "if(k.charAt(0)==='_')continue;" in SRC
    assert "if(srch){if(srchHay(r).indexOf(srch.toLowerCase())<0)return false;}" in SRC


def test_찾기_라벨이_모든_항목이라고_말한다():
    """라벨이 「상품·수령자」로 남아 있으면 사용자가 범위를 오해한다."""
    assert "검색 (상품·수령자)" not in SRC
    assert "모든 항목에서 찾기" in SRC
