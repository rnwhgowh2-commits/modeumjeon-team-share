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

#: 전용 수정 API 가 없어 되돌려 쓸 수 없는 축 — 읽히더라도 시험 대상에서 뺀다.
#: 🔴 상품명·이미지는 상품수정(PUT /product/{prdNo}) 뿐인데 문서 원문이
#:    「기존 데이터는 사라지고 수정되는 정보로 교체됩니다」 — **전체 교체**다.
#:    필수 30여 개를 하나도 안 틀리고 되돌려 보내야 해서 위험 대비 실익이 없다.
#: 🎯 상세는 전용 API 가 따로 있어 여기서 뺐다(eleven11.903/904).
_UNWRITABLE = ("name", "image_urls")

#: ⚠️ [2026-08-12 오보 정정] 예전에 여기 `STOCK_BOUNDS = (0, 9999)` 가 있었다.
#:    재고 전송 실패를 「수량이 상한을 넘었다」로 오진했을 때 **내가 지어낸 값**이다.
#:    진짜 원인은 재고번호(prdStckNo) 자리에 옵션번호(mixOptNo '1,2')를 넣은 것이었고,
#:    문서 어디에도 재고 상한은 없다(예제 재고 500·62·99).
#:    근거 없는 제약을 코드·지도에 적으면 **되는 것도 안 하게 된다.**
STOCK_BOUNDS = None


@dataclass
class Eleven11Ops:
    #: 러너가 읽어 가는 재고 허용범위(위 상수 참조).
    STOCK_BOUNDS = STOCK_BOUNDS

    product_id: str
    client: object
    _get_stocks: object = None
    _get_price: object = None
    _update_price: object = None
    _update_stock: object = None
    _get_detail: object = None
    _update_detail: object = None

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
            # ⚠️ 가격 **조회**는 products.py 에 있다(쓰기만 prices.py). 헷갈려 prices 에서
            #    집었다가 라이브에서 ImportError 로 죽었다(2026-08-12).
            from shared.platforms.eleven11.products import get_product_price as fn
        try:
            return fn(str(self.product_id), client=self.client)
        except Exception:  # noqa: BLE001
            return None

    def _detail(self):
        """상세 HTML. 🎯 상품조회엔 안 실려 온다 — **전용 API**(eleven11.903)로 읽는다."""
        fn = self._get_detail
        if fn is None:
            from shared.platforms.eleven11.detail_cont import get_detail_html as fn
        try:
            return fn(str(self.product_id), client=self.client)
        except Exception:  # noqa: BLE001 — 못 읽으면 확인불가(빈 문자열로 지어내지 않는다)
            return None

    def snapshot(self) -> Snapshot:
        rows = self._stocks()
        price = self._price()
        detail = self._detail()

        first = rows[0] if rows else {}
        stock = first.get("stock")
        # 🔴 [2026-08-12 라이브 2회 거부] 재고수량 변경의 열쇠는 **prd_stck_no** 하나뿐이다.
        #    seller_stock_cd(판매자 관리코드)나 opt_no 로 대신 채우면
        #    「옵션재고 번호 …의 수량 업데이트 실패」로 거부된다. 없으면 확인불가로 남긴다.
        stock_no = first.get("prd_stck_no")
        options = ((str(stock_no), stock, None),) if (rows and stock_no) else ()

        missing = tuple(_UNWRITABLE)
        if price is None:
            missing = missing + ("sale_price",)
        if stock is None or not options:
            missing = missing + ("stock",)
        if detail is None:
            missing = missing + ("detail_html",)

        return Snapshot(market="eleven11", product_id=str(self.product_id),
                        name=None, detail_html=detail, image_urls=None,
                        sale_price=price, options=options, missing=missing,
                        raw={"stocks": rows, "price": price,
                             "detail_len": len(detail or "") if detail else None})

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
                f"11번가는 {blocked} 축에 전용 수정 API 가 없습니다 — 상품수정(PUT)뿐인데 "
                f"그건 **전체 교체**라(문서 원문: 기존 데이터는 사라지고 교체됩니다) "
                f"필수 30여 개를 하나도 안 틀리고 되돌려 보내야 합니다. 보내지 않습니다.")

        if "detail_html" in changes:
            # 🎯 전용 API — 상품수정(전체 교체)을 피한다.
            fn = self._update_detail
            if fn is None:
                from shared.platforms.eleven11.detail_cont import update_detail_html as fn
            # ⚠️ 성공 응답이 빈 <Product/> 라 여기선 성공을 판정할 수 없다.
            #    러너가 되읽어 확인한다 — 그게 유일한 검증 수단이다.
            fn(str(self.product_id), str(changes["detail_html"]), client=self.client)

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
            rows = self._stocks()
            first = rows[0] if rows else {}
            stock_no = first.get("prd_stck_no")
            if not stock_no:
                raise RuntimeError("11번가 재고번호(prdStckNo)를 못 찾아 재고를 보낼 수 없습니다.")
            fn = self._update_stock
            if fn is None:
                # 🔴 update_stock(전체교체) 이 아니라 **재고번호 단위** 함수를 쓴다.
                from shared.platforms.eleven11.inventory import (
                    update_stock_by_stock_no as fn,
                )
            # ⚠️ 상품무게(optWght)는 **그대로 되돌려 보내야** 한다 — 빼면 무게가 지워진다.
            r = fn(str(self.product_id), str(stock_no), int(changes["stock"]),
                   first.get("opt_wght"), client=self.client)
            if not getattr(r, "success", True):
                raise RuntimeError(f"11번가 재고수정 실패: {getattr(r, 'error_message', '')}")


def make_eleven11_ops(product_id, *, client, **inject) -> Eleven11Ops:
    return Eleven11Ops(product_id=str(product_id), client=client, **inject)
