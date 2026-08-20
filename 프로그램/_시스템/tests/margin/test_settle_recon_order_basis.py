# -*- coding: utf-8 -*-
"""주문 단위 대조가 **같은 종류의 숫자**를 맞대는가.

🔴 2026-08-13 발견 — `compare_orders` 는 우리 쪽 재료로 `정산예정금액`(M열 = **상품
   정산만**)을 쓰는데, 마켓 정산 명세의 「정산금액」은 **상품 + 배송비** 합이다.
   그래서 배송비가 붙은 주문은 **전부** 「차이」로 잡혔다 — 우리가 틀린 게 아니라
   비교 대상이 달랐던 것.  (인수인계 문서가 총액 대조에서 짚은 바로 그 함정이
   주문 단위 대조 코드 안에 그대로 남아 있었다.)

   실측(쿠팡 엑셀 153주문): 배송비 있는 주문이 124건 — 그 전부가 가짜 「차이」가 된다.
"""
import pytest

from lemouton.margin import settle_recon as SR


def _parsed(rows):
    return {"order_col": "주문번호", "rows": rows}


def _line(no, m, incl, **extra):
    row = {"오픈마켓주문번호": no, "정산예정금액": m,
           "정산예정금(배송비포함)": incl, "배송비": 4000}
    row.update(extra)
    return {"row": row, "market": "coupang", "account": "A"}


def test_배송비_있는_주문이_가짜_차이로_안_잡힌다():
    """마켓 정산금액 117,792 = 상품 113,924 + 배송비 3,868. 우리 N열이 그 값이다."""
    parsed = _parsed([{"주문번호": "OID1", "금액": 117792}])
    lines = [_line("OID1", m=113924, incl=117792)]
    res = SR.compare_orders(parsed, lines)
    assert res["가능"] is True
    assert res["일치"] == 1, res.get("차이목록")
    assert res["차이"] == 0


def test_진짜_차이는_여전히_잡는다():
    """비교 기준을 바꿨다고 감시 기능이 무뎌지면 안 된다."""
    parsed = _parsed([{"주문번호": "OID1", "금액": 117792}])
    lines = [_line("OID1", m=100000, incl=103868)]
    res = SR.compare_orders(parsed, lines)
    assert res["차이"] == 1
    assert res["차이목록"][0]["차이"] == 103868 - 117792


def test_무료배송은_예전과_같다():
    parsed = _parsed([{"주문번호": "OID1", "금액": 52185}])
    lines = [_line("OID1", m=52185, incl=52185, 배송비=0)]
    assert SR.compare_orders(parsed, lines)["일치"] == 1


def test_N열이_비면_M열로_떨어진다():
    """저장분엔 N열이 빈 행이 있다 — 그때 0 으로 보면 전액이 차이로 둔갑한다."""
    parsed = _parsed([{"주문번호": "OID1", "금액": 52185}])
    lines = [_line("OID1", m=52185, incl="", 배송비=0)]
    assert SR.compare_orders(parsed, lines)["일치"] == 1


def test_클레임_줄은_안_센다():
    """이력(change) 줄을 같이 더하면 한 주문이 두 번 세어진다."""
    parsed = _parsed([{"주문번호": "OID1", "금액": 117792}])
    lines = [_line("OID1", m=113924, incl=117792),
             _line("OID1", m=113924, incl=117792, _kind="change")]
    assert SR.compare_orders(parsed, lines)["일치"] == 1
