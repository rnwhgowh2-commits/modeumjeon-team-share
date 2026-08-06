# -*- coding: utf-8 -*-
"""쿠팡 5축 왕복 어댑터 — **두 갈래**다.

지도 근거:
  · 조회    GET  .../seller-products/{sellerProductId}
  · 재고조회 GET  .../vendor-items/{vendorItemId}/inventories
            🔴 상품상세에는 옵션 재고가 없다(2026-07-17 과거이력).
  · 가격    PUT  .../vendor-items/{vendorItemId}/prices/{price}      — **즉시 반영**
  · 재고    PUT  .../vendor-items/{vendorItemId}/quantities/{qty}    — **즉시 반영**
  · 3축     PUT  .../seller-products (전체 JSON 재전송)
            지도 원문: 「이 API를 사용하면 **승인 후에 반영**됩니다」

🔴 그래서 상품명·상세·이미지는 **보낸 직후 되읽으면 옛 값**일 수 있다(승인 대기).
   그걸 「안 바뀜 = 실패」로 적으면 거짓 보고다 — `APPROVAL_AXES` 로 갈라
   「보냈고, 승인 후 반영」으로 적는다.

🔴 `requested` 는 **false** 로 고정한다. true 면 판매 승인까지 요청한다 —
   시험이 판매중지 상품을 팔리게 만들면 안 된다.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from lemouton.uploader.roundtrip.snapshot import Snapshot

#: 승인 후 반영되는 축 — 즉시 되읽기로는 확인할 수 없다.
APPROVAL_AXES = ("name", "detail_html", "image_urls")

#: 🔴 가격·재고 전용 API 가 **에러 없이 안 먹는** 상태들(2026-08-06 라이브 실측).
#:    승인이 안 난 상품은 vendorItemId 가 활성이 아닌 것으로 보인다.
#:    조용한 무시라 「실패」로 적으면 멀쩡한 배선을 뜯게 된다 → 확인불가로 남긴다.
_PRICE_INERT_STATUSES = ("승인반려", "상품삭제", "임시저장", "심사중", "승인대기중")



def _first_item(detail: dict) -> dict:
    items = (detail or {}).get("items") or []
    return items[0] if items and isinstance(items[0], dict) else {}


def _images_of(item: dict):
    out = []
    for im in (item.get("images") or []):
        if not isinstance(im, dict):
            continue
        u = str(im.get("cdnPath") or im.get("vendorPath") or "").strip()
        if u:
            out.append(u)
    return tuple(out) or None


def _content_of(item: dict):
    for c in (item.get("contents") or []):
        for d in ((c or {}).get("contentDetails") or []):
            v = (d or {}).get("content")
            if v is not None:
                return v
    return None


@dataclass
class CoupangOps:
    seller_product_id: int
    client: object

    # ── 되읽기 ──────────────────────────────────────────────────────────────
    def _detail(self) -> dict:
        from shared.platforms import COUPANG
        path = COUPANG["paths"]["get_product"].format(
            sellerProductId=self.seller_product_id)
        resp = self.client.request(method="GET", path=path)
        return (resp or {}).get("data") or {}

    def _stock(self, vendor_item_id):
        """옵션 재고 — 상품상세엔 없다. 못 읽으면 None(0으로 채우지 않는다)."""
        if not vendor_item_id:
            return None
        from shared.platforms import COUPANG
        path = COUPANG["paths"]["get_inventory"].format(vendorItemId=vendor_item_id)
        try:
            resp = self.client.request(method="GET", path=path)
        except Exception:  # noqa: BLE001 — 못 읽으면 확인불가. 0 은 품절이라 절대 금지.
            return None
        data = (resp or {}).get("data") or {}
        v = data.get("amountInStock")
        if v is None:
            v = data.get("quantity")
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def snapshot(self) -> Snapshot:
        detail = self._detail()
        item = _first_item(detail)
        vid = item.get("vendorItemId")

        name = detail.get("sellerProductName")
        html = _content_of(item)
        imgs = _images_of(item)
        price = item.get("salePrice")
        stock = self._stock(vid)

        missing = tuple(a for a, v in (("name", name), ("detail_html", html),
                                       ("image_urls", imgs), ("sale_price", price))
                        if v is None)
        options = ((str(vid), stock, price),) if vid else ()
        if stock is None:
            missing = missing + ("stock",)

        # 🔴 [2026-08-06 라이브] 승인반려 상품에 가격을 보내면 **에러 없이 200** 인데
        #    되읽으면 옛 값 그대로다(조용한 무시 — 가장 위험한 부류).
        #    승인이 안 난 상품은 vendorItemId 가 활성이 아닌 것으로 보인다.
        #    「보냈는데 안 바뀜=실패」로 적으면 멀쩡한 배선을 뜯게 되므로 확인불가로 남긴다.
        if str(detail.get("statusName") or "").strip() in _PRICE_INERT_STATUSES:
            for axis in ("sale_price", "stock"):
                if axis not in missing:
                    missing = missing + (axis,)

        return Snapshot(market="coupang", product_id=str(self.seller_product_id),
                        name=name, detail_html=html, image_urls=imgs,
                        sale_price=price, options=options, missing=missing, raw=detail)

    def on_sale(self) -> bool:
        """**판매중지가 확실할 때만** False. 나머지는 전부 True(= 시험 거부).

        🔴 쿠팡 statusName 은 「부분승인완료·승인반려·상품삭제」가 판매중지다
           (「중지」라는 낱말이 안 들어간다 — 손수 만든 낱말 판정이 통째로 빗나갔던 이력).
           판정은 정본 `catalog/status.unify_status` 하나만 쓴다.
           대기(임시저장·심사중·승인대기중)도 건드리면 심사 흐름이 꼬이므로 거부한다.
        """
        from lemouton.uploader.roundtrip.sale_status import is_stopped
        return not is_stopped("coupang", (self._detail() or {}).get("statusName"))

    # ── 쓰기 ────────────────────────────────────────────────────────────────
    def apply(self, changes: dict) -> None:
        detail = self._detail()
        item = _first_item(detail)
        vid = item.get("vendorItemId")

        # ① 가격·재고 — 전용 경로(즉시). 전체수정으로 보내면 승인 대기에 걸린다.
        if "sale_price" in changes:
            from shared.platforms.coupang.prices import update_price
            from shared.platforms.price_guard import assert_live_sale_price
            assert_live_sale_price(changes["sale_price"],
                                   context=f"coupang roundtrip vid={vid}")
            update_price(vid, int(changes["sale_price"]), client=self.client)
        if "stock" in changes:
            from shared.platforms.coupang.inventory import update_quantity
            update_quantity(vid, int(changes["stock"]), client=self.client)

        # ② 상품명·상세·이미지 — 전체 JSON 재전송 한 번(승인 후 반영)
        wants = [a for a in APPROVAL_AXES if a in changes]
        if not wants:
            return

        body = copy.deepcopy(detail)
        bitem = _first_item(body)
        if "name" in changes:
            nm = str(changes["name"]).strip()
            if not nm:
                raise ValueError("상품명을 빈 값으로 보낼 수 없습니다.")
            body["sellerProductName"] = nm
        if "detail_html" in changes:
            bitem["contents"] = [{
                "contentsType": "TEXT",
                "contentDetails": [{"content": str(changes["detail_html"]),
                                    "detailType": "TEXT"}],
            }]
        if "image_urls" in changes:
            urls = [str(u).strip() for u in (changes["image_urls"] or []) if str(u or "").strip()]
            if not urls:
                raise ValueError("이미지를 빈 목록으로 보낼 수 없습니다.")
            bitem["images"] = [
                {"imageOrder": i,
                 "imageType": "REPRESENTATION" if i == 0 else "DETAIL",
                 "cdnPath": u, "vendorPath": u}
                for i, u in enumerate(urls)
            ]
        # 🔴 판매 승인까지 요청하지 않는다 — 시험이 상품을 팔리게 만들면 안 된다.
        body["requested"] = False

        from shared.platforms import COUPANG
        resp = self.client.request(method="PUT", path=COUPANG["paths"]["create_product"],
                                   body=body)
        code = str((resp or {}).get("code") or "").upper()
        if code and not code.startswith("SUCCES"):
            raise RuntimeError(f"쿠팡 상품수정 실패: {code} {(resp or {}).get('message')}")


def make_coupang_ops(seller_product_id, *, client) -> CoupangOps:
    return CoupangOps(seller_product_id=int(seller_product_id), client=client)
