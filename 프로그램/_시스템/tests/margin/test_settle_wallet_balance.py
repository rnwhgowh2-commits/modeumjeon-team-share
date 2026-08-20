# -*- coding: utf-8 -*-
"""셀러월렛 미인출 잔액 — 「이미 내 돈인데 아직 안 찾아간 돈」을 받을 돈에서 뺀다.

🔴 왜 (2026-08-06 Wing 화면 실측) — 쿠팡 셀러월렛에 **빠른정산금 잔액 8,112,876원**이
   있었다. 이건 이미 사장님 돈이고 인출만 하면 되는데, **회차 공제에는 안 잡힌다**
   (인출해야 공제된다). 그래서 주문별 정산액에 그대로 남아 「앞으로 받을 돈」에 서 있다.

★ API 창구가 없다 — 셀러월렛은 별도 시스템이라 우리가 읽을 수 없다.
  그래서 「⚙️ 계산 규칙」에서 **사장님이 직접 적는 값**으로 둔다(적은 날짜도 함께).
★ 기간 칸에는 못 나눈다 — 어느 주문 몫인지 알 근거가 없다. 총액에서만 뺀다.
  (없는 근거로 특정 주에 배분하면 그 주가 거짓이 된다)
"""
from __future__ import annotations

import pytest

from lemouton.margin import settle_plan_rules as R


@pytest.fixture(autouse=True)
def _tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_rules_path", lambda: str(tmp_path / "rules.json"))


def test_기본값은_비어있다():
    assert R.load_rules()["wallet_balance"] == {}


def test_계정별_잔액을_적고_읽는다():
    r = R.load_rules()
    r["wallet_balance"] = {"coupang": {"세소(쿠팡)": {"금액": 8_112_876,
                                                      "적은날": "2026-08-06"}}}
    R.save_rules(r)
    got = R.load_rules()["wallet_balance"]
    assert got["coupang"]["세소(쿠팡)"]["금액"] == 8_112_876
    assert got["coupang"]["세소(쿠팡)"]["적은날"] == "2026-08-06"


def test_숫자가_아니거나_음수면_버린다():
    """자금 계산의 입력이라 이상한 값이 들어오면 조용히 반영하면 안 된다."""
    r = R.load_rules()
    r["wallet_balance"] = {"coupang": {"A": {"금액": "몰라"}, "B": {"금액": -5},
                                       "C": {"금액": 1000}}}
    R.save_rules(r)
    got = R.load_rules()["wallet_balance"]["coupang"]
    assert "A" not in got and "B" not in got
    assert got["C"]["금액"] == 1000


def test_모르는_마켓은_버린다():
    r = R.load_rules()
    r["wallet_balance"] = {"없는마켓": {"A": {"금액": 100}}}
    R.save_rules(r)
    assert R.load_rules()["wallet_balance"] == {}


def test_합계를_구한다():
    r = R.load_rules()
    r["wallet_balance"] = {"coupang": {"세소(쿠팡)": {"금액": 8_112_876},
                                       "브랜드마켓(쿠팡)": {"금액": 100_000}},
                           "smartstore": {"브랜드마켓(스스)": {"금액": 50_000}}}
    R.save_rules(r)
    s = R.wallet_summary(R.load_rules())
    assert s["합계"] == 8_262_876
    assert s["계정별"][0]["계정"] == "세소(쿠팡)"      # 큰 금액부터
    assert s["계정별"][0]["금액"] == 8_112_876


def test_적힌_게_없으면_0():
    assert R.wallet_summary(R.load_rules()) == {"합계": 0, "계정별": []}
