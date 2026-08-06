# -*- coding: utf-8 -*-
"""빠른정산 선인출 장부 — 「이미 받은 돈」이 「받을 돈」에 두 번 서지 않게.

🔴 2026-08-06 사장님: "미리 받은 건 나중에 또 받으면 중복이니 확실하게 해줘.
   더 받는 줄 알았다가 안 들어오면 자금 계획이 너무 뻥튀기 되어 있을 듯해."
"""
from __future__ import annotations

import pytest

from lemouton.margin import settle_fast_ledger as FL


@pytest.fixture(autouse=True)
def _tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(FL, "_path", lambda: str(tmp_path / "fast.json"))


_JUNE = {"market": "coupang", "account": "세소(쿠팡)", "from": "2026-06-01",
         "to": "2026-06-30", "settlementDate": "2026-08-03", "type": "RESERVE",
         "fastWithdrawn": 2_916_626}


def test_장부가_비어있으면_0():
    assert FL.summary() == {"합계": 0, "계정별": [], "회차수": 0}


def test_회차를_적고_계정별로_합친다():
    assert FL.record([_JUNE]) == 1
    got = FL.summary()
    assert got["합계"] == 2_916_626
    assert got["계정별"][0]["계정"] == "세소(쿠팡)"
    assert got["계정별"][0]["최근지급일"] == "2026-08-03"


def test_같은_회차를_다시_훑어도_두_번_쌓이지_않는다():
    """스윕은 30분마다 같은 달을 다시 본다 — 겹쳐 쌓이면 자금계획이 거꾸로 부푼다."""
    FL.record([_JUNE])
    FL.record([_JUNE])
    assert FL.summary()["합계"] == 2_916_626


def test_금액이_바뀌면_최신값으로_덮어쓴다():
    FL.record([_JUNE])
    FL.record([dict(_JUNE, fastWithdrawn=3_000_000)])
    assert FL.summary()["합계"] == 3_000_000


def test_인출_0인_회차는_담지_않는다():
    """빠른정산을 안 쓰는 계정까지 장부에 세우면 「이미 받았다」가 거짓이 된다."""
    assert FL.record([dict(_JUNE, fastWithdrawn=0)]) == 0
    assert FL.summary()["합계"] == 0


def test_기간_밖_회차는_빼고_센다():
    FL.record([_JUNE, dict(_JUNE, **{"from": "2026-07-01", "to": "2026-07-31",
                                     "settlementDate": "2026-09-03",
                                     "fastWithdrawn": 1_000_000})])
    assert FL.summary(since="2026-07-01")["합계"] == 1_000_000
    assert FL.summary(until="2026-06-30")["합계"] == 2_916_626
    assert FL.summary()["합계"] == 3_916_626


def test_깨진_파일이어도_0으로_버틴다(tmp_path):
    (tmp_path / "fast.json").write_text("{망가짐", encoding="utf-8")
    assert FL.summary()["합계"] == 0
