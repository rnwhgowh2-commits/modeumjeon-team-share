"""[연결] 마켓 옵션 ↔ 모음전 옵션(canonical_sku) 매칭 코어.

순수 함수: DB·네트워크 없음. 라우트가 추출한 모음전 옵션 + 마켓에서 가져온
옵션 목록을 받아 색상·사이즈 정규화 일치로 canonical_sku 를 매핑한다.
정규화는 mapping.matcher.normalize 재사용(영한 색상·단위·공백 처리).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from lemouton.mapping.matcher import normalize


@dataclass
class MarketOption:
    """마켓에서 가져온 옵션 1개 (소싱처 무관 공통형)."""
    option_id: str
    color: Optional[str]
    size: Optional[str]
    stock: Optional[int] = None   # None = 미수집/미제공(쿠팡). 0 = 실제 품절.
    price: Optional[int] = None   # None = 미수집. 0 붕괴 금지.
    usable: bool = True
    # 🔴 [2026-08-13] 3갈래(모델명·색상·사이즈)로 올린 상품 때문에 둘이 늘었다.
    #   그런 상품은 마켓에서 name1=모델명 · name2=색상 · name3=사이즈 로 온다.
    #   `name3` 이 없으면 우리 (색상,사이즈)와 대조가 안 맞아 **전부 unmatched** 가 되고
    #   가격·재고가 **에러 없이 영영 안 나갔다.**
    #   `manager_code` = 우리가 등록할 때 써 넣은 `sellerManagerCode`(=canonical_sku).
    #   이름 대조보다 정확하다. 둘 다 기본값이 있어 기존 호출부는 그대로 돈다.
    name3: Optional[str] = None
    manager_code: Optional[str] = None


@dataclass
class LinkRow:
    """매칭 결과 1행."""
    market_option_id: str
    market_color: Optional[str]
    market_size: Optional[str]
    canonical_sku: Optional[str]
    status: str  # 'matched' | 'unmatched' | 'ambiguous'


def _color_keys(opt: dict) -> set[str]:
    return {normalize(opt.get("color_display") or ""),
            normalize(opt.get("color_code") or "")} - {""}


def _size_keys(opt: dict) -> set[str]:
    return {normalize(opt.get("size_display") or ""),
            normalize(opt.get("size_code") or "")} - {""}


def match_market_options_to_skus(
    bundle_options: list[dict],
    market_options: list[MarketOption],
) -> list[LinkRow]:
    """마켓 옵션 각각을 모음전 옵션(canonical_sku)에 매칭.

    bundle_options: [{"canonical_sku","color_code","color_display",
                      "size_code","size_display"}, ...]
    market_options: [MarketOption(...), ...]

    매칭 순서 (2026-08-13):
      ① **우리 SKU** — 마켓 `sellerManagerCode` 가 우리 `canonical_sku` 와 정확히 같으면
         그것으로 잇는다. 등록할 때 우리가 써 넣은 값이라 이름 대조보다 정확하다.
      ② 이름 대조 — ①이 없거나 안 맞을 때. 손으로 만든 옛 상품은 SKU 가 비어 있으므로
         이 길을 **지우지 않고 뒤에 남긴다.**
         · 3갈래 상품(마켓 name3 있음) → (모델, 색상, 사이즈) 세 값으로
         · 2갈래 상품 → 예전 그대로 (색상, 사이즈)
      1개 → matched / 0개 → unmatched / 2개↑ → ambiguous(연결 보류).
    """
    rows: list[LinkRow] = []
    by_sku = {b.get("canonical_sku"): b for b in bundle_options}
    for mo in market_options:
        # ── ① 우리 SKU 로 정확히 ───────────────────────────────────────────
        code = (mo.manager_code or "").strip()
        if code and code in by_sku:
            rows.append(LinkRow(mo.option_id, mo.color, mo.size, code, "matched"))
            continue
        # ── ② 이름 대조 ────────────────────────────────────────────────────
        mc = normalize(mo.color or "")
        ms = normalize(mo.size or "")
        m3 = normalize(mo.name3 or "")
        if m3:
            # 3갈래 — 마켓 칸이 (모델명, 색상, 사이즈) 로 한 칸씩 밀려 있다.
            hits = [
                b for b in bundle_options
                if mc and ms and m3
                and mc == normalize(b.get("model") or "")
                and ms in _color_keys(b) and m3 in _size_keys(b)
            ]
        else:
            hits = [
                b for b in bundle_options
                if mc and ms and mc in _color_keys(b) and ms in _size_keys(b)
            ]
        if len(hits) == 1:
            rows.append(LinkRow(mo.option_id, mo.color, mo.size,
                                hits[0]["canonical_sku"], "matched"))
        elif not hits:
            rows.append(LinkRow(mo.option_id, mo.color, mo.size, None, "unmatched"))
        else:
            rows.append(LinkRow(mo.option_id, mo.color, mo.size, None, "ambiguous"))
    return rows
