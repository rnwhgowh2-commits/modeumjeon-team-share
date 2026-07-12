# -*- coding: utf-8 -*-
r"""sourcing_parser 무수정 이식 검증 — 함수 존재 + 순수 파싱 동작 + 원본과 바이트 동치(import 줄 제외).

classifier/matcher verbatim 가드와 동일 패턴. 원본:
C:\dev\대량등록 마진계산기\modules\sourcing_parser.py (187줄, 순수 regex 파싱).
유일한 허용 수정 = 2개 import 줄
  `from modules.sourcing_checker import ...` → `from lemouton.margin.sourcing_sites import ...`
(브라우저·네트워크 없음 — 소싱처 order_detail_url 템플릿 역매칭 + 메모 regex 뿐).
"""
import pathlib

import pytest

from lemouton.margin import sourcing_parser as SP

ORIGINAL = pathlib.Path(r"C:\dev\대량등록 마진계산기\modules\sourcing_parser.py")


def test_public_api_present():
    for name in ("extract_memo_info", "detect_order_no_from_url",
                 "_template_to_regex", "fetch_order_no"):
        assert hasattr(SP, name), name


# ── 순수 파싱 대표 케이스 ─────────────────────────────────────────────────

def test_explicit_order_no_in_memo_text():
    """메모에 '주문번호 : XXX' 명시 → 성공, source=메모텍스트."""
    r = SP.fetch_order_no("25.08.03 주문번호 : 202508031019270004 -. 계정 : 무신사/rnwhgowh2")
    assert r["success"] is True
    assert r["order_no"] == "202508031019270004"
    assert r["source"] == "메모텍스트"
    assert r["site_key"] == "musinsa"
    assert r["account_id"] == "rnwhgowh2"


def test_musinsa_order_detail_url_template_match():
    """무신사 주문상세 URL 이 템플릿과 매칭 → 성공, source=URL파싱."""
    r = SP.fetch_order_no(
        "26.04.14 무신사 / rnwhgowh1 은순 https://www.musinsa.com/order/order-detail/ABC123XYZ")
    assert r["success"] is True
    assert r["order_no"] == "ABC123XYZ"
    assert r["source"] == "URL파싱"
    assert r["site_key"] == "musinsa"


def test_ssg_order_detail_query_template_match():
    """SSG 주문상세 URL(쿼리 템플릿 orordNo=) 역매칭 → 성공."""
    r = SP.fetch_order_no("SSG https://pay.ssg.com/myssg/orderInfoDetail.ssg?orordNo=SSG99887766")
    assert r["success"] is True
    assert r["order_no"] == "SSG99887766"
    assert r["source"] == "URL파싱"
    assert r["site_key"] == "ssg"


def test_url_present_but_no_extractable_order_no_fails_honestly():
    """소싱처 URL 은 있으나 주문번호가 path/query 에 없으면 정직한 실패 메시지."""
    r = SP.fetch_order_no("무신사 https://www.musinsa.com/")
    assert r["success"] is False
    assert "수동 입력 필요" in r["error"]
    assert r["order_no"] == ""


def test_empty_memo_fails():
    r = SP.fetch_order_no("")
    assert r["success"] is False
    assert r["error"] == "간단메모 비어있음"


def test_site_detection_from_site_name_text_only():
    """URL 없이 소싱처명 텍스트만으로 site_key 판별(‑SSF)."""
    info = SP.extract_memo_info("26.01.02 SSF / acct1 홍길동")
    assert info["site_key"] == "ssfshop"


def test_detect_order_no_from_url_direct():
    """detect_order_no_from_url: 폴더스타일 oid 템플릿 역매칭."""
    got = SP.detect_order_no_from_url(
        "https://www.folderstyle.com/mypage/orderDetail?oid=FLD777", "folder")
    assert got == "FLD777"
    # 잘못된 site_key → 빈 문자열
    assert SP.detect_order_no_from_url("https://x", "") == ""


def test_no_url_no_order_no_specific_error():
    """URL·주문번호 둘 다 없음 → 그 특정 에러."""
    r = SP.fetch_order_no("무신사 계정 확인 요망")
    assert r["success"] is False
    assert "URL 둘 다 없음" in r["error"]


# ── 무수정 이식 가드 (classifier_verbatim 패턴) ────────────────────────────

def _strip_imports(lines):
    """이식이 허용한 2개 import 줄만 제거(원본·이식본 양쪽에서 동일하게).

    원본: `from modules.sourcing_checker import ...`
    이식: `from lemouton.margin.sourcing_sites import ...`
    두 형태 모두 지워야 나머지가 바이트 동치로 비교된다. 다른 곳의 삽입/변조는
    앵커에 안 걸려 그대로 남으므로 가려지지 않는다.
    """
    out = []
    for ln in lines:
        s = ln.lstrip()
        if s.startswith("from") and (
            "sourcing_checker import" in ln or "sourcing_sites import" in ln
        ):
            continue
        out.append(ln)
    return out


def test_source_is_verbatim_except_import_lines():
    """원본과의 diff 가 2개 import 줄뿐이어야 한다 (docstring 포함 전부 동일).

    원본은 개발자 PC 에만 있는 단독앱이라 CI·팀원 PC 에서는 skip 된다.
    """
    if not ORIGINAL.exists():
        pytest.skip(f"원본 마진계산기 없음: {ORIGINAL}")
    ported = pathlib.Path(SP.__file__).read_text(encoding="utf-8").splitlines()
    original = ORIGINAL.read_text(encoding="utf-8").splitlines()
    assert _strip_imports(ported) == _strip_imports(original), \
        "sourcing_parser 본문이 원본과 다릅니다 — 무수정 이식 규칙 위반"


def test_exactly_two_import_lines_differ():
    """실제로 바뀐 줄이 정확히 그 2개 import 줄인지(과다·과소 치환 방지)."""
    if not ORIGINAL.exists():
        pytest.skip(f"원본 마진계산기 없음: {ORIGINAL}")
    ported = pathlib.Path(SP.__file__).read_text(encoding="utf-8").splitlines()
    original = ORIGINAL.read_text(encoding="utf-8").splitlines()
    diff = [(o, p) for o, p in zip(original, ported) if o != p]
    assert len(diff) == 2, f"바뀐 줄이 2개가 아님: {diff}"
    for o, p in diff:
        assert "modules.sourcing_checker import" in o
        assert "lemouton.margin.sourcing_sites import" in p


def test_original_path_guard_is_skippable():
    """원본 경로가 없는 PC(CI·팀원)에서 FileNotFoundError 로 '에러' 나면 안 된다 (skip 이어야)."""
    import inspect
    for fn in (test_source_is_verbatim_except_import_lines,
               test_exactly_two_import_lines_differ):
        src = inspect.getsource(fn)
        assert "ORIGINAL.exists()" in src, f"{fn.__name__} 에 원본 부재 skip 가드가 없습니다"
