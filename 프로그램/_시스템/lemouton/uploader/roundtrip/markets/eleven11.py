# -*- coding: utf-8 -*-
"""11번가 왕복 어댑터 — 가격·재고.

사장님 지적(2026-08-07): 「11번가도 가능하다」 — 확인해 보니 **이미 우리 코드에
다 있었다**. 어댑터만 없어서 「문서 미확보」로 오판하고 있었다.

  · 가격 쓰기  `GET /rest/prodservices/product/price/{prdNo}/{selPrc}`
               `eleven11/prices.update_price`
  · 재고 쓰기  `PUT /rest/prodservices/stockqty/{prdStckNo}`
               `eleven11/inventory.update_stock_by_stock_no`
  · 되읽기     `POST /rest/prodmarketservice/prodmarket/stocks`  (지도 st=ok)
               `eleven11/stocks_query.get_stocks`

🔴 `inventory.update_stock` 은 **일부러 NotImplementedError** 를 낸다 —
   옵션 전체교체 API 라 한 옵션만 보내면 **형제 옵션이 지워진다**. 절대 쓰지 않는다.
   재고는 반드시 **재고번호(prdStckNo) 단위**로 한 옵션만 보낸다.

상품명·상세·이미지: 11번가 상품수정 API 스펙 미확보 → **확인불가**로 남긴다.
  (문서가 로그인 뒤 POST 폼으로만 열려 못 받았다 — incidents 에 시도한 경로 기록)
"""
from __future__ import annotations

from dataclasses import dataclass

from lemouton.uploader.roundtrip.snapshot import Snapshot

#: 스펙 미확보라 되돌려 쓸 수 없는 축 — 읽히더라도 시험 대상에서 뺀다.
_UNWRITABLE = ("name", "detail_html", "image_urls")


@dataclass
class Eleven11Ops:
    product_id: str
    client: object
    _get_stocks: object = None
    _get_price: object = None
    _update_price: object = None
    _update_stock: object = None

    # ── 되읽기 ──────────────────────────────────────────────────────────────
    def _stocks(self):
        fn = self._get_stocks
        if fn is None:
            from shared.platforms.eleven11.stocks_query import get_stocks as fn
        try:
            return list(fn(str(self.product_id), client=self.client) or [])
        except Exception:  # noqa: BLE001 — 못 읽으면 확인불가(0 으로 채우지 않는다)
            return []

    def _price(self):
        fn = self._get_price
        if fn is None:
            from shared.platforms.eleven11.prices import get_product_price as fn
        try:
            return fn(str(self.product_id), client=self.client)
        except Exception:  # noqa: BLE001
            return None

    def snapshot(self) -> Snapshot:
        rows = self._stocks()
        price = self._price()

        first = rows[0] if rows else {}
        stock = first.get("stock")
        # 재고번호(prdStckNo)를 옵션 식별자로 쓴다 — 이게 있어야 한 옵션만 보낼 수 있다.
        stock_no = first.get("seller_stock_cd") or first.get("opt_no")
        options = ((str(stock_no), stock, None),) if (rows and stock_no) else ()

        missing = tuple(_UNWRITABLE)
        if price is None:
            missing = missing + ("sale_price",)
        if stock is None or not options:
            missing = missing + ("stock",)

        return Snapshot(market="eleven11", product_id=str(self.product_id),
                        name=None, detail_html=None, image_urls=None,
                        sale_price=price, options=options, missing=missing,
                        raw={"stocks": rows, "price": price})

    def on_sale(self) -> bool:
        """11번가 목록 조회가 상태를 주지만 상세엔 없다 — 모르면 판매중으로 본다(안전 쪽)."""
        rows = self._stocks()
        if not rows:
            return True
        from lemouton.uploader.roundtrip.sale_status import is_stopped
        return not is_stopped("eleven11", (rows[0] or {}).get("stat"))

    # ── 쓰기 ────────────────────────────────────────────────────────────────
    def apply(self, changes: dict) -> None:
        blocked = [a for a in _UNWRITABLE if a in changes]
        if blocked:
            raise RuntimeError(
                f"11번가는 {blocked} 축의 수정 API 스펙이 미확보입니다 — "
                f"되읽지 못하는 값을 보내면 원복됐는지 확인할 수 없어 보내지 않습니다.")

        if "sale_price" in changes:
            from shared.platforms.price_guard import assert_live_sale_price
            assert_live_sale_price(changes["sale_price"],
                                   context=f"eleven11 roundtrip prd={self.product_id}")
            fn = self._update_price
            if fn is None:
                from shared.platforms.eleven11.prices import update_price as fn
            r = fn(str(self.product_id), int(changes["sale_price"]), client=self.client)
            if not getattr(r, "success", True):
                raise RuntimeError(f"11번가 가격수정 실패: {getattr(r, 'error_message', '')}")

        if "stock" in changes:
            snap = self.snapshot()
            if not snap.options:
                raise RuntimeError("11번가 재고번호(prdStckNo)를 못 찾아 재고를 보낼 수 없습니다.")
            stock_no = str(snap.options[0][0])
            fn = self._update_stock
            if fn is None:
                # 🔴 update_stock(전체교체) 이 아니라 **재고번호 단위** 함수를 쓴다.
                from shared.platforms.eleven11.inventory import (
                    update_stock_by_stock_no as fn,
                )
            r = fn(str(self.product_id), stock_no, int(changes["stock"]),
                   client=self.client)
            if not getattr(r, "success", True):
                raise RuntimeError(f"11번가 재고수정 실패: {getattr(r, 'error_message', '')}")


def make_eleven11_ops(product_id, *, client, **inject) -> Eleven11Ops:
    return Eleven11Ops(product_id=str(product_id), client=client, **inject)
