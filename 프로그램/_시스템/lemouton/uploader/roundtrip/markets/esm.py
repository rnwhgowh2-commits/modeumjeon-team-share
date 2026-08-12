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

#: 🔴 [2026-07-21 esm-stock-zero-oversell-guard] ESM 재고 유효범위. **0 은 규격상 무효**다.
#:    품절을 재고 0 으로 보내면 마켓이 거부(에러 1000)하는데 우리는 성공으로 알고 계속 판다
#:    = 오버셀. 품절은 재고가 아니라 플래그(isSoldOutSite / isSell=false)로 표현한다.
_STOCK_MIN, _STOCK_MAX = 1, 99999
#: [2026-07-21 esm-register-400-triple] 가격 유효범위(10원~10억).
_PRICE_MIN, _PRICE_MAX = 10, 10 ** 9
#: 판매기간 「기존 유지」 값. 수정 API 는 -1/0/15/30/60/90 만 받는데 조회는
#: **남은 일수**를 준다 — 조회값을 되돌리면 400. 0 = 기존 기간 유지(지도 원문).
_PERIOD_KEEP = 0


def _error_body(exc) -> str:
    """마켓이 4xx 와 함께 보낸 **사유 본문**을 꺼낸다. 못 꺼내면 빈 문자열.

    🔴 requests 의 raise_for_status 는 본문을 버린다 — 그런데 ESM 은 400 본문에
       `{"resultCode":1000,"message":"…"}` 로 **진짜 스펙**을 적어 보낸다.
       이걸 못 보면 「400 인데 이유를 모른다」로 막힌다(지도 이력의 교훈).
    """
    resp = getattr(exc, "response", None)
    if resp is None:
        return ""
    try:
        text = resp.text or ""
    except Exception:  # noqa: BLE001
        return ""
    if not text:
        return ""
    try:
        import json as _j
        data = _j.loads(text)
        if isinstance(data, dict):
            msg = data.get("message") or data.get("Message") or ""
            code = data.get("resultCode")
            if msg or code is not None:
                return f"resultCode={code} {msg}".strip()
    except Exception:  # noqa: BLE001 — JSON 이 아니면 원문 그대로
        pass
    return text[:400]



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
    #: 러너가 읽어 가는 재고 허용범위 — 0 은 규격상 무효(품절은 플래그로 표현).
    STOCK_BOUNDS = (_STOCK_MIN, _STOCK_MAX)

    goods_no: str
    market: str
    client: object
    #: 🔴 [2026-08-07 사고] 상품명 축은 **기본 끔**. 실제로 잠긴 적이 있다 —
    #:    판매중지 상품에 가격·상품명·상세를 바꿨더니 첫 전송 직후 마켓이
    #:    「지식재산권침해 우려(1250) 노출 제한」으로 상품을 잠갔고,
    #:    원복도 손복구도 거부돼 **되돌릴 수 없는 변경**이 남았다.
    #:    상품명에 브랜드가 들어가면 수정 자체가 재심사 대상이 된다.
    #:    근거가 생기면 allow_name=True 로 켤 수 있다(영영 막지는 않는다).
    allow_name: bool = False

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

    def _option_rows(self) -> list[tuple[str, object]]:
        """옵션 API(esm.26)가 주는 **진짜 옵션 식별자(optSeq)** 와 그 사이트 재고.

        🔴 [2026-08-08] 여기 없이 상품 상세만 읽고 `"__base__"` 라는 **우리가 지어낸
           이름**을 재고 API 에 넘겼다 → 마켓이 대상 옵션을 못 찾아 재고가 통째로 실패.
           재고를 쓰는 API 가 요구하는 열쇠는 그 API 로 읽어야 한다.
        옵션이 없으면 빈 목록 — 그때는 **본품 재고 API** 를 쓴다(옵션 API 대상이 아님).
        """
        col, _ = self._cols               # 'Iac' / 'Gmkt'
        try:
            from shared.platforms.esm.inventory import (
                _ci_get, _find_option_details, _option_id_of,
            )
            env = self.client.request(method="GET", path=self._path("options"))
            details = _find_option_details(env) or []
        except Exception:  # noqa: BLE001 — 못 읽으면 옵션 없음이 아니라 '모름'
            return []
        out = []
        for d in details:
            if not isinstance(d, dict):
                continue
            oid = _option_id_of(d)
            if not oid:
                continue                   # 식별자를 모르면 그 옵션은 건드리지 않는다
            qty = _ci_get(d, "qty") or {}
            out.append((oid, qty.get(col) if isinstance(qty, dict) else None))
        return out

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

        # 🔴 재고를 쓰는 API 가 요구하는 열쇠(optSeq)는 **그 API 로 읽는다**.
        #    상품 상세만 읽고 이름을 지어내면 대상 옵션을 못 찾아 통째로 실패한다.
        opt_rows = self._option_rows()
        if opt_rows:
            oid, oqty = opt_rows[0]
            options = ((oid, oqty if oqty is not None else stock, None),)
        elif stock is not None:
            options = ((_BASE_STOCK_ID, stock, None),)   # 본품만 — 본품 재고 API 로 간다
        else:
            options = ()

        missing = tuple(a for a, v in (("name", name), ("sale_price", price),
                                       ("detail_html", html), ("image_urls", imgs))
                        if v is None)
        # 🔴 원래 재고가 규격 밖(0 등)이면 **원복할 값이 무효**라 왕복이 성립하지 않는다.
        #    시험했다가 원복에서 400 이 나면 마켓에 시험값이 그대로 남는다 → 아예 안 건드린다.
        #    판정은 **원복할 값**(= 우리가 실제로 되돌려 보낼 옵션 재고)으로 한다.
        cur_stock = options[0][1] if options else None
        if cur_stock is None or not (_STOCK_MIN <= int(cur_stock) <= _STOCK_MAX):
            missing = missing + ("stock",)
        # 🔴 상품명 수정 불가 상품 — 보내도 조용히 무시되므로 시험 대상에서 뺀다.
        # 🔴 그리고 상품명 축은 **기본 끔**(2026-08-07 사고 — 재심사 유발로 상품이 잠김).
        if (not self.allow_name or g.get("isEditableGoodsName") is False) \
                and "name" not in missing:
            missing = missing + ("name",)

        return Snapshot(market=self.market, product_id=str(self.goods_no),
                        name=name, detail_html=html, image_urls=imgs,
                        sale_price=price, options=options, missing=missing, raw=g)

    def on_sale(self) -> bool:
        """**판매중지가 확실할 때만** False. 나머지는 전부 True(= 시험 거부).

        ESM 은 상태코드가 아니라 `isSell` 불리언으로 온다 — False 가 곧 판매중지.
        (다른 마켓은 정본 `catalog/status.unify_status` 를 쓴다 — 여긴 코드표가 아님)
        """
        _, sell_col = self._cols
        return _dig(self._get(), "isSell", sell_col) is not False

    # ── 쓰기 ────────────────────────────────────────────────────────────────
    def apply(self, changes: dict, *, _price_fn=None, _stock_fn=None,
              _base_stock_fn=None) -> None:
        """🔴 [2026-08-07] **가격·재고는 전용 API**, 3축만 전체 상품수정 PUT.

        전체 PUT(esm.20)으로 가격을 바꿨더니 **재심사가 돌아 브랜드 상품이 잠겼다**.
        지도에 전용 API 가 따로 있었다(쿠팡과 같은 구조인데 ESM 만 놓쳤다):
          · 가격 esm.186 `PUT /item/v1/goods/{goodsNo}/price`      ← esm/prices.update_price
          · 재고 esm.26  `PUT .../recommended-options` (st=ok)      ← esm/inventory.update_stock
        ⚠️ esm.186 원문: 「판매중지 상품은 가격 수정되지 않습니다」 — 판매중 상품에만 먹는다.
        """
        price_col, sell_col = self._cols

        # ① 가격 — 전용 API(전체 PUT 금지)
        if "sale_price" in changes:
            v = int(changes["sale_price"])
            if not (_PRICE_MIN <= v <= _PRICE_MAX):
                raise ValueError(f"ESM 가격은 {_PRICE_MIN}~{_PRICE_MAX:,} 범위여야 합니다: {v}")
            fn = _price_fn
            if fn is None:
                from shared.platforms.esm.prices import update_price as fn
            r = fn(str(self.goods_no), self.market, v, client=self.client)
            if not getattr(r, "success", True):
                raise RuntimeError(f"ESM 가격 수정 실패: {getattr(r, 'error_message', '')}")

        # ② 재고 — 옵션 관리 API(전체 PUT 금지)
        if "stock" in changes:
            v = int(changes["stock"])
            # 🔴 0 은 규격상 무효 — 품절은 재고가 아니라 플래그로 표현한다(오버셀 이력).
            if not (_STOCK_MIN <= v <= _STOCK_MAX):
                raise ValueError(
                    f"ESM 재고는 {_STOCK_MIN}~{_STOCK_MAX:,} 범위여야 합니다: {v} "
                    f"(0 은 규격상 무효 — 품절은 isSoldOutSite/isSell 로 표현합니다)")
            opt_rows = self._option_rows()
            if opt_rows:
                # 옵션 상품 — 옵션 API(esm.26)에 **그 API 가 준 optSeq** 로 보낸다.
                opt_id = str(opt_rows[0][0])
                fn = _stock_fn
                if fn is None:
                    from shared.platforms.esm.inventory import update_stock as fn
                if not fn(str(self.goods_no), self.market, opt_id, v, client=self.client):
                    raise RuntimeError(
                        f"ESM 재고 수정 실패 — 옵션 {opt_id} (goodsNo={self.goods_no}, "
                        f"{self.market}). 옵션 API 가 거부했습니다.")
            else:
                # 본품만 판매하는 상품 — 옵션 API 대상이 아니다(문서 /194 명시).
                fn = _base_stock_fn
                if fn is None:
                    from shared.platforms.esm.inventory import update_base_stock as fn
                if not fn(str(self.goods_no), self.market, v, client=self.client):
                    raise RuntimeError(
                        f"ESM 본품 재고 수정 실패 (goodsNo={self.goods_no}, {self.market})")

        # ③ 상품명·상세·이미지 — 전용 API 가 없다. 전체 PUT 뿐이라 재심사 위험이 있다.
        heavy = [a for a in ("name", "detail_html", "image_urls") if a in changes]
        if not heavy:
            return

        g = self._get()
        body = copy.deepcopy(g)

        if "name" in changes:
            if g.get("isEditableGoodsName") is False:
                raise RuntimeError(
                    "이 상품은 상품명 수정이 막혀 있습니다(isEditableGoodsName=false) — "
                    "보내도 에러 없이 무시되므로 보내지 않습니다.")
            _put(body, str(changes["name"]), "itemBasicInfo", "goodsName", "kor")

        # 🔴 [esm-register-400-triple] 양쪽 사이트가 **둘 다 유효값**이어야 한다.
        #    반대편이 0/누락이면 400(범위 위반). 노출은 category.site 가 통제하므로
        #    반대편에 유효값을 채워도 그 사이트에 팔리지 않는다.
        for node, col_a, col_b, lo, hi in (
                ("price", "Iac", "Gmkt", _PRICE_MIN, _PRICE_MAX),
                ("stock", "Iac", "Gmkt", _STOCK_MIN, _STOCK_MAX)):
            cur = _dig(body, "itemAddtionalInfo", node) or {}
            good = [v for v in (cur.get(col_a), cur.get(col_b))
                    if isinstance(v, int) and lo <= v <= hi]
            if not good:
                continue        # 둘 다 모르면 손대지 않는다(지어내지 않음)
            fill = good[0]
            for c in (col_a, col_b):
                v = cur.get(c)
                if not (isinstance(v, int) and lo <= v <= hi):
                    _put(body, fill, "itemAddtionalInfo", node, c)
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

        # 🔴 [2026-08-06 라이브] 판매기간 — 조회값을 그대로 되돌리면 400.
        #    resultCode=1000 "[IAC] 판매기간은 -1(무제한), 0, 15, 30, 60, 90만 가능합니다."
        #    지도 원문: 「조회 API 경우 **남은 판매 기간** 확인 가능」 · 「수정시 **0** 입력
        #    경우 **기존 기간 유지**」 → 조회는 남은 일수(37 등)를 주고 수정은 안 받는다.
        #    0 이 유일하게 안전한 값이다 — 상품 설정을 바꾸지 않으면서 거부도 안 된다.
        period = _dig(body, "itemAddtionalInfo", "sellingPeriod")
        if isinstance(period, dict):
            for c in ("Iac", "Gmkt"):
                if c in period:
                    period[c] = _PERIOD_KEEP

        # 판매상태는 수정 호출 시 **필수** — 조회한 현재 상태를 그대로 실어 보낸다.
        cur_sell = _dig(g, "isSell", sell_col)
        _put(body, bool(cur_sell) if cur_sell is not None else False, "isSell", sell_col)

        try:
            resp = self.client.request(method="PUT", path=self._path("update"), body=body)
        except Exception as e:  # noqa: BLE001
            # 🔴 [지도 이력 esm-register-400-triple] 「400 본문(resultCode 1000 message)이
            #    진짜 스펙이다. raise_for_status 로 본문을 버리면 스펙 발굴이 불가능해진다.」
            #    마켓이 준 사유를 건져 올린다 — 못 건지면 원래 예외를 그대로 올린다(삼키지 않음).
            detail = _error_body(e)
            if detail:
                raise RuntimeError(f"ESM 수정 실패: {detail}") from e
            raise
        code = (resp or {}).get("resultCode") if isinstance(resp, dict) else None
        if code not in (None, 0, "0"):
            msg = (resp or {}).get("message") if isinstance(resp, dict) else ""
            raise RuntimeError(f"ESM 수정 실패: resultCode={code} {msg}")


def resolve_master_goods_no(raw, *, client) -> str:
    """어떤 번호를 줘도 **마스터 goodsNo** 로. 수정은 마스터번호로만 된다.

    🔴 [2026-08-06 라이브] 후보 조회는 이미 마스터 goodsNo 를 준다. 그걸 다시
       site-goods 변환에 넣으면 400 「사이트 상품 번호가 잘 못 되었습니다」로 죽는다.
       변환이 실패하면 **입력값을 마스터로 보고 넘어간다** — 진짜 판별은 상세조회가 한다
       (없는 번호면 상세조회가 실패하므로 조용히 틀린 상품을 건드리지 않는다).
    """
    raw = str(raw)
    try:
        from shared.platforms.esm.products import resolve_goods_no
        got = resolve_goods_no(raw, client=client)
        return str(got or raw)
    except Exception:  # noqa: BLE001 — 이미 마스터번호인 경우가 대부분이다
        return raw


def make_esm_ops(goods_no, *, market: str, client, allow_name: bool = False) -> EsmOps:
    return EsmOps(goods_no=str(goods_no), market=market, client=client,
                  allow_name=bool(allow_name))
