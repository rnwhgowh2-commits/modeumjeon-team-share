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
    assert FL.summary() == {"합계": 0, "계정별": [], "차감액": 0,
                            "수령완료분": 0, "회차수": 0}


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


# ══ 총액에서 뺄 몫 가리기 — **두 번 빼면 자금계획이 거꾸로 쪼그라든다** ═══════════
#  2026-08-06 사장님: "이미 받은 돈이면 받을 돈이 아니니 총 받을 금액을 줄여줘야지!"
#  그런데 다 빼면 안 된다:
#   · 지급 완료 회차(DONE) → 그 구간 주문은 이미 「이미 받은 것」으로 총액 밖에 있다 → 또 빼면 이중.
#   · 미지급 회차(SUBJECT) → 그 구간 주문은 아직 「받을 돈」에 서 있는데 이미 인출했다 → **이것만** 뺀다.

_DONE = dict(_JUNE, status="DONE")
_SUBJ = {"market": "coupang", "account": "세소(쿠팡)", "from": "2026-07-01",
         "to": "2026-07-31", "settlementDate": "2026-09-03", "type": "RESERVE",
         "status": "SUBJECT", "fastWithdrawn": 1_500_000}


def test_아직_지급_안_된_회차_몫만_총액에서_뺀다():
    FL.record([_DONE, _SUBJ])
    got = FL.summary()
    assert got["합계"] == 2_916_626 + 1_500_000     # 카드에는 둘 다 보여준다
    assert got["차감액"] == 1_500_000                # 총액에서 빼는 건 SUBJECT 몫만
    assert got["수령완료분"] == 2_916_626            # 이미 총액 밖 — 또 빼면 이중


def test_상태를_모르는_옛_장부는_빼지_않는다():
    """근거 없이 총액을 깎으면 「안 들어온다」는 거짓 안심이 된다 — 모르면 그대로 둔다."""
    FL.record([{k: v for k, v in _JUNE.items()}])   # status 없음
    got = FL.summary()
    assert got["합계"] == 2_916_626
    assert got["차감액"] == 0


def test_차감액도_기간으로_추린다():
    FL.record([_DONE, _SUBJ])
    assert FL.summary(since="2026-07-01")["차감액"] == 1_500_000
    assert FL.summary(until="2026-06-30")["차감액"] == 0


# ══ 역산 오염 걷어내기 — **받지도 않은 돈으로 총액을 깎으면 안 된다** ═══════════
#  인출액은 전용 필드가 없어 공제금액에서 역산한다. 그래서 빠른정산을 안 쓰는 계정의
#  다른 공제(정산차감·전주채권 등)까지 잡힌다. 2026-08-06 라이브: 세소(지정 계정) 말고
#  브랜드마켓(쿠팡)에도 2,148,500 이 잡혔다.

def test_빠른정산_계정이_아닌_행은_걷어낸다():
    FL.record([_SUBJ, dict(_SUBJ, account="브랜드마켓(쿠팡)", fastWithdrawn=2_148_500)])
    assert FL.summary()["합계"] == 1_500_000 + 2_148_500
    지운수 = FL.prune_accounts("coupang", {"세소(쿠팡)"})
    assert 지운수 == 1
    assert FL.summary()["합계"] == 1_500_000          # 지정 계정 몫만 남는다


def test_다른_마켓_행은_건드리지_않는다():
    FL.record([_SUBJ, dict(_SUBJ, market="smartstore", account="브랜드마켓(스스)")])
    FL.prune_accounts("coupang", {"세소(쿠팡)"})
    assert FL.summary()["회차수"] == 2


def test_지울_게_없으면_0():
    FL.record([_SUBJ])
    assert FL.prune_accounts("coupang", {"세소(쿠팡)"}) == 0
