# -*- coding: utf-8 -*-
"""쿠팡 5축 왕복 어댑터.

지도 근거:
  · 조회   GET  .../seller-products/{sellerProductId}          (get_product)
  · 가격   PUT  .../vendor-items/{vendorItemId}/prices/{price}  — **즉시**
  · 재고   PUT  .../vendor-items/{vendorItemId}/quantities/{q}  — **즉시**
  · 재고조회 GET .../vendor-items/{vendorItemId}/inventories     (상품상세엔 재고가 없다)
  · 3축    PUT  .../seller-products (전체 JSON 재전송)
           지도 원문: 「이 API를 사용하면 **승인 후에 반영**됩니다」

🔴 그래서 쿠팡은 두 갈래다. 가격·재고는 즉시 되읽기로 확인되지만,
   상품명·상세·이미지는 **보낸 직후 되읽으면 옛 값**일 수 있다(승인 대기).
   그걸 「안 바뀜=실패」로 적으면 거짓 보고다 — 「승인 대기」로 구분해 적는다.
"""
from __future__ import annotations

import copy

import pytest

from lemouton.uploader.roundtrip.markets.coupang import (
    APPROVAL_AXES, make_coupang_ops,
)


def _detail(*, name="원래이름", price=10000, stock=5, status="판매중지",
            html="<p>원래</p>", images=("http://img/a.jpg", "http://img/b.jpg")):
    return {
        "sellerProductId": 111,
        "sellerProductName": name,
        "statusName": status,
        "displayCategoryCode": 1001,
        "vendorId": "A0001",
        "items": [{
            "sellerProductItemId": 9001,
            "vendorItemId": 77001,
            "itemName": "옵션A",
            "salePrice": price,
            "maximumBuyCount": stock,
            "images": [{"imageOrder": i, "imageType": "REPRESENTATION" if i == 0 else "DETAIL",
                        "cdnPath": u, "vendorPath": u}
                       for i, u in enumerate(images)],
            "contents": [{"contentsType": "TEXT",
                          "contentDetails": [{"content": html, "detailType": "TEXT"}]}],
        }],
    }


class FakeCoupangClient:
    """가격·재고는 즉시 반영, 3축은 「승인 대기」라 조회에 안 나타나는 마켓."""

    def __init__(self, detail=None, *, approval_pending=True):
        self.detail = detail or _detail()
        self.approval_pending = approval_pending
        self.calls = []
        self.pending_body = None
        self.inventory = {77001: self.detail["items"][0]["maximumBuyCount"]}

    def request(self, *, method, path, body=None, **kw):
        self.calls.append((method, path))
        if method == "GET" and "/inventories" in path:
            vid = int(path.split("/vendor-items/")[1].split("/")[0])
            return {"data": {"amountInStock": self.inventory.get(vid)}}
        if method == "GET":
            return {"data": copy.deepcopy(self.detail)}
        if method == "PUT" and "/prices/" in path:
            self.detail["items"][0]["salePrice"] = int(path.rsplit("/", 1)[1])
            return {"code": "SUCCESS"}
        if method == "PUT" and "/quantities/" in path:
            q = int(path.rsplit("/", 1)[1])
            self.detail["items"][0]["maximumBuyCount"] = q
            self.inventory[77001] = q
            return {"code": "SUCCESS"}
        if method == "PUT":                      # seller-products 전체 수정
            self.pending_body = copy.deepcopy(body)
            if not self.approval_pending:        # 승인 없이 바로 반영되는 계정도 있을 수 있다
                self.detail = copy.deepcopy(body)
            return {"code": "SUCCESS", "data": 111}
        raise AssertionError(f"{method} {path}")


def _ops(cli):
    return make_coupang_ops(111, client=cli)


# ── 되읽기 ───────────────────────────────────────────────────────────────────
def test_되읽기가_다섯_축을_모두_준다():
    s = _ops(FakeCoupangClient()).snapshot()

    assert s.name == "원래이름"
    assert s.sale_price == 10000
    assert s.detail_html == "<p>원래</p>"
    assert s.image_urls == ("http://img/a.jpg", "http://img/b.jpg")
    assert s.value_of("stock") == 5
    assert s.missing == ()


def test_재고는_상품상세가_아니라_재고조회로_읽는다():
    """과거이력(2026-07-17): 쿠팡 옵션 재고는 상품상세에 없다 — vendor-items inventories."""
    cli = FakeCoupangClient()
    cli.inventory[77001] = 42

    s = _ops(cli).snapshot()

    assert s.value_of("stock") == 42
    assert any("/inventories" in p for _, p in cli.calls)


