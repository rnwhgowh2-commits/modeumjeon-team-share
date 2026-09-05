# -*- coding: utf-8 -*-
"""마켓 정산 대조 — 마켓 화면 엑셀 ↔ 우리 정산예정금액 (노션 주문관리 c-4).

사장님: "실마켓 계정 접속해서 실제 정산받는 금액과 비교 및 정합성 검사."

🔴 이 엔진에서 가장 위험한 실패는 「못 읽었는데 0원으로 읽고 일치라고 말하는 것」이다.
   그래서 파싱 실패를 **크게** 시험한다.
"""
import datetime as dt
import io

import pytest

from lemouton.margin import settle_recon as SR
from lemouton.margin.settle_plan_rules import DEFAULT_RULES

TODAY = dt.date(2026, 8, 12)


def _xlsx(rows, cols=None):
    """행 목록 → .xlsx 바이트."""
    import pandas as pd
    df = pd.DataFrame(rows, columns=cols) if cols else pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def _line(market="coupang", incl=10000, date=None, status="구매확정",
          account="계정A", src="real"):
    row = {"주문상태": status, "정산예정금(배송비포함)": incl,
           "정산예정금액": incl, "_settle_source": src, "배송비": 0}
    if date:
        row["정산예정일"] = date
    return {"row": row, "market": market, "account": account,
            "status_at": dt.datetime(2026, 8, 1, 12, 0)}


# ── 파싱 ─────────────────────────────────────────────────────────────────────

def test_금액열을_별칭으로_찾는다():
    b = _xlsx([{"정산일": "2026-08-20", "최종지급액": "1,234,000"},
               {"정산일": "2026-08-27", "최종지급액": "766,000"}])
    p = SR.parse_sheet(b)
    assert p["amount_col"] == "최종지급액"
    assert p["합계"] == 2000000
    assert p["금액건수"] == 2
    assert p["기간시작"] == "2026-08-20" and p["기간끝"] == "2026-08-27"


def test_괄호_붙은_열이름도_찾는다():
    b = _xlsx([{"정산일": "2026-08-20", "최종지급액 (원)": 500}])
    assert SR.parse_sheet(b)["합계"] == 500


def test_금액열을_못_찾으면_본_열이름을_말하며_실패한다():
    """🔴 조용히 0원으로 넘어가면 「대조했는데 일치」라는 가장 나쁜 거짓말이 된다."""
    b = _xlsx([{"이상한열": 1, "또다른열": 2}])
    with pytest.raises(ValueError) as e:
        SR.parse_sheet(b)
    msg = str(e.value)
    assert "이상한열" in msg and "또다른열" in msg      # 무엇을 봤는지 알려준다
    assert "찾지 못했습니다" in msg


def test_합계줄과_빈줄은_건너뛴다():
    b = _xlsx([{"최종지급액": 100}, {"최종지급액": None}, {"최종지급액": ""}])
    p = SR.parse_sheet(b)
    assert p["합계"] == 100 and p["금액건수"] == 1


def test_빠른정산_열이_있으면_따로_센다():
    b = _xlsx([{"최종지급액": 1000, "빠른정산금액": 300}])
    p = SR.parse_sheet(b)
    assert p["빠른정산합계"] == 300


# ── 우리 값 ──────────────────────────────────────────────────────────────────

def test_우리값은_마켓과_같은_창으로_잰다():
    """쿠팡 일반정산 구매확정 = 정산일 2달 창. 창 밖은 안 센다."""
    lines = [_line(date="2026-08-20", incl=100),        # 창 안
             _line(date="2026-12-01", incl=999)]        # 창 밖(60일 초과)
    o = SR.ours_for("coupang_confirmed", lines, DEFAULT_RULES, today=TODAY,
                    fast_summary={})
    assert o["가능"] is True and o["금액"] == 100 and o["건수"] == 1


def test_다른_마켓_줄은_안_센다():
    lines = [_line(market="smartstore", date="2026-08-20", incl=100)]
    o = SR.ours_for("coupang_confirmed", lines, DEFAULT_RULES, today=TODAY)
    assert o["금액"] == 0


