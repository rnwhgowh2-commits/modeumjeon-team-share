# -*- coding: utf-8 -*-
"""옥션·G마켓(ESM 2.0) 5축 왕복 어댑터.

지도 근거 — `auction.esm.20` / `gmarket.esm.20` (st=ok · 라이브검증):
    조회 [GET]  /item/v1/goods/{goodsNo}
    수정 [PUT]  /item/v1/goods/{goodsNo}      ← 등록과 같은 스키마, 마스터 goodsNo 로만
    상품명   itemBasicInfo.goodsName.kor
    가격     itemAddtionalInfo.price.Iac(옥션) / .Gmkt(G마켓)
    재고     itemAddtionalInfo.stock.Iac / .Gmkt
    이미지   itemAddtionalInfo.images.basicImgURL + addtionalImg1URL~14URL
    상세     itemAddtionalInfo.descriptions.kor.html
    판매상태 isSell.iac / isSell.gmkt   ← **수정 호출 시 필수 설정**

🔴 idTrap ①(지도 원문) — `isEditableGoodsName=false` 면 「상품명 수정해서 입력시
   처리되지 않으며 **별도 에러 처리 없음**」. 200 받고 안 바뀌는 부류라, 조회로
   미리 알 수 있는 이상 **아예 안 보낸다**.
🔴 idTrap ② — 옥션/G마켓은 한 상품(goodsNo) 아래 사이트별 값이 따로 있다.
   반대 사이트 칸을 읽거나 쓰면 남의 사이트 값을 건드린다.
🔴 idTrap ③ — 이미지가 줄면 남은 addtionalImgNURL 칸을 **지워야** 한다.
   안 지우면 원복했다고 믿는데 사진이 한 장 더 붙어 있다.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from lemouton.uploader.roundtrip.snapshot import Snapshot

#: 우리 마켓 슬러그 → (가격·재고 칸 이름, isSell 칸 이름)
_SITE = {"auction": ("Iac", "iac"), "gmarket": ("Gmkt", "gmkt")}
_MAX_EXTRA_IMAGES = 14
_BASE_STOCK_ID = "__base__"


def _dig(d, *keys):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _put(d, value, *keys):
    cur = d
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[keys[-1]] = value


@dataclass
class EsmOps:
    goods_no: str
    market: str
    client: object

    @property
    def _cols(self):
        try:
            return _SITE[self.market]
        except KeyError:
            raise ValueError(f"ESM 마켓은 auction/gmarket 만: {self.market!r}") from None

    def _path(self, key: str) -> str:
        paths = (getattr(self.client, "_cfg", None) or {}).get("paths") or {}
        tmpl = paths.get(key)
        if not tmpl:
            raise ValueError(f"ESM {key} 경로 미설정(스펙 미확보) — 지어내지 않고 멈춥니다.")
        return tmpl.format(goodsNo=str(self.goods_no))

    # ── 되읽기 ──────────────────────────────────────────────────────────────
    def _get(self) -> dict:
        resp = self.client.request(method="GET", path=self._path("detail"))
        if isinstance(resp, dict) and isinstance(resp.get("data"), dict):
            resp = resp["data"]          # 봉투를 쓰는 응답 형태 대응
        return resp if isinstance(resp, dict) else {}

    def snapshot(self) -> Snapshot:
        price_col, _ = self._cols
        g = self._get()

        name = _dig(g, "itemBasicInfo", "goodsName", "kor")
        price = _dig(g, "itemAddtionalInfo", "price", price_col)
        stock = _dig(g, "itemAddtionalInfo", "stock", price_col)
        html = _dig(g, "itemAddtionalInfo", "descriptions", "kor", "html")

        imgs_node = _dig(g, "itemAddtionalInfo", "images") or {}
        rep = str(imgs_node.get("basicImgURL") or "").strip()
        imgs = None
        if rep:
            extra = []
            for i in range(1, _MAX_EXTRA_IMAGES + 1):
                u = str(imgs_node.get(f"addtionalImg{i}URL") or "").strip()
                if u:
                    extra.append(u)
            imgs = (rep,) + tuple(extra)

        options = ((_BASE_STOCK_ID, stock, None),) if stock is not None else ()

        missing = tuple(a for a, v in (("name", name), ("sale_price", price),
                                       ("detail_html", html), ("image_urls", imgs))
                        if v is None)
        if stock is None:
            missing = missing + ("stock",)
        # 🔴 상품명 수정 불가 상품 — 보내도 조용히 무시되므로 시험 대상에서 뺀다.
        if g.get("isEditableGoodsName") is False and "name" not in missing:
            missing = missing + ("name",)

        return Snapshot(market=self.market, product_id=str(self.goods_no),
                        name=name, detail_html=html, image_urls=imgs,
                        sale_price=price, options=options, missing=missing, raw=g)

    def on_sale(self) -> bool:
        """판매중이면 True. 상태를 못 읽으면 판매중으로 본다(안전 쪽으로 틀린다)."""
        _, sell_col = self._cols
        return _dig(self._get(), "isSell", sell_col) is not False

    # ── 쓰기 ────────────────────────────────────────────────────────────────
    def apply(self, changes: dict) -> None:
        price_col, sell_col = self._cols
        g = self._get()
        body = copy.deepcopy(g)

        if "name" in changes:
            if g.get("isEditableGoodsName") is False:
                raise RuntimeError(
                    "이 상품은 상품명 수정이 막혀 있습니다(isEditableGoodsName=false) — "
                    "보내도 에러 없이 무시되므로 보내지 않습니다.")
            _put(body, str(changes["name"]), "itemBasicInfo", "goodsName", "kor")

        if "sale_price" in changes:
            _put(body, int(changes["sale_price"]), "itemAddtionalInfo", "price", price_col)
        if "stock" in changes:
            _put(body, int(changes["stock"]), "itemAddtionalInfo", "stock", price_col)
        if "detail_html" in changes:
            _put(body, str(changes["detail_html"]),
                 "itemAddtionalInfo", "descriptions", "kor", "html")

        if "image_urls" in changes:
            urls = [str(u).strip() for u in (changes["image_urls"] or []) if str(u or "").strip()]
            if not urls:
                raise ValueError("이미지를 빈 목록으로 보낼 수 없습니다.")
            node = _dig(body, "itemAddtionalInfo", "images")
            if not isinstance(node, dict):
                node = {}
                _put(body, node, "itemAddtionalInfo", "images")
            node["basicImgURL"] = urls[0]
            for i in range(1, _MAX_EXTRA_IMAGES + 1):
                key = f"addtionalImg{i}URL"
                if i < len(urls):
                    node[key] = urls[i]
                else:
                    node.pop(key, None)     # 🔴 남은 옛 칸을 지운다

        # 판매상태는 수정 호출 시 **필수** — 조회한 현재 상태를 그대로 실어 보낸다.
        cur_sell = _dig(g, "isSell", sell_col)
        _put(body, bool(cur_sell) if cur_sell is not None else False, "isSell", sell_col)

        resp = self.client.request(method="PUT", path=self._path("update"), body=body)
        code = (resp or {}).get("resultCode") if isinstance(resp, dict) else None
        if code not in (None, 0, "0"):
            msg = (resp or {}).get("message") if isinstance(resp, dict) else ""
            raise RuntimeError(f"ESM 수정 실패: resultCode={code} {msg}")


def make_esm_ops(goods_no, *, market: str, client) -> EsmOps:
    return EsmOps(goods_no=str(goods_no), market=market, client=client)
