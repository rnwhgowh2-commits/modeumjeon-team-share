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
    stock: int = 0
    price: int = 0
    usable: bool = True


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

    매칭: 색상·사이즈 정규화가 모두 일치하는 모음전 옵션
          1개 → matched / 0개 → unmatched / 2개↑ → ambiguous(연결 보류).
    """
    rows: list[LinkRow] = []
    for mo in market_options:
        mc = normalize(mo.color or "")
        ms = normalize(mo.size or "")
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
