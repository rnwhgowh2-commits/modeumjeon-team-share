# -*- coding: utf-8 -*-
"""롯데온 5축 왕복 어댑터.

지도 근거:
  · 조회 POST /v1/openapi/product/v1/product/detail  (lotteon.product.get_detail · st=code)
        확보 필드: data.pdNm(상품명) · data.slStatCd(판매상태) ·
                   data.itmLst[].slPrc(판매가) · .stkQty(재고)
        🔴 `res.note = "전체 스펙 롯데ON apiNo=94"` — **상세 HTML·이미지 필드는 미확보**.
           문서로 모르는 것을 지어내지 않는다. 응답에 실제로 있으면 읽고, 없으면
           「확인불가」로 남긴다(프로브로 실측해 지도에 되채운 뒤 열린다).
  · 가격 POST .../item/price/change
  · 재고 POST .../item/stock/change
  · 3축  POST .../product/modification/request — 「수정 **요청**」 · st=code(문서만)

🔴 되읽을 수 없는 축은 **보내지 않는다.** 보내면 원복이 됐는지 영영 확인할 수 없다
   — 왕복 검증에서 가장 위험한 상태(마켓엔 시험값, 우리는 모름)다.

🔴 재고 미관리(stkMgtYn=N)면 센티넬 999,999,999 가 온다. 그대로 노출하면
   「재고 10억」이 된다 → None(확인불가).
"""
from __future__ import annotations

from dataclasses import dataclass

from lemouton.uploader.roundtrip.snapshot import Snapshot

_STOCK_UNMANAGED = 999999999

#: 🔴 **읽히지만 되돌려 쓸 수 없는 축.** 상품 수정(product/modification/request)이
#:    지도상 st=code(문서만)라 배선이 없다. 읽힌다고 시험 대상에 넣으면 전송에서
#:    거부되고, 그 바람에 **쓸 수 있는 축(가격·재고)까지 통째로 실패**한다
#:    (2026-08-06 라이브에서 실제로 겪음). 배선되면 이 목록에서 빼면 살아난다.
_UNWRITABLE = ("name", "detail_html", "image_urls")

#: 상세·이미지가 응답에 실려 올 때 쓰일 후보 열쇠(지도 미확보 → 실측으로 확정).
#: 못 찾으면 확인불가. **지어낸 값을 쓰지 않는다.**
_DETAIL_KEYS = ("pdDtlDesc", "pdDtlCntn", "dtlDesc", "detailContent", "pdDtlHtml")
_IMAGE_LIST_KEYS = ("imgLst", "pdImgLst", "images")
#: 🔴 실측 확정(2026-08-12) — 실제 열쇠는 `origImgFileNm` 이다. 나머지는 추측 후보였다.
_IMAGE_URL_KEYS = ("origImgFileNm", "imgUrl", "url", "imgPathNm", "imgNm")


