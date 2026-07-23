# -*- coding: utf-8 -*-
"""11번가 주문상태 코드 → 한글 (2026-07-23 저장분 411건 숫자 노출 사고)."""
from shared.platforms.eleven11.orders import ORD_PRD_STAT_KO, status_ko
from lemouton.markets.order_store import _heal_eleven11_status


def test_known_codes_become_korean():
    assert status_ko("901") == "수취완료"      # 문서 '수취확인' → 정산 판정표에 맞춰 통일
    assert status_ko("501") == "배송완료"
    assert status_ko("A01") == "반품완료"


def test_korean_passes_through():
    assert status_ko("배송중") == "배송중"


def test_unknown_code_is_not_invented():
    assert status_ko("999") == "999"           # 지어내지 않는다
    assert status_ko("") == "" and status_ko(None) == ""


def test_settlement_vocabulary_matches():
    """901 을 '수취확인' 으로 두면 정산 판정에서 411건이 조용히 빠진다."""
    from lemouton.margin.config import SETTLEMENT_O_EXACT
    assert ORD_PRD_STAT_KO["901"] in SETTLEMENT_O_EXACT


def test_stored_numeric_status_is_healed_on_read():
    """★ 치유는 order_store.load 안에 있어야 한다 — 주문내역 화면은 order_source 를
    거치지 않고 load 를 직접 부른다(상류에만 뒀다가 화면에 숫자가 그대로 남았다)."""
    rows = [{"판매처": "11번가", "주문상태": "901"},
            {"판매처": "11번가", "주문상태": "501"},
            {"판매처": "11번가", "주문상태": "배송중"},
            {"판매처": "롯데온", "주문상태": "11"}]      # 다른 마켓은 손대지 않는다
    n = _heal_eleven11_status(rows)
    assert n == 2
    assert [r["주문상태"] for r in rows] == ["수취완료", "배송완료", "배송중", "11"]
    assert rows[0]["주문상태원본"] == "901"              # 원본 코드 보존
