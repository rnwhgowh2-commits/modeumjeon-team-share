# -*- coding: utf-8 -*-
"""쿠팡 정산 대조기 — 「우리가 받을 거라 계산한 돈」 vs 「쿠팡이 실제로 준 돈」.

🔴 왜 필요한가(2026-08-06 사장님 지적) — 우리 정산예정금액은 **주문별 정산액**(매출내역)
   을 쓴다. 그런데 실제 입금은 정산 **회차**의 finalAmount 이고, 거기서 서비스이용료·
   정산차감·전주채권 등이 **더 빠진다**. 그 차이를 아무도 안 보고 있었다 —
   라이브 정산율이 90~92% 로 수수료(6~18%)와 어긋나던 것도 이 자리일 수 있다.
   「이걸 놓치면 엄청난 정산 금액 차이」(사장님) → 수치로 드러낸다.

대조 축 = 매출인식월. 회차의 [from,to] 안에 주문의 recognitionDate 가 드는 것끼리 묶는다.
"""
from __future__ import annotations


def test_우리계산과_실제지급을_나란히_놓고_차이를_낸다():
    from lemouton.margin import settle_parity as SP

    hist = [{"type": "WEEKLY", "status": "DONE", "settlementDate": "2026-06-26",
             "from": "2026-06-01", "to": "2026-06-07", "finalAmount": 1000000},
            {"type": "RESERVE", "status": "DONE", "settlementDate": "2026-08-03",
             "from": "2026-06-01", "to": "2026-06-30", "finalAmount": 300000}]
    ours = [{"주문번호": "A", "_recognition_date": "2026-06-03", "정산액": 800000},
            {"주문번호": "B", "_recognition_date": "2026-06-05", "정산액": 600000},
            {"주문번호": "C", "_recognition_date": "2026-07-01", "정산액": 999}]  # 구간 밖

    r = SP.compare(hist, ours)
    assert r["실지급합"] == 1300000
    assert r["우리계산합"] == 1400000          # 구간 안 두 건만
    assert r["차이"] == 100000                  # 우리가 10만 더 크게 봄
    assert r["차이율"] == 7.1                   # 10만 / 140만
    assert r["대조건수"] == 2
    assert r["구간밖건수"] == 1
    assert r["판정"] == "우리가 더 큼"


def test_차이가_작으면_정상으로_본다():
    from lemouton.margin import settle_parity as SP
    hist = [{"type": "WEEKLY", "status": "DONE", "settlementDate": "2026-06-26",
             "from": "2026-06-01", "to": "2026-06-30", "finalAmount": 1000000}]
    ours = [{"주문번호": "A", "_recognition_date": "2026-06-03", "정산액": 1005000}]
    r = SP.compare(hist, ours)
    assert r["판정"] == "정상"                  # 0.5% — 반올림·소액 차감 범위


def test_재료가_없으면_판정하지_않는다():
    from lemouton.margin import settle_parity as SP
    assert SP.compare([], [])["판정"] == "대조불가"
    assert SP.compare([{"type": "WEEKLY", "status": "DONE",
                        "settlementDate": "2026-06-26", "from": "2026-06-01",
                        "to": "2026-06-30", "finalAmount": 100}], [])["판정"] == "대조불가"


def test_지급예정_회차는_빼고_완료분만_센다():
    """아직 안 준 돈을 「실지급」이라 하면 대조가 거짓이 된다."""
    from lemouton.margin import settle_parity as SP
    hist = [{"type": "WEEKLY", "status": "DONE", "settlementDate": "2026-06-26",
             "from": "2026-06-01", "to": "2026-06-30", "finalAmount": 500000},
            {"type": "WEEKLY", "status": "SUBJECT", "settlementDate": "2026-09-01",
             "from": "2026-06-01", "to": "2026-06-30", "finalAmount": 400000}]
    ours = [{"주문번호": "A", "_recognition_date": "2026-06-03", "정산액": 500000}]
    r = SP.compare(hist, ours)
    assert r["실지급합"] == 500000
    assert r["미지급회차합"] == 400000          # 숨기지 않고 따로 보여준다