def test_마켓화면이_빠른정산을_뺀_항목이면_우리도_뺀다():
    """쿠팡 정산예정 화면엔 빠른정산 제외분만 나온다 — 같은 것을 비교해야 한다."""
    lines = [_line(date="2026-08-20", incl=1000)]
    o = SR.ours_for("coupang_confirmed", lines, DEFAULT_RULES, today=TODAY,
                    fast_summary={"차감액": 300})
    assert o["금액"] == 700
    assert o["빠른정산차감"] == 300


def test_스스는_확정_미확정_둘_다_센다():
    lines = [_line(market="smartstore", date="2026-08-20", incl=100),
             _line(market="smartstore", date="2026-08-20", incl=50,
                   status="배송완료")]
    o = SR.ours_for("smartstore", lines, DEFAULT_RULES, today=TODAY)
    assert o["금액"] == 150


def test_로켓그로스는_회차를_안_가져왔으면_판정불가():
    """🔴 없는 걸 0원으로 두고 「일치」라 하면 안 된다 — 무엇을 하면 되는지 말한다."""
    o = SR.ours_for("coupang_rg", [], DEFAULT_RULES, today=TODAY, rg_summary={})
    assert o["가능"] is False
    assert "로켓그로스 가져오기" in o["왜"]


def test_로켓그로스는_최종지급액_한달창으로_맞춘다(monkeypatch):
    """🔴 [2026-08-13 정정] 예전엔 `지급액 − 빠른정산`(기간 무제한)이었다 —
    라이브 9,508,138 vs 쿠팡 화면 7,818,202 로 **1,689,936 어긋났다.**
    화면 정의는 **Σ최종지급액(정산일이 오늘 이후 ~ 한 달 이내)** 이고, 사장님 Wing
    25회차로 원 단위 확인했다(tests/margin/test_rg_ahead_summary.py 가 그 근거).
    """
    from lemouton.margin import rg_settlement as RG
    monkeypatch.setattr(RG, "ahead_summary",
                        lambda **kw: {"금액": 7818202, "회차수": 9,
                                      "이미받은회차합": 1226921,
                                      "구성": "최종지급액 합(정산일 …)"})
    o = SR.ours_for("coupang_rg", [], DEFAULT_RULES, today=TODAY,
                    rg_summary={"회차수": 25})
    assert o["가능"] is True and o["금액"] == 7818202 and o["건수"] == 9
    assert "빠른정산" not in o["구성"]        # 옛 규칙으로 되돌리면 깨진다


# ── 판정 ─────────────────────────────────────────────────────────────────────

def test_판정_정확히_같으면_일치():
    v = SR.judge(1000, {"가능": True, "금액": 1000}, rows=5)
    assert v["판정"] == "match" and v["차이"] == 0


def test_판정_반올림_범위는_허용차이():
    v = SR.judge(1000, {"가능": True, "금액": 950}, rows=10)   # 허용 ±100
    assert v["판정"] == "tol"


def test_판정_구조적_항목으로_설명되면_정의차이():
    """빠른정산 선인출·셀러월렛처럼 **구조적으로** 다른 항목은 「틀림」이 아니다."""
    v = SR.judge(1_000_000, {"가능": True, "금액": 700_000}, rows=10,
                 explains={"셀러월렛 미인출 잔액": 300_000})
    assert v["판정"] == "def"
    assert "셀러월렛" in v["왜"]


def test_판정_설명_안_되면_불일치():
    v = SR.judge(1_000_000, {"가능": True, "금액": 700_000}, rows=10,
                 explains={"셀러월렛 미인출 잔액": 10})
    assert v["판정"] == "diff"
    assert "기준일" in v["왜"]        # 무엇부터 확인할지 말해 준다


def test_판정_재료가_없으면_판정불가():
    v = SR.judge(1000, {"가능": False, "왜": "회차 없음"}, rows=1)
    assert v["판정"] == "unknown" and v["차이"] is None


def test_애매한_것을_일치로_뭉개지_않는다():
    """정답지 대조와 같은 규율 — 「거의 같다」는 일치가 아니다."""
    v = SR.judge(1_000_000, {"가능": True, "금액": 995_000}, rows=10)
    assert v["판정"] != "match"


# ── 전체 대조 ────────────────────────────────────────────────────────────────