def _pick(d: dict, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _images_of(detail: dict):
    """이미지 목록. 없으면 None(확인불가) — 빈 튜플로 「사진 없음」을 지어내지 않는다.

    🔴 [2026-08-12 라이브] 이미지는 **단품(itm) 안**에 있다:
           itmLst[].itmImgLst[].origImgFileNm
       그런데 상품 최상위에서 `imgLst`/`pdImgLst`/`images` 를 찾고 있었고, 그런 열쇠가
       없으니 「이 마켓은 이미지를 안 준다」로 굳어 있었다. 상세조회는 필드를 150개나
       주는데 우리가 안 본 것이다 — 「마켓이 안 준다」고 적기 전에 열쇠를 전수로 본다.
    """
    node = _pick(detail, _IMAGE_LIST_KEYS)
    if not isinstance(node, list) or not node:
        # 단품 안을 본다. 대표 단품(첫 행)의 이미지가 그 상품의 사진이다.
        for itm in (detail.get("itmLst") or []):
            if isinstance(itm, dict) and itm.get("itmImgLst"):
                node = itm["itmImgLst"]
                break
    if not isinstance(node, list) or not node:
        return None
    out = []
    for it in node:
        if isinstance(it, str) and it.strip():
            out.append((False, it.strip()))
        elif isinstance(it, dict):
            u = _pick(it, _IMAGE_URL_KEYS)
            if u:
                # 대표(rprtImgYn='Y')를 맨 앞으로 — 순서가 뒤바뀌면 원복했는데
                # 대표 사진이 달라진다.
                rep = str(it.get("rprtImgYn") or "").upper() == "Y"
                out.append((rep, str(u).strip()))
    out.sort(key=lambda x: not x[0])
    return tuple(u for _, u in out) or None


@dataclass
class LotteonOps:
    spd_no: str
    client: object

    @property
    def _cfg(self):
        from shared.platforms import LOTTEON
        return getattr(self.client, "_cfg", None) or LOTTEON

    def _base_body(self) -> dict:
        cfg = self._cfg
        return {"trGrpCd": cfg.get("tr_grp_cd", "SR"),
                "trNo": cfg.get("tr_no", ""),
                "lrtrNo": cfg.get("lrtr_no", "")}

    # ── 되읽기 ──────────────────────────────────────────────────────────────
    def _detail(self) -> dict:
        body = {**self._base_body(), "spdNo": str(self.spd_no)}
        resp = self.client.request(method="POST", path=self._cfg["paths"]["detail"],
                                   body=body)
        if str((resp or {}).get("returnCode")) not in ("0000", "SUCCESS"):
            raise RuntimeError(
                f"롯데온 상세조회 실패 spdNo={self.spd_no} "
                f"returnCode={(resp or {}).get('returnCode')} "
                f"message={(resp or {}).get('message')}")
        return (resp or {}).get("data") or {}

    def snapshot(self) -> Snapshot:
        d = self._detail()
        items = d.get("itmLst") or []
        first = items[0] if items and isinstance(items[0], dict) else {}

        name = d.get("pdNm")
        price = first.get("slPrc")
        html = _pick(d, _DETAIL_KEYS)
        imgs = _images_of(d)

        # 재고 — 미관리면 센티넬이 온다. 「재고 10억」으로 보이면 안 된다.
        managed = str(first.get("stkMgtYn") or "Y").strip().upper() != "N"
        raw = first.get("stkQty")
        stock = None if (not managed or raw == _STOCK_UNMANAGED) else raw

        missing = tuple(a for a, v in (("name", name), ("sale_price", price),
                                       ("detail_html", html), ("image_urls", imgs))
                        if v is None)
        # 🔴 [2026-08-06 라이브] 상품명은 조회로 **읽힌다**(pdNm). 그런데 쓰기는
        #    product/modification/request 뿐이고 지도상 st=code(문서만)라 배선이 없다.
        #    읽힌다고 시험 대상에 넣었더니 apply 가 거부하면서 **가격·재고까지 통째로**
        #    실패했다. 원칙 — **되돌려 쓸 수 없는 축은 읽히더라도 확인불가로 뺀다.**
        for axis in _UNWRITABLE:
            if axis not in missing:
                missing = missing + (axis,)
        options = ((str(first.get("sitmNo")), stock, price),) if first.get("sitmNo") else ()
        if stock is None:
            missing = missing + ("stock",)

        return Snapshot(market="lotteon", product_id=str(self.spd_no),
                        name=name, detail_html=html, image_urls=imgs,
                        sale_price=price, options=options, missing=missing, raw=d)

    def on_sale(self) -> bool:
        """**판매중지가 확실할 때만** False. 나머지는 전부 True(= 시험 거부).
        판정은 정본 `catalog/status.unify_status` 하나만 쓴다."""
        from lemouton.uploader.roundtrip.sale_status import is_stopped
        return not is_stopped("lotteon", (self._detail() or {}).get("slStatCd"))

    # ── 쓰기 ────────────────────────────────────────────────────────────────
    def apply(self, changes: dict) -> None:
        snap = self.snapshot()
        # 🔴 되읽을 수 없는 축은 보내지 않는다 — 원복 확인이 불가능해진다.
        blocked = [a for a in ("name", "detail_html", "image_urls")
                   if a in changes and a in snap.missing]
        if blocked:
            raise RuntimeError(
                f"롯데온은 {blocked} 축을 조회로 되읽을 수 없습니다(지도 미확보 — 확인불가). "
                f"되읽지 못하는 값을 보내면 원복됐는지 영영 확인할 수 없어 보내지 않습니다.")
        if any(a in changes for a in ("name", "detail_html", "image_urls")):
            raise RuntimeError(
                "롯데온 상품 수정(product/modification/request)은 지도상 st=code(문서만)라 "
                "아직 배선하지 않았습니다 — 없는 것을 있는 척 하지 않습니다.")

        if not snap.options:
            raise RuntimeError("단품(sitmNo)을 못 찾아 가격·재고를 보낼 수 없습니다.")
        sitm_no = str(snap.options[0][0])
        cfg = self._cfg

        # 🔴 [2026-07-21 lotteon-register-spdlst-silent] body 를 손으로 조립하지 않는다.
        #    롯데온은 래퍼가 틀리면 **0건 접수를 「정상 처리되었습니다」로 응답**한다
        #    (returnCode 0000 + data[] 비어 있음). 그래서
        #      ① 래퍼(itmPrcLst / itmStkLst)를 이미 아는 **검증된 기존 writer** 를 쓰고
        #      ② 성공 판정은 returnCode 가 아니라 **항목별 결과**로 한다.
        if "sale_price" in changes:
            from shared.platforms.price_guard import assert_live_sale_price
            from shared.platforms.lotteon.prices import update_prices
            assert_live_sale_price(changes["sale_price"],
                                   context=f"lotteon roundtrip spd={self.spd_no}")
            results = update_prices(
                [{"spd_no": str(self.spd_no), "sitm_no": sitm_no,
                  "price": int(changes["sale_price"])}],
                client=self.client)
            self._check(results, "가격")

        if "stock" in changes:
            from shared.platforms.lotteon.inventory import update_stocks
            results = update_stocks(
                [{"spd_no": str(self.spd_no), "sitm_no": sitm_no,
                  "stock": int(changes["stock"])}],
                client=self.client)
            self._check(results, "재고")

    @staticmethod
    def _check(results, what):
        """항목별 결과로만 성공 판정. **빈 결과 = 실패**(0건 접수를 「정상」이라 답하는 마켓)."""
        rows = list(results or [])
        if not rows:
            raise RuntimeError(
                f"롯데온 {what} 변경 결과가 0건입니다 — 「정상 처리되었습니다」를 받아도 "
                f"항목이 없으면 아무것도 안 바뀐 것입니다(조용한 무시).")
        bad = [r for r in rows if not getattr(r, "success", False)]
        if bad:
            msgs = "; ".join(str(getattr(r, "error_message", "")) for r in bad)
            raise RuntimeError(f"롯데온 {what} 변경 실패: {msgs}")


def make_lotteon_ops(spd_no, *, client) -> LotteonOps:
    return LotteonOps(spd_no=str(spd_no), client=client)
