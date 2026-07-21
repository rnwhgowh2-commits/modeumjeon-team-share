# -*- coding: utf-8 -*-
"""롯데온 백필 실결제 = 할인 반영 — SettleProduct(정가)에 SettleItmdSales 할인 조인.

2026-07-22 샵마인 대사: 백필 행 실결제가 slAmt(정가)라 658건 불일치(샵마인=할인
반영). SettleItmdSales 가 (odNo,odSeq) 키로 셀러즉시할인·상품할인(셀러/이커머스
부담)을 준다 — 정가에서 빼서 실결제를 복원한다.
"""
import datetime as _dt


class _Cli:
    def __init__(self):
        self.calls = []

    def request(self, method=None, path=None, body=None):
        self.calls.append(path)
        if path.endswith("/SettleProduct"):
            return {"returnCode": "SUCCESS", "data": [
                {"odNo": "LO1", "odSeq": "1", "procSeq": "1", "odTypCd": "10",
                 "spdNm": "상품", "sitmNm": "옵션", "slQty": "1", "slUprc": "27800",
                 "slAmt": "27800", "pyDttm": "20260422120000"}]}
        if path.endswith("/SettleItmdSales"):
            return {"returnCode": "SUCCESS", "data": [
                {"odNo": "LO1", "odSeq": "1", "procSeq": "1",
                 "slAmt": "27800", "slrDcAmt": "2000", "pdDcOcoAmt": "1000",
                 "pdDcSlrAmt": "350", "pymtAmt": "21000"}]}
        return {"returnCode": "SUCCESS", "data": []}


def test_백필_실결제는_정가에서_할인을_뺀_값():
    from shared.platforms.lotteon import settle_orders as so
    rows = so.order_rows(_dt.datetime(2026, 4, 1), _dt.datetime(2026, 4, 29),
                         client=_Cli())
    assert rows[0]["실결제금액"] == 27800 - 2000 - 1000 - 350   # 24,450
    assert rows[0]["단가"] == 27800                             # 정가는 단가로 보존


def test_할인정보가_없으면_실결제를_비운다():
    """조인 상대가 없으면 정가를 실결제로 두지 않는다 — 정가≠실결제(658건 사고 재발 방지).
    비워 두면 fill_claim_blanks/후속 조회가 채우고, 화면은 공란=미확보로 정직하게 보인다."""
    class _NoItmd(_Cli):
        def request(self, method=None, path=None, body=None):
            r = super().request(method, path, body)
            if path.endswith("/SettleItmdSales"):
                return {"returnCode": "SUCCESS", "data": []}
            return r

    from shared.platforms.lotteon import settle_orders as so
    rows = so.order_rows(_dt.datetime(2026, 4, 1), _dt.datetime(2026, 4, 29),
                         client=_NoItmd())
    assert rows[0]["실결제금액"] == ""
