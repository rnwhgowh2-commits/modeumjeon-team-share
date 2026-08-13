# -*- coding: utf-8 -*-
"""로켓그로스 「앞으로 받을 돈」 — 사장님 Wing 화면 **실물 25회차**로 못 박는다.

🔴 2026-08-13 사장님 화면(정산일 창 두 개 · 총 25회차)을 그대로 옮겨 왔다.
   화면 「지급 예상금액」 = **7,818,202**.

   Σ최종지급액 (21건 전부)              = 9,045,123
   Σ최종지급액 (정산일 이미 지남)         = 1,226,921
   Σ최종지급액 (오늘 이후 ~ 한 달 이내)    = **7,818,202**  ← 화면과 원 단위 일치
   Σ최종지급액 (오늘 이후 **전부**)        = 9,528,423      ← 화면이 아니다(창이 있다)

🔴 옛 계산 `지급액 − 빠른정산` 은 라이브에서 9,508,138 이라 1,689,936 어긋났다.
   ① 기간 제한이 없어 이미 받은 회차까지 셌고
   ② 마켓이 이미 계산해 준 `최종지급액` 을 두고 우리가 다시 만들었다.
"""
import datetime as dt

import pytest

from lemouton.margin import rg_settlement as RG

TODAY = dt.date(2026, 8, 13)
SCREEN = 7_818_202          # 사장님 화면 「지급 예상금액」


class _Row:
    def __init__(self, sd, ratio, fin):
        self.settlement_date, self.ratio, self.final_amount = sd, ratio, fin
        self.payable_amount = self.fast_withdrawn = 0
        self.account = "세소(쿠팡)"


class _Sess:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *a):
        return self

    def all(self):
        return self._rows

    def close(self):
        pass


#  ── 사장님 화면 그대로 (정산일, 지급비율, 최종지급액) ──────────────────────
#  창①  정산일 2026.7.13~9.13 · 21건
W1 = [
    ("2026-08-03", 30, 127470), ("2026-08-03", 30, 113202),
    ("2026-07-20", 70, 193790), ("2026-08-03", 30, 83053),
    ("2026-07-27", 70, 0),      ("2026-08-03", 30, 0),
    ("2026-08-03", 70, 709406), ("2026-08-10", 30, 0),
    ("2026-08-03", 70, 0),      ("2026-08-10", 30, 0),
    ("2026-08-10", 70, 0),      ("2026-09-01", 30, 0),
    ("2026-08-14", 70, 1920756), ("2026-09-01", 30, 942766),
    ("2026-08-24", 70, 1652539), ("2026-09-01", 30, 813073),
    ("2026-08-31", 70, 1371614), ("2026-09-07", 30, 327194),
    ("2026-08-31", 70, 0),      ("2026-09-07", 30, 0),
    ("2026-09-07", 70, 790260),
]
#  창②  정산일 2026.9.13~10.14 · 4건 (전부 오늘 이후지만 **화면 숫자엔 안 들어간다**)
W2 = [
    ("2026-10-01", 30, 379125), ("2026-09-14", 70, 479717),
    ("2026-10-01", 30, 242991), ("2026-10-07", 100, 608388),
]
ALL = [_Row(*r) for r in (W1 + W2)]


def test_화면_지급예상금액과_원_단위로_같다():
    """🔴 이 시험이 이 규칙의 유일한 근거다 — 깨지면 규칙부터 다시 잰다."""
    got = RG.ahead_summary(today=TODAY, session=_Sess(ALL))
    assert got["금액"] == SCREEN, got


def test_이미_지난_정산일은_안_센다():
    """이미 받은 돈을 「앞으로 받을 돈」에 넣으면 자금계획이 통째로 부푼다."""
    got = RG.ahead_summary(today=TODAY, session=_Sess(ALL))
    assert got["이미받은회차합"] == 1_226_921


def test_한_달_밖_회차는_화면_숫자가_아니다():
    """「오늘 이후 전부」로 세면 9,528,423 — 화면(7,818,202)과 다르다."""
    all_future = sum(r.final_amount for r in ALL
                     if r.settlement_date > TODAY.isoformat())
    assert all_future == 9_528_423
    assert all_future != SCREEN


def test_창을_넓히면_한_달_밖_회차가_들어온다():
    """창 길이는 상수다 — 나중에 어긋나면 여기부터 다시 본다."""
    wide = RG.ahead_summary(today=TODAY, window_days=90, session=_Sess(ALL))
    assert wide["금액"] == 9_528_423


def test_정산일이_없는_회차는_시기를_못_가르니_안_센다():
    rows = ALL + [_Row("", 70, 999999)]
    assert RG.ahead_summary(today=TODAY, session=_Sess(rows))["금액"] == SCREEN


def test_옛_계산과_다르다는_것을_못_박는다():
    """`지급액 − 빠른정산`(기간 무제한)은 화면과 다르다 — 되돌리면 이 시험이 깨진다."""
    got = RG.ahead_summary(today=TODAY, session=_Sess(ALL))
    assert got["구성"].startswith("최종지급액 합")
    assert "빠른정산" not in got["구성"]
