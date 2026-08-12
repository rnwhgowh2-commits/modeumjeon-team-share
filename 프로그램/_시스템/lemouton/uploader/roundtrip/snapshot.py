# -*- coding: utf-8 -*-
"""마켓에서 되읽은 5축 스냅샷.

**None 과 빈 값을 절대 섞지 않는다.**
    ``None``  = 그 마켓이 이 축을 안 준다(확인불가). 건드리면 안 된다.
    ``""``·0  = 마켓이 실제로 그 값을 갖고 있다.
    이걸 섞으면 「못 읽은 것」을 「비어 있는 것」으로 오해해 빈 값을 전송하게 되고,
    그 순간 원복할 원본이 사라진다. (market_fetch.py 의 stock=None 관례와 같은 이유)
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: 왕복 검증이 다루는 5축 — 이 순서가 화면·보고서 순서
AXES = ("sale_price", "stock", "name", "detail_html", "image_urls")

AXIS_LABELS = {
    "sale_price": "가격",
    "stock": "재고",
    "name": "상품명",
    "detail_html": "상세페이지",
    "image_urls": "이미지",
}


@dataclass(frozen=True)
class Snapshot:
    """한 시점에 마켓이 갖고 있던 값. 원복의 유일한 근거."""

    market: str
    product_id: str
    name: str | None = None
    detail_html: str | None = None
    image_urls: tuple | None = None
    sale_price: int | None = None
    #: ((option_id, stock, price), ...) — stock/price 도 모르면 None
    options: tuple = ()
    #: 이 마켓이 못 주는 축 이름들 — 보고서에 「확인불가」로 나간다
    missing: tuple = ()
    #: 원본 응답(진단·손복구용)
    raw: dict = field(default_factory=dict)

    def value_of(self, axis: str):
        """축 이름 → 값. 'stock' 은 첫 옵션의 재고."""
        if axis == "stock":
            if not self.options:
                return None
            return self.options[0][1]
        return getattr(self, axis, None)

    def has(self, axis: str) -> bool:
        """이 축을 시험할 수 있나 — 마켓이 값을 줬고 missing 에도 없어야."""
        return axis not in self.missing and self.value_of(axis) is not None
