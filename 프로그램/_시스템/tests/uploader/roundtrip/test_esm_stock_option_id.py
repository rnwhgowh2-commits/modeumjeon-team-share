# -*- coding: utf-8 -*-
"""ESM 재고 — **가짜 옵션 식별자**로 보내 재고가 통째로 실패하던 것.

[2026-08-08 라이브] 옥션 6495431339 왕복: 가격은 전용 API 로 잘 나갔는데
재고에서 `RuntimeError: ESM 재고 수정 실패`. 원인은 마켓이 아니라 **우리 쪽**이었다.

  · 재고 전용 API(esm.26)는 `GET recommended-options` 가 주는 **optSeq** 를 요구한다.
  · 그런데 우리 snapshot 은 상품 상세(esm.20 GET)만 읽고 옵션 식별자를 `"__base__"`
    라는 **우리가 지어낸 이름**으로 넣고 있었다 → 대상 옵션을 못 찾아 False.

바로잡는 규칙 두 가지:
  ① 옵션이 있는 상품 → 옵션 API 가 준 **진짜 optSeq** 로 그 옵션만 보낸다.
  ② 옵션이 없는 본품 상품 → 옵션 API 를 쓰면 안 되고 **본품 재고 API**
     (`update_base_stock`, PUT /item/v1/goods/{goodsNo}/stock)로 보낸다.
     문서 명시: 옵션 사용 상품은 본품 재고가 무시되고, 본품 상품은 옵션 API 대상이 아니다.
"""
from __future__ import annotations

import copy

import pytest

from lemouton.uploader.roundtrip.markets.esm import make_esm_ops


def _goods(stock=10, price=54600):
    return {
        "goodsNo": "G1", "isEditableGoodsName": True, "isSell": {"iac": True},
        "itemBasicInfo": {"goodsName": {"kor": "이름"}},
        "itemAddtionalInfo": {
            "price": {"Iac": price, "Gmkt": price},
            "stock": {"Iac": stock, "Gmkt": stock},
            "images": {"basicImgURL": "http://img/a.jpg"},
            "descriptions": {"kor": {"type": 2, "html": "<p>d</p>"}},
        },
    }


class FakeEsm:
    """상세 GET + 옵션 GET 을 모두 흉내낸다."""

    def __init__(self, *, options=True):
        self.goods = _goods()
        self.options_envelope = {
            "type": "RECOMMEND", "isStockManage": True,
            "independent": {"details": [
                {"optSeq": 77, "qty": {"Iac": 10, "Gmkt": 10}},
                {"optSeq": 78, "qty": {"Iac": 3, "Gmkt": 3}},
            ]},
        } if options else {"type": "NONE", "independent": {"details": []}}
        self._cfg = {"paths": {"detail": "/g/{goodsNo}", "update": "/g/{goodsNo}",
                               "options": "/g/{goodsNo}/opt",
                               "stock_change": "/g/{goodsNo}/stock"}}

    def request(self, *, method, path, body=None, **kw):
        if method == "GET":
            return copy.deepcopy(
                self.options_envelope if path.endswith("/opt") else self.goods)
        return {"resultCode": 0}


# ── ① 옵션 있는 상품 ─────────────────────────────────────────────────────────
def test_옵션_식별자를_지어내지_않고_optSeq_를_쓴다():
    """`__base__` 같은 우리 이름을 보내면 마켓이 대상 옵션을 못 찾아 통째로 실패한다."""
    ops = make_esm_ops("G1", market="auction", client=FakeEsm())

    s = ops.snapshot()

    assert s.options, "옵션 식별자가 비어 있다"
    assert str(s.options[0][0]) == "77", f"진짜 optSeq 가 아니다: {s.options[0][0]}"


def test_재고는_그_optSeq_로_옵션API_에_나간다():
    cli = FakeEsm()
    seen = []
    ops = make_esm_ops("G1", market="auction", client=cli)

    ops.apply({"stock": 11},
              _stock_fn=lambda gn, mk, oid, v, client=None: seen.append((gn, oid, v)) or True)

    assert seen == [("G1", "77", 11)], f"보낸 값: {seen}"


# ── ② 옵션 없는 본품 상품 ───────────────────────────────────────────────────
def test_본품만_있는_상품은_본품_재고API_로_보낸다():
    """옵션 API 는 본품 상품 대상이 아니다 — 보내면 대상 옵션 없음으로 실패한다."""
    cli = FakeEsm(options=False)
    opt_calls, base_calls = [], []
    ops = make_esm_ops("G1", market="auction", client=cli)

    ops.apply({"stock": 11},
              _stock_fn=lambda gn, mk, oid, v, client=None: opt_calls.append(oid) or True,
              _base_stock_fn=lambda gn, mk, v, client=None: base_calls.append(v) or True)

    assert base_calls == [11], f"본품 재고 API 로 안 갔다: base={base_calls} opt={opt_calls}"
    assert opt_calls == [], f"본품 상품인데 옵션 API 를 불렀다: {opt_calls}"


def test_재고전송_실패는_이유를_숨기지_않는다():
    """False 만 보고 「실패」라고만 적으면 무엇이 문제인지 영영 모른다."""
    ops = make_esm_ops("G1", market="auction", client=FakeEsm())

    with pytest.raises(RuntimeError, match="77|옵션"):
        ops.apply({"stock": 11}, _stock_fn=lambda *a, **k: False)
