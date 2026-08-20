# -*- coding: utf-8 -*-
"""빠른정산 선인출을 **그 기간 칸에서** 뺀다 — 화면의 주인공은 「기간 내 얼마 받나」.

🔴 2026-08-06 사장님: "올바른 방향으로 사용자가 결국 기간내 얼마 받을지 아는게 중요해.
   이미 받은걸로 헷갈리게 안했으면 좋겠어."

앞선 방식은 총액에서만 빼서, **기간별 표는 여전히 부풀어 있었다**(8월 2주차에 얼마 들어오나를
보면 이미 받은 돈이 섞여 있음). 회차의 **지급예정일이 속한 칸**에서 빼야 그 칸이 진실이 된다.

★ 이미 지급이 끝난 회차(DONE)는 건드리지 않는다 — 그 주문은 이미 「받은 것」이라 칸에 없다.
★ 뺄 칸이 없으면(그 날짜에 받을 돈이 없음) **빼지 않고 따로 알린다** — 없는 돈을 깎으면 거짓이 된다.
"""
from __future__ import annotations

from lemouton.margin import settle_plan as SP


def _agg(unit="week"):
    """8/03 주(월요일 2026-08-03)와 8/10 주에 받을 돈이 있는 집계 모양."""
    return {
        "kpi": {"confirmed_future": 700_000, "unconfirmed_future": 300_000,
                "overdue": 0, "undated": 0, "assumed_paid": 0, "risk": 0,
                "paid": 0, "total_uncollected": 1_000_000},
        "buckets": [
            {"key": "2026-08-03", "total": 600_000, "markets": {"coupang": {
                "confirmed": 400_000, "unconfirmed": 200_000,
                "accounts": {"세소(쿠팡)": {"confirmed": 400_000, "unconfirmed": 200_000}}}}},
            {"key": "2026-08-10", "total": 400_000, "markets": {"coupang": {
                "confirmed": 300_000, "unconfirmed": 100_000,
                "accounts": {"세소(쿠팡)": {"confirmed": 300_000, "unconfirmed": 100_000}}}}},
        ],
    }


_LEDGER = [{"market": "coupang", "account": "세소(쿠팡)", "from": "2026-07-01",
            "to": "2026-07-07", "settlementDate": "2026-08-07", "type": "WEEKLY",
            "status": "SUBJECT", "fastWithdrawn": 250_000}]


def test_회차_지급일이_속한_칸에서_뺀다():
    got = SP.apply_fast_withdrawn(_agg(), _LEDGER, unit="week")
    b = {x["key"]: x for x in got["buckets"]}
    assert b["2026-08-03"]["total"] == 350_000        # 60만 − 25만
    assert b["2026-08-10"]["total"] == 400_000        # 다른 칸은 그대로


def test_그_칸의_마켓_계정에도_적어준다():
    got = SP.apply_fast_withdrawn(_agg(), _LEDGER, unit="week")
    mk = got["buckets"][0]["markets"]["coupang"]
    assert mk["fast"] == 250_000
    assert mk["accounts"]["세소(쿠팡)"]["fast"] == 250_000
    # 확정·미확정 내역은 건드리지 않는다 — 회차 단위 금액이라 부류로 못 나눈다
    assert mk["confirmed"] == 400_000 and mk["unconfirmed"] == 200_000


def test_총액도_실제로_뺀_만큼만_줄어든다():
    got = SP.apply_fast_withdrawn(_agg(), _LEDGER, unit="week")
    assert got["kpi"]["fast_withdrawn"] == 250_000
    assert got["kpi"]["net_uncollected"] == 750_000


def test_지급_끝난_회차는_건드리지_않는다():
    """그 주문은 이미 「받은 것」이라 칸에 없다 — 또 빼면 이중 차감."""
    done = [dict(_LEDGER[0], status="DONE")]
    got = SP.apply_fast_withdrawn(_agg(), done, unit="week")
    assert got["kpi"]["fast_withdrawn"] == 0
    assert got["buckets"][0]["total"] == 600_000


def test_뺄_칸이_없으면_안_빼고_따로_알린다():
    """그 날짜에 받을 돈이 없는데 깎으면 거짓이 된다."""
    far = [dict(_LEDGER[0], settlementDate="2026-12-25")]
    got = SP.apply_fast_withdrawn(_agg(), far, unit="week")
    assert got["kpi"]["fast_withdrawn"] == 0
    assert got["kpi"]["net_uncollected"] == 1_000_000
    assert got["빠른정산_칸밖"] == 250_000


def test_칸에_있는_돈보다_많으면_그_칸은_0까지만():
    big = [dict(_LEDGER[0], fastWithdrawn=900_000)]
    got = SP.apply_fast_withdrawn(_agg(), big, unit="week")
    assert got["buckets"][0]["total"] == 0
    assert got["kpi"]["fast_withdrawn"] == 600_000      # 실제로 뺀 만큼만
    assert got["빠른정산_칸밖"] == 300_000               # 못 뺀 나머지는 숨기지 않는다


def test_월_단위로_봐도_같은_칸을_찾는다():
    a = _agg(); a["buckets"][0]["key"] = "2026-08"; a["buckets"][1]["key"] = "2026-09"
    got = SP.apply_fast_withdrawn(a, _LEDGER, unit="month")
    assert got["buckets"][0]["total"] == 350_000


def test_상태를_모르는_옛_장부는_빼지_않는다():
    old = [{k: v for k, v in _LEDGER[0].items() if k != "status"}]
    got = SP.apply_fast_withdrawn(_agg(), old, unit="week")
    assert got["kpi"]["fast_withdrawn"] == 0
