# -*- coding: utf-8 -*-
"""스마트스토어 왕복 어댑터.

5축 전부를 **한 번의 GET/PUT** 으로 다룬다 — Naver 커머스 수정은 originProduct 전체를
다시 보내는 형식이라(`edit_product.py`), 축마다 따로 PUT 하면 호출이 5배가 되고
스스는 동시성 8에서 429 가 72% 난다(지도 실측). 그래서 한 번에 묶어 보낸다.

⚠️ 상품번호는 **originProductNo**. 저장·조회 키인 channelProductNo 를 그대로 넣으면
   수정이 실패한다 (2026-07-17 과거이력) — 호출부가 `resolve_product_ids` 로 변환해서 준다.
"""
from __future__ import annotations

from dataclasses import dataclass

from lemouton.uploader.roundtrip.snapshot import Snapshot

_PATH = "/external/v2/products/origin-products/{no}"

#: 옵션 없는 단일상품의 재고를 담는 가짜 옵션ID. 진짜 옵션ID(정수)와 절대 안 겹치게
#: 문자열로 둔다 — 이 값이 옵션 수정으로 새어 나가면 남의 옵션을 건드린다.
_BASE_STOCK_ID = "__base__"


def _image_urls(images: dict) -> tuple | None:
    """대표 + 추가 이미지 URL. 대표가 없으면 None(확인불가) — 빈 튜플로 채우지 않는다."""
    if not isinstance(images, dict):
        return None
    rep = ((images.get("representativeImage") or {}).get("url") or "").strip()
    if not rep:
        return None
    extra = [str((x or {}).get("url") or "").strip()
             for x in (images.get("optionalImages") or [])]
    return (rep,) + tuple(u for u in extra if u)


@dataclass
class SmartStoreOps:
    origin_product_no: int
    client: object

    # ── 되읽기 ──────────────────────────────────────────────────────────────
    def _get(self) -> dict:
        resp = self.client.request("GET", _PATH.format(no=self.origin_product_no))
        return resp if isinstance(resp, dict) else {}

    def snapshot(self) -> Snapshot:
        payload = self._get()
        origin = payload.get("originProduct") or {}
        opt_info = ((origin.get("detailAttribute") or {}).get("optionInfo") or {})
        options = tuple(
            (str(c.get("id")), c.get("stockQuantity"), c.get("price"))
            for c in (opt_info.get("optionCombinations") or [])
            if c.get("id") is not None
        )
        name = origin.get("name")
        detail = origin.get("detailContent")
        imgs = _image_urls(origin.get("images") or {})
        price = origin.get("salePrice")

        # 옵션 없는 단일상품은 재고가 originProduct.stockQuantity 에 있다.
        # 옵션만 보고 「재고 확인불가」로 두면 단일상품은 영영 검증이 안 된다
        # (2026-08-06 라이브 1차에서 실제로 겪음).
        if not options:
            base_stock = origin.get("stockQuantity")
            if base_stock is not None:
                options = ((_BASE_STOCK_ID, base_stock, None),)

        # 마켓이 안 준 축은 이름을 남긴다 — 그래야 「전송 안 함 + 확인불가」로 나간다.
        missing = tuple(axis for axis, val in (
            ("name", name), ("detail_html", detail),
            ("image_urls", imgs), ("sale_price", price),
        ) if val is None)
        if not options:
            missing = missing + ("stock",)

        return Snapshot(
            market="smartstore", product_id=str(self.origin_product_no),
            name=name, detail_html=detail, image_urls=imgs,
            sale_price=price, options=options, missing=missing, raw=payload,
        )

    def on_sale(self) -> bool:
        """**판매중지가 확실할 때만** False. 나머지는 전부 True(= 시험 거부).

        판정은 정본 `catalog/status.unify_status` 하나만 쓴다 — 손수 만든 낱말 판정이
        마켓마다 빗나갔던 이력(쿠팡 300개 스캔 0건) 때문.
        """
        from lemouton.uploader.roundtrip.sale_status import is_stopped
        status = (self._get().get("originProduct") or {}).get("statusType")
        return not is_stopped("smartstore", status)

    # ── 쓰기 ────────────────────────────────────────────────────────────────
    def apply(self, changes: dict) -> None:
        from shared.platforms.smartstore.edit_product import edit_options

        option_updates = None
        base_stock = None
        if "stock" in changes:
            snap = self.snapshot()
            if not snap.options:
                raise RuntimeError("옵션도 상품재고도 없어 재고를 쓸 수 없습니다.")
            first_id = snap.options[0][0]
            if first_id == _BASE_STOCK_ID:
                base_stock = int(changes["stock"])       # 옵션 없는 단일상품
            else:
                # 첫 옵션만 — 형제 옵션까지 바꾸면 원복 범위가 커진다.
                option_updates = {int(first_id): {"stockQuantity": int(changes["stock"])}}

        r = edit_options(
            self.origin_product_no,
            sale_price=changes.get("sale_price"),
            option_updates=option_updates,
            base_stock_quantity=base_stock,
            name=changes.get("name"),
            detail_html=changes.get("detail_html"),
            image_urls=changes.get("image_urls"),
            client=self.client,
        )
        if not r.success:
            raise RuntimeError(f"스마트스토어 수정 실패: {r.error_code} {r.error_message} "
                               f"{r.invalid_inputs or ''}")


def make_smartstore_ops(origin_product_no, *, client) -> SmartStoreOps:
    return SmartStoreOps(origin_product_no=int(origin_product_no), client=client)
