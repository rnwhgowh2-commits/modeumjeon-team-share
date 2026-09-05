# -*- coding: utf-8 -*-
"""반품·교환 걸린 주문은 「받을 돈」에서 빼고, **반품비만** 남긴다 (사장님 확정 2026-08-13).

> *"반품진행중과 반품 완료건은 금액에서 제외해줘야지. 다만 반품비정도 추가해야지."*

🔴 왜 지금까지 안 빠졌나 — 클레임은 **별도 행**(`_kind='change'`)으로 저장되고,
   원래 주문 행의 `주문상태` 는 **배송완료인 채 그대로 남는다**. `classify` 는 그 원래 행의
   상태만 보므로 반품완료여도 「받을 돈」에 살아 있었다.
   라이브 실측(2026-08-13): 쿠팡 미수령 22,487,606원 중 **반품 걸린 51주문 3,864,383원**.
   두 행은 서로를 모른다 — **주문번호로 이어 줘야** 원래 행이 반품을 안다.

🔴 반품비는 「더하기」가 아니라 **마켓이 준 부호 그대로**다.
   라이브 전건 확인: 쿠팡은 배송비 정산이 **받는 게 4건 · 내는(음수) 게 15건**이다.
   무조건 더하면 15건에서 반대로 틀린다. 11번가는 양수로 온다(clmReqSeq 라인).

🔴 실값이 없으면 **아무것도 안 더한다** — 반품비를 지어내면 없는 돈이 총액에 선다.
"""
import datetime as dt

import pytest

from lemouton.margin import settle_plan as SP

TODAY = dt.date(2026, 8, 13)
RULES = {"markets": {"coupang": {"cycle_days": 7, "auto_confirm_days": 7,
                                 "transit_days": 0, "split_ratio": 1.0}}}


def _line(no, status, amount, *, kind=None, ship=None, paid=None,
          plan="2026-08-20", market="coupang"):
    row = {"오픈마켓주문번호": no, "주문상태": status,
           "정산예정금(배송비포함)": amount, "정산예정금액": amount,
           "_settle_source": "real", "정산예정일": plan}
    if kind:
        row["_kind"] = kind
    if ship is not None:
        row["_ship_settle"] = ship
    if paid:
        row["_settle_paid_date"] = paid
    return {"row": row, "market": market, "account": "브랜드마켓", "status_at": None}


def _agg(lines):
    SP.annotate_claims(lines)
    return SP.aggregate_payout(lines, RULES, unit="week", today=TODAY)


# ── ① 클레임 행이 원 주문행에 표식을 남긴다 ─────────────────────────────────

def test_클레임_행이_원_주문행에_표식을_남긴다():
    lines = [_line("A1", "배송완료", 100000),
             _line("A1", "반품완료", 0, kind="change")]
    SP.annotate_claims(lines)
    assert lines[0]["row"]["_claim"] == "done"


def test_진행중과_완료를_가른다():
    """받을지 모르는 것(진행중)과 확정적으로 줄어든 것(완료)은 다르다."""
    lines = [_line("B1", "배송완료", 100000),
             _line("B1", "반품요청", 0, kind="change"),
             _line("C1", "배송완료", 100000),
             _line("C1", "반품완료", 0, kind="change")]
    SP.annotate_claims(lines)
    assert lines[0]["row"]["_claim"] == "open"
    assert lines[2]["row"]["_claim"] == "done"


def test_클레임_없는_주문엔_표식이_안_붙는다():
    lines = [_line("D1", "배송완료", 100000)]
    SP.annotate_claims(lines)
    assert "_claim" not in lines[0]["row"]


def test_한_주문에_요청과_완료가_둘_다면_완료가_이긴다():
    """라이브에 56주문이 이 모양이다 — 요청 뒤에 완료가 오므로 완료가 최신이다."""
    lines = [_line("E1", "배송완료", 100000),
             _line("E1", "반품요청", 0, kind="change"),
             _line("E1", "반품완료", 0, kind="change")]
    SP.annotate_claims(lines)
    assert lines[0]["row"]["_claim"] == "done"


# ── ② 받을 돈에서 빠진다 ─────────────────────────────────────────────────────

def test_반품_진행중은_받을_돈에서_빠지고_별도_줄에_선다():
    a = _agg([_line("F1", "배송완료", 100000),
              _line("F1", "반품요청", 0, kind="change")])
    assert a["kpi"]["total_uncollected"] == 0
    assert a["kpi"]["risk"] == 100000


def test_반품_완료도_받을_돈에서_빠진다():
    """🔴 이게 라이브에서 새던 3,864,383원이다."""
    a = _agg([_line("G1", "배송완료", 100000),
              _line("G1", "반품완료", 0, kind="change")])
    assert a["kpi"]["total_uncollected"] == 0
    assert a["kpi"]["returned"] == 100000


def test_고치기_전이라면_그대로_남았을_것이다():
    """표식이 없으면(=옛 동작) 그대로 받을 돈에 선다 — 이 시험이 무엇을 막는지 보인다."""
    a = _agg([_line("H1", "배송완료", 100000)])
    assert a["kpi"]["total_uncollected"] == 100000


# ── ③ 반품비만 남는다 ───────────────────────────────────────────────────────

def test_반품비_실값이_있으면_받을_돈에_더해진다():
    a = _agg([_line("I1", "배송완료", 100000, ship=7736),
              _line("I1", "반품완료", 0, kind="change")])
    assert a["kpi"]["total_uncollected"] == 7736, "반품비는 우리가 받는 돈이다"
    assert a["kpi"]["returned"] == 100000


