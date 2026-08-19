# -*- coding: utf-8 -*-
"""SKU 연결상태 호버카드 — SKU 하나하나의 정체성(번호·브랜드·모델명·색상·사이즈).

옵션 매트릭스 목록(`webapp/routes/optgen.py`)의 「SKU 연결상태」 칸이 펼치는
카드가 쓰는 자료다. 품번·바코드·GTIN(`lemouton/matrix/sku_info.py`)과는
다른 물음이다 — 그건 「번호를 다 적었나」, 이건 **「이 SKU 가 누구인가」**다.
두 칸은 서로 다른 것을 세므로 자료도 따로 둔다.

🔴 사이즈 축이 매트릭스 전체에서 **서로 다른 값 1개뿐**이면 그 값 대신
   「FREE」를 보여준다(사장님 지시 — "사이즈(1개면 free)"). 2개 이상이면
   그대로 보여준다. 값이 아예 없는 옵션은 「FREE」로 지어내지 않는다 — None.
"""
from __future__ import annotations


def rows_of(session, code: str) -> list[dict]:
    """묶음 하나의 SKU 줄 목록.

    한 줄: `{sku, no, brand, model_name, color, size}`
      · `sku`        — canonical_sku (SKU 번호)
      · `no`         — 옵션번호(`display_no`). 없으면 `None`
      · `brand`      — 옵션 자체 브랜드 → 모델 상속(`effective_option_brand`)
      · `model_name` — `lemouton.matrix.option_name.model_name_of` 판정 그대로
      · `color`      — `color_display`(없으면 `color_code`). 둘 다 없으면 `None`
      · `size`       — 위와 같되, 매트릭스 전체가 사이즈 1개뿐이면 「FREE」

    🔴 화면 순서는 `sku_info.rows_of` 와 **같다**(`sort_order` → `canonical_sku`).
       두 호버카드가 같은 SKU 를 다른 순서로 보여주면 사장님이 서로 다른
       목록을 보고 있다고 오해한다.

    묶음이 없으면 빈 목록 — 없는 것을 지어내지 않는다.
    """
    from lemouton.matrix.option_name import model_name_of
    from lemouton.sourcing.axis_summary import axis_batch
    from lemouton.sourcing.models import Model, Option
    from lemouton.sourcing.option_brand import effective_option_brand

    model = session.query(Model).filter(Model.model_code == code).first()
    if model is None:
        return []

    axis_names = axis_batch(session, [code])[code]['axis_names']
    bundle_model_name = getattr(model, 'bundle_model_name', None)

    opts = (session.query(Option)
            .filter(Option.model_code == code)
            .order_by(Option.sort_order, Option.canonical_sku)
            .all())

    def _size_of(o) -> str:
        return (o.size_display or o.size_code or '').strip()

    distinct_sizes = {_size_of(o) for o in opts}
    distinct_sizes.discard('')
    one_size = len(distinct_sizes) == 1

    out = []
    for o in opts:
        size_val = _size_of(o)
        color_val = (o.color_display or o.color_code or '').strip()
        out.append({
            'sku': o.canonical_sku,
            'no': o.display_no or None,
            'brand': effective_option_brand(o),
            'model_name': model_name_of(model.model_name_display, o, axis_names,
                                        bundle_model_name=bundle_model_name),
            'color': color_val or None,
            'size': ('FREE' if (one_size and size_val) else (size_val or None)),
        })
    return out
