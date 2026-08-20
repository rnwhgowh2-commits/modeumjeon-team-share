# -*- coding: utf-8 -*-
"""Phase D 진입 게이트 — 어떤 마켓이든 페이로드가 있으면 업로더를 돌린다.

회귀 방지: 옛 게이트는 스마트스토어·쿠팡만 검사해 롯데온/ESM 단독 변동을 드롭했다.
"""
from lemouton.uploader.orchestrator import has_uploadable_payload, UPLOAD_MARKETS


def test_empty_output_skips():
    assert has_uploadable_payload({}) is False
    assert has_uploadable_payload(None) is False
    assert has_uploadable_payload({"alerts": [1, 2]}) is False  # alerts 뿐 → 전송 대상 아님


def test_smartstore_or_coupang_runs():
    assert has_uploadable_payload({"smartstore": {"M1": {}}}) is True
    assert has_uploadable_payload({"coupang": {"M1": {}}}) is True


def test_lotteon_only_runs():   # 옛 게이트가 드롭하던 케이스
    assert has_uploadable_payload({"lotteon": {"M1": {}}}) is True


def test_esm_only_runs():
    assert has_uploadable_payload({"auction": {"M1": {}}}) is True
    assert has_uploadable_payload({"gmarket": {"M1": {}}}) is True


def test_eleven11_only_runs():
    assert has_uploadable_payload({"eleven11": {"M1": {}}}) is True


def test_empty_market_dict_skips():
    # 마켓 키는 있으나 빈 dict → 전송 대상 없음
    assert has_uploadable_payload({m: {} for m in UPLOAD_MARKETS}) is False