def test_반품비가_음수면_음수_그대로_싣는다():
    """🔴 쿠팡은 내는 쪽이 더 많다(받는 4건 vs 내는 15건). 무조건 더하면 반대로 틀린다."""
    a = _agg([_line("J1", "배송완료", 100000, ship=-9670),
              _line("J1", "반품완료", 0, kind="change")])
    assert a["kpi"]["total_uncollected"] == -9670


def test_반품비_실값이_없으면_아무것도_안_더한다():
    """지어내면 없는 돈이 총액에 선다."""
    a = _agg([_line("K1", "배송완료", 100000),
              _line("K1", "반품완료", 0, kind="change")])
    assert a["kpi"]["total_uncollected"] == 0


def test_반품_아닌_주문의_배송비는_건드리지_않는다():
    """멀쩡한 주문은 예전 그대로 정산액 전체가 선다."""
    a = _agg([_line("L1", "배송완료", 100000, ship=3868)])
    assert a["kpi"]["total_uncollected"] == 100000


# ── ④ 이미 받은 것은 안 건드린다 ────────────────────────────────────────────

def test_이미_받은_주문은_반품이_걸려도_받음_그대로다():
    """받을 돈이 아니라 이미 지나간 돈이다 — 여기서 옮기면 이력이 흔들린다."""
    a = _agg([_line("M1", "배송완료", 100000, paid="2026-08-01"),
              _line("M1", "반품완료", 0, kind="change")])
    assert a["kpi"]["paid"] == 100000
    assert a["kpi"]["returned"] == 0


# ── ⑤ 드릴다운도 같은 판정을 쓴다 ───────────────────────────────────────────

def test_드릴다운_부류가_집계와_같다():
    """🔴 예전에 「KPI 5.5억 · 목록 0건」이 라이브에 나갔다 — 판정은 한 곳에서만."""
    lines = [_line("N1", "배송완료", 100000, ship=7736),
             _line("N1", "반품완료", 0, kind="change")]
    SP.annotate_claims(lines)
    r = SP.resolve(lines[0], RULES, today=TODAY)
    assert r["category"] == "returned"
    assert [e["amount"] for e in r["events"]] == [7736]


def test_새_부류가_화면_목록에_들어_있다():
    """부류 이름을 화면이 모르면 눌러도 목록이 안 뜬다."""
    import webapp.routes.orders as om
    assert "returned" in om._SP_CATEGORIES
    assert om._SP_CAT_KO["returned"]


def test_화면에_반품교환완료_카드가_있다():
    """부류를 만들어도 화면에 자리가 없으면 사장님은 영영 못 본다."""
    import pathlib
    tpl = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "templates"
           / "orders" / "index.html").read_text(encoding="utf-8")
    assert "spn-returned-card" in tpl
    assert "k.returned" in tpl                     # 숫자를 실제로 그린다
    assert "'returned','↩ 반품·교환 완료" in tpl   # 눌렀을 때 목록이 뜬다
    assert "반품비는 남겨 뒀어요" in tpl            # 왜 총액이 안 줄었는지 말해 준다


def test_줄_만드는_곳이_클레임을_이어_준다():
    """🔴 집계·드릴다운·엑셀이 전부 이 함수를 지난다 — 여기서 빠지면 셋이 갈린다.

    [2026-09-05] 실제 조회는 `order_store.lines_for_markets` 로 옮겼다(마진계산기도
    같은 판정을 쓰게 하려고 — 단일 진실 원천). `_settle_plan_lines` 는 그리로
    위임만 하므로, 여기서는 **위임 여부**와 **위임 대상이 실제로 이어 붙이는지**를
    각각 확인한다(둘 중 하나만 보면 이관 중 조용히 끊겨도 통과한다)."""
    import pathlib
    import webapp.routes.orders as om
    from lemouton.markets import order_store as OS

    src = pathlib.Path(om.__file__).read_text(encoding="utf-8")
    i = src.index("def _settle_plan_lines")
    blk = src[i:i + 800]
    assert "lines_for_markets" in blk, "_settle_plan_lines 가 order_store.lines_for_markets 를 안 부른다"

    store_src = pathlib.Path(OS.__file__).read_text(encoding="utf-8")
    j = store_src.index("def lines_for_markets")
    k = store_src.index("\ndef ", j + 1)   # 다음 함수 시작까지 — 길이에 안 흔들리게
    store_blk = store_src[j:k]
    assert "annotate_claims" in store_blk


def test_반품교환완료_칸을_누르면_목록이_뜬다(monkeypatch):
    """🔴 내 앞 커밋의 결함 — 눌러도 **영영 0건**이었다.

    드릴다운은 `bucket == category` 로 거른다. 그런데 반품비 이벤트의 bucket 은
    confirmed/overdue/undated 라서 `bucket == 'returned'` 인 이벤트가 **하나도 없다**.
    `returned` 는 이벤트 표식이 아니라 **부류**다 — risk·paid 와 같은 자리에서 걸러야 한다.
    (이 저장소가 예전에 겪은 「KPI 는 5.5억인데 목록은 0건」과 같은 부류의 사고다.)
    """
    import pathlib
    import webapp.routes.orders as om
    src = pathlib.Path(om.__file__).read_text(encoding="utf-8")
    # 🔴 **두 곳** 다 본다 — 화면 목록과 엑셀 내보내기가 같은 줄을 따로 갖고 있다.
    #   한 곳만 고치면 「화면엔 뜨는데 엑셀엔 없다」가 된다.
    for fn in ("def settle_plan_detail", "def settle_plan_export"):
        i = src.index(fn)
        blk = src[i:i + 4500]
        assert 'category in ("risk", "returned", "paid")' in blk, (
            f"{fn} 에서 returned 가 부류 자리에서 안 걸러진다 — 목록이 영영 비어 있다")
