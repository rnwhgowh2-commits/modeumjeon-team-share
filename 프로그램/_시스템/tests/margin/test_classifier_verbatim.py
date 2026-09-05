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
                 "_classify_market_only", "_get_check_info", "_memo_override",
                 "CLASSIFICATION_MAP", "PENDING_MAP", "KKADAEGI_MAP", "CHECK_INFO"):
        assert hasattr(CL, name), name


# ── 3축 상태기계 대표 케이스 (매입 · 배송 · 정산) ──────────────────────────

def _mango_row(**over):
    """classify() 가 읽는 더망고+판매처 필드 최소셋 (match_for_classifier 산출 형태)."""
    row = {
        "사이트주문번호": "SO-1", "구매가격": 30000, "간단메모": "http://shop.com/1",
        "국내송장번호": "1234567890",
        "더망고주문상태 (사용자 연동)": "배송완료",
        "마켓주문상태 (오픈 마켓 연동)": "",
        "마켓주문일자": "2026-07-04",
        "판매처_매칭": True, "판매처_정상건존재": True, "판매처_주문상태": "배송완료",
    }
    row.update(over)
    return row


def _classify_one(row, bucket="matched"):
    matched = [row] if bucket == "matched" else []
    unmatched = [row] if bucket == "mango_unmatched" else []
    only = [row] if bucket == "market_only" else []
    return CL.classify(matched, unmatched, only)["classified"][0]


def test_normal_O_O_O_is_1_1():
    r = _classify_one(_mango_row())
    assert r["매입상태"] == "O" and r["배송상태"] == "O" and r["정산상태"] == "O"
    assert r["상세분류"].startswith("1-1_")


def test_purchase_O_delivery_O_cancel_is_1_4():
    r = _classify_one(_mango_row(**{"판매처_정상건존재": False, "판매처_주문상태": "취소완료"}))
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
    r = _classify_one(_mango_row(**{"판매처_매칭": False}), bucket="mango_unmatched")
    assert r["정산상태"] == "X_미매칭"
    assert r["상세분류"].startswith("1-6_")


def test_market_only_cancel_is_5_7():
    r = _classify_one({"주문상태": "취소완료"}, bucket="market_only")
    assert r["대분류"] == "5_교차검증"
    assert r["상세분류"].startswith("5-7_")


def test_market_only_revert_is_5_6():
    r = _classify_one({"주문상태": "취소철회(배송완료)"}, bucket="market_only")
    assert r["상세분류"].startswith("5-6_")


def test_summary_counts_by_major_and_detail():
    out = CL.classify([_mango_row()], [], [])
    assert out["summary"]["1_매입O"]["1-1_정상거래"] == 1


# ── 무수정 이식 가드 (matcher_verbatim 패턴) ──────────────────────────────

def _undo_shopmine_word_purge(text: str) -> str:
    """2026-09 "샵마인" 단어 제거 작업(사장님 지시)에서 의도적으로 바꾼 식별자를
    원본 이름으로 되돌린다 — 무수정 이식 가드가 이 사전 승인된 리네임까지 diff 로
    잡으면 안 되므로, 비교 직전에만 원복해 실제 로직 변조와 구분한다."""
    reps = [
        ("MARKET_SELL_COLS", "SHOPMINE_COLS"),
        ("_classify_market_only", "_classify_shopmine_only"),
        ("market_only", "shopmine_only"),
        ("mk_sell_status", "shopmine_status"),
        ("판매처에 주문기록", "샵마인에 주문기록"),
        ("판매처주문상태", "샵마인주문상태"),
        ("데이터미비+판매처누락", "데이터미비+샵마인누락"),
        ("이상(매입불명+배송+판매처없음)", "이상(매입불명+배송+샵마인없음)"),
        ("판매처_", "샵마인_"),
        ("더망고+판매처", "더망고+샵마인"),
        ("판매처만", "샵마인만"),
        # 안내 문구(카드 사유·대응 텍스트) 속 순수 산문 '판매처' — 전부 원본의
        # '샵마인' 한 단어였다(실측 확인). 문구 전체를 앵커로 써서, 아래
        # '"판매처_판매처"'(원래부터 있던 필드 '판매처'와는 무관 — 그건 그대로 둔다)
        # 같은 의미 다른 자리의 '판매처'까지 잘못 되돌리지 않게 한다.
        ("판매처 동기화 오류면 재동기화, 마켓에서", "샵마인 동기화 오류면 재동기화, 마켓에서"),
        ("매입했는데 판매처 미매칭", "매입했는데 샵마인 미매칭"),
        ("있으면 판매처 동기화", "있으면 샵마인 동기화"),
        ("매입 흔적만 있고 판매처에도 없음", "매입 흔적만 있고 샵마인에도 없음"),
        ("매입 흔적+미배송+판매처 미매칭", "매입 흔적+미배송+샵마인 미매칭"),
        ("미배송 + 판매처 미매칭 → 정상", "미배송 + 샵마인 미매칭 → 정상"),
        ("배송 O + 판매처 미매칭", "배송 O + 샵마인 미매칭"),
        ("주문 흔적, 판매처 미매칭", "주문 흔적, 샵마인 미매칭"),
        ("매입불명+배송됨+판매처 미매칭", "매입불명+배송됨+샵마인 미매칭"),
        ("송장전송실패 + 판매처 미매칭", "송장전송실패 + 샵마인 미매칭"),
        ("판매처에만 있고 더망고에 없음", "샵마인에만 있고 더망고에 없음"),
        ('"판매처에만 있는 취소/반품건', '"샵마인에만 있는 취소/반품건'),
        ('"판매처에만 있는 반품건', '"샵마인에만 있는 반품건'),
        ("X_미매칭: 판매처 매칭 안됨", "X_미매칭: 샵마인 매칭 안됨"),
        # 필드 키 '판매처_판매처' — 접두어만 되돌린다(접미어 '판매처'는 원본에도
        # '판매처'였던 서로 다른 개념 — 함께 되돌리면 이중 치환이 된다).
        ('"판매처_판매처"', '"샵마인_판매처"'),
    ]
    for new, old in reps:
        text = text.replace(new, old)
    return text


def test_source_is_verbatim_except_import_lines():
    """원본과의 diff 가 config import 줄 + 승인된 샵마인 리네임뿐이어야 한다.

    원본은 개발자 PC 에만 있는 단독앱이라 CI·팀원 PC 에서는 skip 된다.
    """
    if not ORIGINAL.exists():
        pytest.skip(f"원본 마진계산기 없음: {ORIGINAL}")
    ported = _undo_shopmine_word_purge(
        pathlib.Path(CL.__file__).read_text(encoding="utf-8")).splitlines()
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
