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


# ── 송장번호 칸에 앉은 상태 문구 치유 (2026-07-24 쿠팡 89건) ──────────────

def test_invoice_status_text_is_healed():
    """번호 칸에 「송장입력됨」 같은 문구가 앉으면 '확인 불가'로 정리한다.

    번호인 척하는 문구를 그대로 두면 사장님이 번호로 읽고, 송장 유무 판정도 틀린다.
    '송장미입력'(아직 안 넣음)·'확인 불가'(넣었지만 번호를 못 받음)는 뜻이 달라 유지.
    """
    from lemouton.markets.order_store import _heal_invoice_status_text
    rows = [{"송장입력": "송장입력됨"},
            {"송장입력": "123456789012"},   # 진짜 번호
            {"송장입력": "송장미입력"},
            {"송장입력": "확인 불가"},
            {"송장입력": ""}]
    n = _heal_invoice_status_text(rows)
    assert n == 1
    assert [r["송장입력"] for r in rows] == [
        "확인 불가", "123456789012", "송장미입력", "확인 불가", ""]
    assert rows[0]["송장입력원본"] == "송장입력됨"     # 원본 보존


def test_load_fills_invoice_from_ledger(monkeypatch):
    """저장분을 읽을 때 송장 원장 채움이 **읽기 층에서** 돈다.

    라우트에만 있으면 마진계산기(order_source→order_store.load)가 못 타서
    같은 주문이 화면마다 달라 보인다(11번가 79건).
    """
    from lemouton.markets import order_store as st
    called = {}

    class _Fake:
        @staticmethod
        def fill_missing(rows, **kw):
            called["rows"] = rows
            for r in rows:
                r["송장입력"] = "999"
            return len(rows)

    monkeypatch.setitem(__import__("sys").modules,
                        "lemouton.markets.invoice_ledger", _Fake)
    rows = [{"송장입력": "확인 불가"}]
    assert st._fill_invoice_from_ledger(rows) == 1
    assert rows[0]["송장입력"] == "999"
    assert called["rows"] is rows


def test_ledger_failure_does_not_break_load(monkeypatch):
    """원장이 터져도 주문 조회는 살아야 한다 — 보조기능이기 때문."""
    from lemouton.markets import order_store as st

    class _Boom:
        @staticmethod
        def fill_missing(rows, **kw):
            raise RuntimeError("DB down")

    monkeypatch.setitem(__import__("sys").modules,
                        "lemouton.markets.invoice_ledger", _Boom)
    assert st._fill_invoice_from_ledger([{"송장입력": ""}]) == 0
