# -*- coding: utf-8 -*-
"""받는 날을 **우리가 추정한 몫**은 따로 센다 — 안 그러면 대조가 쓸모없어진다.

🔴 2026-08-13 스마트스토어 **첫 대조**에서 드러났다(라이브 실측):
      마켓 값   538,606 (5건)
      우리 값 2,542,248 (17건)   → 판정 「불일치 372%」
   그런데 우리 21건을 날짜 근거로 갈라 보니:
      날짜가 마켓 실값   7건    629,656   ← 마켓도 아는 것
      날짜를 우리가 추정 14건 2,215,700   ← 마켓 화면엔 **아직 안 뜨는 것**

   마켓의 「정산예정일 N달」 화면은 **이미 날짜가 정해진 것만** 보여준다.
   우리는 진행 중 주문의 지급일까지 규칙으로 추정해 넣는다 —
   **틀린 게 아니라 정의가 다르다.** 그래서 설명 항목으로 분리한다.
"""
import datetime as dt

import pytest

from lemouton.margin import settle_recon as SR
from lemouton.margin.settle_plan_rules import DEFAULT_RULES

TODAY = dt.date(2026, 8, 13)


class _SP:
    """settle_plan 대역 — 사장님 라이브를 축소한 사건 목록."""

    _MK_KO = {}

    @staticmethod
    def resolve(ln, rules, today=None):
        return {"events": ln["events"]}

    @staticmethod
    def _norm_date(v):
        return v

    @staticmethod
    def bucket_key(d, unit):
        return ""


def _ln(events):
    return {"row": {"정산예정금(배송비포함)": 1, "_settle_source": "real"},
            "market": "smartstore", "account": "A", "events": events}


def _ev(date, amount, src):
    return {"bucket": "confirmed", "date": date, "amount": amount,
            "date_source": src}


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr("lemouton.margin.settle_plan.resolve", _SP.resolve)
    monkeypatch.setattr("lemouton.margin.sell_source._settlement_for",
                        lambda row: (1, "real"))


LINES = [
    _ln([_ev("2026-08-20", 629656, "real")]),        # 마켓도 아는 것
    _ln([_ev("2026-08-25", 2215700, "estimated")]),  # 우리가 날짜를 추정한 것
]


def test_실값_몫과_추정_몫을_갈라_센다():
    o = SR.ours_for("smartstore", LINES, DEFAULT_RULES, today=TODAY)
    assert o["금액"] == 2845356
    assert o["받는날_실값몫"] == 629656 and o["받는날_실값건수"] == 1
    assert o["받는날_추정몫"] == 2215700 and o["받는날_추정건수"] == 1


def test_추정_몫이_차이를_설명하면_불일치가_아니다():
    """🔴 이걸 안 가르면 판정이 늘 「불일치 372%」라 대조가 쓸모없어진다."""
    parsed = {"합계": 629656, "금액건수": 1, "order_col": "", "rows": [],
              "amount_col": "settleExpectAmount", "기간시작": "", "기간끝": ""}
    res = SR.reconcile("smartstore", parsed, LINES, DEFAULT_RULES, today=TODAY)
    assert res["판정"] == "def", res          # 정의차이 — 틀린 게 아니다
    assert "받는 날을 우리가 추정한 몫" in res["왜"]


def test_화면이_그_몫을_그대로_말한다():
    """숨기면 사장님이 차이를 「우리가 틀렸다」로 읽는다."""
    parsed = {"합계": 629656, "금액건수": 1, "order_col": "", "rows": [],
              "amount_col": "x", "기간시작": "", "기간끝": ""}
    res = SR.reconcile("smartstore", parsed, LINES, DEFAULT_RULES, today=TODAY)
    assert res["받는날_실값몫"] == 629656
    assert res["받는날_추정몫"] == 2215700


def test_추정이_하나도_없으면_설명항목을_안_만든다():
    """없는 설명을 붙이면 진짜 불일치가 「정의차이」로 숨는다."""
    only_real = [_ln([_ev("2026-08-20", 100, "real")])]
    parsed = {"합계": 999999, "금액건수": 1, "order_col": "", "rows": [],
              "amount_col": "x", "기간시작": "", "기간끝": ""}
    res = SR.reconcile("smartstore", parsed, only_real, DEFAULT_RULES, today=TODAY)
    assert res["판정"] == "diff"
    assert not any("추정한 몫" in k for k in (res.get("설명후보") or {}))
