# -*- coding: utf-8 -*-
"""데이터 코드 지도 `incidents` 전수정독(2026-08-06)에서 뒤늦게 발견한 함정 4건.

전부 **이미 지도에 적혀 있던 것**을 내가 안 읽어서 다시 밟을 뻔한 것들이다.
(consult-market-map 스킬이 ⑦과거이력·idTraps 를 건너뛰지 말라고 한 이유가 이것)

① [2026-07-21 esm-stock-zero-oversell-guard]
   ESM 재고 유효범위는 **1~99,999**. 0 은 규격상 무효라 마켓이 거부한다.
   품절은 재고 0 이 아니라 플래그(isSoldOutSite / isSell=false)로 표현한다.
   🔴 왕복에서 원래 재고가 0 이면 **원복이 400 으로 실패**한다 — 미리 막는다.

② [2026-07-21 esm-register-400-triple]
   ESM 은 **양쪽(Gmkt·Iac) price/stock 이 모두 유효값**이어야 한다.
   반대편에 0 을 넣는 조립으로 400 을 3번 맞았던 이력.

③ [2026-07-21 lotteon-register-spdlst-silent]
   롯데온은 래퍼가 틀리면 **0건 접수를 「정상 처리되었습니다」로 응답**한다(조용한 무시).
   → body 를 손으로 조립하지 말고 **검증된 기존 writer** 를 쓴다.

④ 같은 이력 — 성공 판정은 returnCode 가 아니라 **항목별 결과**로 한다.
"""
from __future__ import annotations

import copy

import pytest

from lemouton.uploader.roundtrip.markets.esm import make_esm_ops
from lemouton.uploader.roundtrip.markets.lotteon import make_lotteon_ops


# ── ① ESM 재고 유효범위 1~99,999 ─────────────────────────────────────────────
def _goods(stock=5, price=10000, market="auction"):
    col = "Iac" if market == "auction" else "Gmkt"
    other = "Gmkt" if market == "auction" else "Iac"
    site = "iac" if market == "auction" else "gmkt"
    return {
        "goodsNo": "G1", "isEditableGoodsName": True, "isSell": {site: False},
        "itemBasicInfo": {"goodsName": {"kor": "이름"}},
        "itemAddtionalInfo": {
            "price": {col: price, other: price},
            "stock": {col: stock, other: stock},
            "images": {"basicImgURL": "http://img/a.jpg"},
            "descriptions": {"kor": {"type": 2, "html": "<p>d</p>"}},
        },
    }


class FakeEsm:
    def __init__(self, goods=None):
        self.goods = goods or _goods()
        self.puts = []
        self._cfg = {"paths": {"detail": "/g/{goodsNo}", "update": "/g/{goodsNo}"}}

    def request(self, *, method, path, body=None, **kw):
        if method == "GET":
            return copy.deepcopy(self.goods)
        self.puts.append(copy.deepcopy(body))
        self.goods = copy.deepcopy(body)
        return {"goodsNo": "G1", "resultCode": 0}


def test_ESM_재고0은_보내기_전에_막는다():
    """0 은 규격상 무효(1~99,999) — 보내면 400. 품절은 플래그로 표현해야 한다."""
    cli = FakeEsm()

    with pytest.raises(ValueError, match="1~99,999|재고"):
        make_esm_ops("G1", market="auction", client=cli).apply({"stock": 0})

    assert cli.puts == [], "거부했는데 전송이 나갔다"


def test_ESM_재고_상한초과도_막는다():
    cli = FakeEsm()

    with pytest.raises(ValueError):
        make_esm_ops("G1", market="auction", client=cli).apply({"stock": 100000})


def test_ESM_원래재고가_0이면_재고축을_시험대상에서_뺀다():
    """원복할 값(0)이 규격상 무효라 왕복이 성립하지 않는다 — 확인불가로 남긴다."""
    ops = make_esm_ops("G1", market="auction", client=FakeEsm(_goods(stock=0)))

    s = ops.snapshot()

    assert "stock" in s.missing, "0 인 재고를 시험 대상으로 삼으면 원복이 400 난다"