def test_재고조회가_실패하면_0으로_채우지_않는다():
    cli = FakeCoupangClient()
    cli.inventory[77001] = None

    s = _ops(cli).snapshot()

    assert s.value_of("stock") is None
    assert "stock" in s.missing


def test_판매중이면_판매중으로_알린다():
    """🔴 쿠팡 statusName 은 「판매중/판매중지」가 아니다 — 실제 값으로 시험한다.
    승인완료=판매중 · 부분승인완료·승인반려·상품삭제=판매중지 (catalog/status.py 실측표)."""
    assert _ops(FakeCoupangClient(_detail(status="승인완료"))).on_sale() is True
    assert _ops(FakeCoupangClient(_detail(status="부분승인완료"))).on_sale() is False
    assert _ops(FakeCoupangClient(_detail(status="승인반려"))).on_sale() is False


def test_심사중_상품은_건드리지_않는다():
    """대기 상품을 건드리면 심사 흐름이 꼬인다 — 판매중지가 아니므로 거부."""
    assert _ops(FakeCoupangClient(_detail(status="심사중"))).on_sale() is True
    assert _ops(FakeCoupangClient(_detail(status="임시저장"))).on_sale() is True


def test_모르는_상태는_건드리지_않는다():
    assert _ops(FakeCoupangClient(_detail(status="처음보는상태"))).on_sale() is True


# ── 쓰기 ─────────────────────────────────────────────────────────────────────
def test_가격과_재고는_전용_경로로_즉시_보낸다():
    """전체 JSON 재전송으로 가격을 바꾸면 승인 대기에 걸린다 — 전용 경로가 즉시다."""
    cli = FakeCoupangClient()

    _ops(cli).apply({"sale_price": 11000, "stock": 7})

    assert any("/prices/11000" in p for _, p in cli.calls)
    assert any("/quantities/7" in p for _, p in cli.calls)
    assert cli.pending_body is None, "가격·재고에 전체 수정 API 를 쓰면 안 된다"
    assert _ops(cli).snapshot().sale_price == 11000


def test_상품명_상세_이미지는_전체수정_한_번으로_보낸다():
    cli = FakeCoupangClient()

    _ops(cli).apply({"name": "새이름", "detail_html": "<p>새</p>",
                     "image_urls": ("http://img/x.jpg",)})

    b = cli.pending_body
    assert b is not None
    assert b["sellerProductName"] == "새이름"
    assert b["items"][0]["contents"][0]["contentDetails"][0]["content"] == "<p>새</p>"
    assert [im["cdnPath"] for im in b["items"][0]["images"]] == ["http://img/x.jpg"]
    puts = [p for m, p in cli.calls if m == "PUT" and "/vendor-items/" not in p]
    assert len(puts) == 1, "축마다 따로 전체수정하면 승인 큐가 여러 번 돈다"


def test_자동승인요청은_켜지_않는다():
    """requested=true 면 판매 승인까지 요청한다 — 시험이 상품을 팔리게 만들면 안 된다."""
    cli = FakeCoupangClient()

    _ops(cli).apply({"name": "새이름"})

    assert cli.pending_body.get("requested") is False


# ── 🔴 승인 대기 구분 ────────────────────────────────────────────────────────
def test_승인이_필요한_축이_무엇인지_선언한다():
    """runner 가 「안 바뀜=실패」와 「승인 대기」를 가르려면 목록이 필요하다."""
    assert set(APPROVAL_AXES) == {"name", "detail_html", "image_urls"}
    assert "sale_price" not in APPROVAL_AXES
    assert "stock" not in APPROVAL_AXES


# ── 🔴 승인반려 상품 — 가격·재고가 에러 없이 안 먹는다 ──────────────────────
def test_승인반려_상품은_가격_재고를_확인불가로_남긴다():
    """🔴 [2026-08-06 라이브] 승인반려 상품에 가격을 보내면 **에러 없이 200** 인데
    되읽으면 옛 값 그대로다(조용한 무시 — 가장 위험한 부류).

    원인 추정: 승인이 안 난 상품은 vendorItemId 가 활성이 아니다.
    확인 전까지는 「보냈는데 안 바뀜=실패」로 적지 않고 **확인불가**로 남긴다 —
    배선이 멀쩡한데 실패로 보고하면 멀쩡한 코드를 뜯게 된다.
    """
    s = _ops(FakeCoupangClient(_detail(status="승인반려"))).snapshot()

    assert "sale_price" in s.missing
    assert "stock" in s.missing


def test_부분승인완료_상품은_가격_재고를_시험한다():
    """승인이 난 적 있는 상품은 가격 API 가 먹는다 — 시험 대상으로 남긴다."""
    s = _ops(FakeCoupangClient(_detail(status="부분승인완료"))).snapshot()

    assert "sale_price" not in s.missing
