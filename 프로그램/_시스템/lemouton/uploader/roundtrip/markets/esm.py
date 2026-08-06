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
        # 🔴 원래 재고가 규격 밖(0 등)이면 **원복할 값이 무효**라 왕복이 성립하지 않는다.
        #    시험했다가 원복에서 400 이 나면 마켓에 시험값이 그대로 남는다 → 아예 안 건드린다.
        if stock is None or not (_STOCK_MIN <= int(stock) <= _STOCK_MAX):
            missing = missing + ("stock",)
        # 🔴 상품명 수정 불가 상품 — 보내도 조용히 무시되므로 시험 대상에서 뺀다.
        if g.get("isEditableGoodsName") is False and "name" not in missing:
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
            v = int(changes["sale_price"])
            if not (_PRICE_MIN <= v <= _PRICE_MAX):
                raise ValueError(f"ESM 가격은 {_PRICE_MIN}~{_PRICE_MAX:,} 범위여야 합니다: {v}")
            _put(body, v, "itemAddtionalInfo", "price", price_col)
        if "stock" in changes:
            v = int(changes["stock"])
            # 🔴 0 은 규격상 무효 — 품절은 재고가 아니라 플래그로 표현한다(오버셀 이력).
            if not (_STOCK_MIN <= v <= _STOCK_MAX):
                raise ValueError(
                    f"ESM 재고는 {_STOCK_MIN}~{_STOCK_MAX:,} 범위여야 합니다: {v} "
                    f"(0 은 규격상 무효 — 품절은 isSoldOutSite/isSell 로 표현합니다)")
            _put(body, v, "itemAddtionalInfo", "stock", price_col)

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


def make_esm_ops(goods_no, *, market: str, client) -> EsmOps:
    return EsmOps(goods_no=str(goods_no), market=market, client=client)