# ── ② ESM 양쪽 price/stock 필수 ──────────────────────────────────────────────
def test_ESM_가격은_양쪽_사이트에_모두_유효값으로_나간다():
    """반대편이 0/누락이면 400(1~10억 범위) — 등록 400 3연발 이력."""
    cli = FakeEsm()

    make_esm_ops("G1", market="auction", client=cli).apply({"detail_html": "<p>x</p>"})

    # 가격은 이제 **전용 API** 로 나간다. 다만 무거운 축을 보낼 때 실리는 본문의
    # price 도 양쪽이 유효값이어야 400 을 안 맞는다.
    p = cli.puts[-1]["itemAddtionalInfo"]["price"]
    assert isinstance(p.get("Iac"), int) and p["Iac"] > 0
    assert isinstance(p.get("Gmkt"), int) and p["Gmkt"] > 0, \
        f"반대편이 유효값이 아니다: {p}"


def test_ESM_재고도_양쪽_모두_유효값이다():
    cli = FakeEsm()

    make_esm_ops("G1", market="auction", client=cli).apply({"detail_html": "<p>x</p>"})

    s = cli.puts[-1]["itemAddtionalInfo"]["stock"]
    assert 1 <= s.get("Iac", 0) <= 99999
    assert 1 <= s.get("Gmkt", 0) <= 99999, f"반대편이 유효범위 밖: {s}"


# ── ③④ 롯데온 — 검증된 기존 writer 를 쓴다 ──────────────────────────────────
class FakeLotteon:
    """롯데온처럼 래퍼가 틀리면 「정상」이라 답하면서 아무것도 안 바꾸는 마켓."""

    def __init__(self):
        self.detail = {"spdNo": "S1", "pdNm": "이름", "slStatCd": "STP",
                       "itmLst": [{"sitmNo": "I1", "slPrc": 10000,
                                   "stkQty": 5, "stkMgtYn": "Y"}]}
        self.bodies = []
        self._cfg = {"tr_grp_cd": "SR", "tr_no": "T1", "lrtr_no": "",
                     "paths": {"detail": "/detail",
                               "price_change": "/price", "stock_change": "/stock"}}

    def request(self, *, method, path, body=None, **kw):
        if path == "/detail":
            return {"returnCode": "0000", "data": copy.deepcopy(self.detail)}
        self.bodies.append((path, copy.deepcopy(body)))
        # 🔴 래퍼가 틀리면 0건 접수인데 "정상 처리되었습니다"
        if path == "/price" and "itmPrcLst" not in (body or {}):
            return {"returnCode": "0000", "message": "정상 처리되었습니다", "data": []}
        if path == "/stock" and "itmStkLst" not in (body or {}):
            return {"returnCode": "0000", "message": "정상 처리되었습니다", "data": []}
        if path == "/price":
            self.detail["itmLst"][0]["slPrc"] = body["itmPrcLst"][0]["slPrc"]
        else:
            self.detail["itmLst"][0]["stkQty"] = body["itmStkLst"][0]["stkQty"]
        return {"returnCode": "0000", "data": [{"resultCode": "0000", "sitmNo": "I1"}]}


def test_롯데온_가격은_itmPrcLst_래퍼로_나간다():
    """래퍼가 없으면 0건 접수를 「정상」이라 응답한다 — 조용한 무시(2026-07-21 이력)."""
    cli = FakeLotteon()

    make_lotteon_ops("S1", client=cli).apply({"sale_price": 11000})

    path, body = cli.bodies[-1]
    assert path == "/price"
    assert "itmPrcLst" in body, f"래퍼가 없다 — 0건 접수된다: {list(body)}"
    assert cli.detail["itmLst"][0]["slPrc"] == 11000


def test_롯데온_재고는_itmStkLst_래퍼로_나간다():
    cli = FakeLotteon()

    make_lotteon_ops("S1", client=cli).apply({"stock": 7})

    path, body = cli.bodies[-1]
    assert path == "/stock"
    assert "itmStkLst" in body, f"래퍼가 없다: {list(body)}"
    assert cli.detail["itmLst"][0]["stkQty"] == 7


def test_롯데온_0건_접수를_성공으로_보지_않는다():
    """returnCode 0000 + 「정상 처리되었습니다」인데 data[] 가 비면 실패다."""
    cli = FakeLotteon()

    def silent(*, method, path, body=None, **kw):
        if path == "/detail":
            return {"returnCode": "0000", "data": copy.deepcopy(cli.detail)}
        return {"returnCode": "0000", "message": "정상 처리되었습니다", "data": []}

    cli.request = silent

    with pytest.raises(RuntimeError):
        make_lotteon_ops("S1", client=cli).apply({"sale_price": 11000})