def test_대조결과에_기준일_규칙이_그대로_실린다():
    """기준일을 잘못 뽑으면 대조 자체가 거짓이 된다 — 화면이 규칙을 보여줘야 한다."""
    b = _xlsx([{"정산일": "2026-08-20", "최종지급액": 100}])
    res = SR.reconcile("coupang_confirmed", SR.parse_sheet(b),
                       [_line(date="2026-08-20", incl=100)],
                       DEFAULT_RULES, today=TODAY)
    assert res["판정"] == "match"
    assert "정산일 2달" in res["기준일규칙"]
    assert res["마켓화면"].startswith("정산 > 정산현황")
    assert res["읽은열"] == "최종지급액"
    assert res["마켓기간"] == "2026-08-20 ~ 2026-08-20"


def test_노션_기준일_규칙_4항목이_전부_있다():
    assert set(SR.ITEMS) == {"coupang_rg", "coupang_confirmed",
                             "coupang_unconfirmed", "smartstore"}
    assert SR.ITEMS["coupang_rg"]["window_days"] == 60      # 매출인식일 2달
    assert SR.ITEMS["smartstore"]["window_days"] == 30      # 정산예정일 1달
    assert SR.ITEMS["coupang_rg"]["fast_excluded"] is True  # 빠른정산금 제외됨
    assert SR.ITEMS["coupang_unconfirmed"]["fast_excluded"] is False


# ══ [2026-08-12 실물 확인] 쿠팡 상세 엑셀은 주문번호를 준다 → 주문 단위 대조 ═══
#  총액만 맞고 안이 틀린 경우를 잡는다. 우리 정산액과 쿠팡 「정산금액」은 둘 다
#  지급비율 적용 **전** 금액이라 같은 종류다(그래서 바로 맞댈 수 있다).
#  🔴 [2026-08-13 정정] 우리 쪽 재료는 **N열(`정산예정금(배송비포함)`)** 이다 —
#    마켓 「정산금액」이 상품+배송비 합이라, M열(상품분만)과 맞대면 배송비가 붙은
#    주문이 전부 가짜 「차이」가 된다. 아래 배송비 케이스가 그 회귀를 잠근다.

def test_주문번호가_있으면_주문_단위로_맞댄다():
    b = _xlsx([{"주문번호": "A1", "정산금액": 1000, "정산예정일": "2026-08-24"},
               {"주문번호": "A2", "정산금액": 2000, "정산예정일": "2026-08-24"}])
    parsed = SR.parse_sheet(b)
    assert parsed["amount_col"] == "정산금액"
    assert parsed["is_base_amount"] is True      # 지급비율 적용 전 금액이다
    lines = [_line(incl=1000), _line(incl=1777)]
    lines[0]["row"]["오픈마켓주문번호"] = "A1"
    lines[1]["row"]["오픈마켓주문번호"] = "A2"
    r = SR.compare_orders(parsed, lines)
    assert r["가능"] and r["일치"] == 1 and r["차이"] == 1
    assert r["차이목록"][0]["주문번호"] == "A2"
    assert r["차이목록"][0]["차이"] == -223


def test_배송비_붙은_주문이_가짜_차이로_안_잡힌다():
    """마켓 정산금액 117,792 = 상품 113,924 + 배송료 3,868 (쿠팡 실측)."""
    b = _xlsx([{"주문번호": "A1", "정산금액": 117792}])
    ln = _line(incl=117792)
    ln["row"].update({"오픈마켓주문번호": "A1", "정산예정금액": 113924, "배송비": 4000})
    r = SR.compare_orders(SR.parse_sheet(b), [ln])
    assert r["일치"] == 1 and r["차이"] == 0


def test_마켓에만_있는_주문을_드러낸다():
    """우리가 아예 못 받아 온 주문 — 조용히 빠지면 「일치」로 보인다."""
    b = _xlsx([{"주문번호": "Z9", "정산금액": 500}])
    r = SR.compare_orders(SR.parse_sheet(b), [])
    assert r["마켓에만_수"] == 1 and r["일치"] == 0


def test_주문번호_열이_없으면_못한다고_말한다():
    b = _xlsx([{"정산금액": 500}])
    r = SR.compare_orders(SR.parse_sheet(b), [])
    assert r["가능"] is False and "주문번호" in r["왜"]
