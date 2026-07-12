# -*- coding: utf-8 -*-
"""classifier 무수정 이식 검증 — 함수 존재 + 3축 상태기계 동작 + 원본과 바이트 동치(import 줄 제외).

matcher 이식(test_matcher_verbatim.py)과 동일한 패턴. 원본:
C:\\dev\\대량등록 마진계산기\\modules\\classifier.py (565줄, 순수 pandas+config).
유일한 허용 수정 = `from config import` → `from lemouton.margin.config import`.
"""
import pathlib

import pytest

from lemouton.margin import classifier as CL

ORIGINAL = pathlib.Path(r"C:\dev\대량등록 마진계산기\modules\classifier.py")


def test_public_api_present():
    for name in ("classify", "_determine_purchase_status", "_determine_delivery_status",
                 "_determine_settlement_status", "_assign_category", "_cross_validate",
                 "_classify_shopmine_only", "_get_check_info", "_memo_override",
                 "CLASSIFICATION_MAP", "PENDING_MAP", "KKADAEGI_MAP", "CHECK_INFO"):
        assert hasattr(CL, name), name


# ── 3축 상태기계 대표 케이스 (매입 · 배송 · 정산) ──────────────────────────

def _mango_row(**over):
    """classify() 가 읽는 더망고+샵마인 필드 최소셋 (match_for_classifier 산출 형태)."""
    row = {
        "사이트주문번호": "SO-1", "구매가격": 30000, "간단메모": "http://shop.com/1",
        "국내송장번호": "1234567890",
        "더망고주문상태 (사용자 연동)": "배송완료",
        "마켓주문상태 (오픈 마켓 연동)": "",
        "마켓주문일자": "2026-07-04",
        "샵마인_매칭": True, "샵마인_정상건존재": True, "샵마인_주문상태": "배송완료",
    }
    row.update(over)
    return row


def _classify_one(row, bucket="matched"):
    matched = [row] if bucket == "matched" else []
    unmatched = [row] if bucket == "mango_unmatched" else []
    only = [row] if bucket == "shopmine_only" else []
    return CL.classify(matched, unmatched, only)["classified"][0]


def test_normal_O_O_O_is_1_1():
    r = _classify_one(_mango_row())
    assert r["매입상태"] == "O" and r["배송상태"] == "O" and r["정산상태"] == "O"
    assert r["상세분류"].startswith("1-1_")


def test_purchase_O_delivery_O_cancel_is_1_4():
    r = _classify_one(_mango_row(**{"샵마인_정상건존재": False, "샵마인_주문상태": "취소완료"}))
    assert r["정산상태"] == "X_취소"
    assert r["상세분류"].startswith("1-4_")


def test_pending_status_is_1_11():
    r = _classify_one(_mango_row(**{"더망고주문상태 (사용자 연동)": "결제완료", "국내송장번호": ""}))
    assert r["배송상태"] == "발송대기"
    assert r["상세분류"].startswith("1-11_")


def test_kkadaegi_status_is_1_12():
    r = _classify_one(_mango_row(**{"더망고주문상태 (사용자 연동)": "해외현지배송중", "국내송장번호": ""}))
    assert r["배송상태"] == "까대기"
    assert r["상세분류"].startswith("1-12_")


def test_mango_unmatched_is_X_mismatch_1_6():
    r = _classify_one(_mango_row(**{"샵마인_매칭": False}), bucket="mango_unmatched")
    assert r["정산상태"] == "X_미매칭"
    assert r["상세분류"].startswith("1-6_")


def test_shopmine_only_cancel_is_5_7():
    r = _classify_one({"주문상태": "취소완료"}, bucket="shopmine_only")
    assert r["대분류"] == "5_교차검증"
    assert r["상세분류"].startswith("5-7_")


def test_shopmine_only_revert_is_5_6():
    r = _classify_one({"주문상태": "취소철회(배송완료)"}, bucket="shopmine_only")
    assert r["상세분류"].startswith("5-6_")


def test_summary_counts_by_major_and_detail():
    out = CL.classify([_mango_row()], [], [])
    assert out["summary"]["1_매입O"]["1-1_정상거래"] == 1


# ── 무수정 이식 가드 (matcher_verbatim 패턴) ──────────────────────────────

def test_source_is_verbatim_except_import_lines():
    """원본과의 diff 가 config import 줄뿐이어야 한다 (docstring 포함 전부 동일).

    원본은 개발자 PC 에만 있는 단독앱이라 CI·팀원 PC 에서는 skip 된다.
    """
    if not ORIGINAL.exists():
        pytest.skip(f"원본 마진계산기 없음: {ORIGINAL}")
    ported = pathlib.Path(CL.__file__).read_text(encoding="utf-8").splitlines()
    original = ORIGINAL.read_text(encoding="utf-8").splitlines()

    def strip(lines):
        # import 문 줄만 제거 (바로 그 줄만 diff 허용) — 다른 곳의 "config import" 주석은
        # 남겨서 삽입/변조를 가리지 않도록 앵커링한다.
        return [ln for ln in lines
                if not (ln.lstrip().startswith("from") and "config import" in ln)]

    assert strip(ported) == strip(original), \
        "classifier 본문이 원본과 다릅니다 — 무수정 이식 규칙 위반"


def test_original_path_guard_is_skippable():
    """원본 경로가 없는 PC(CI·팀원)에서 FileNotFoundError 로 '에러' 나면 안 된다 (skip 이어야)."""
    import inspect
    src = inspect.getsource(test_source_is_verbatim_except_import_lines)
    assert "ORIGINAL.exists()" in src, "원본 부재 시 skip 가드가 없습니다"
