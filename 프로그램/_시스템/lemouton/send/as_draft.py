# -*- coding: utf-8 -*-
"""구성(벌) → 등록용 초안 — **신규 등록 경로를 새로 만들지 않기 위해서**.

마켓에 처음 올리는 일은 이미 다 만들어져 있다 —
`registration/service.py:register_draft()` 가 컴파일·이미지 CDN 재호스팅·게이트·
장부(중복 등록 방지)·등록 후 판매중지까지 들고 있고, 무엇이 모자란지는
`bulk/drafts.py:preflight_rows()` 가 **단일 판정기**로 알려 준다.

그 둘이 요구하는 것은 `ProductDraft` 한 줄뿐이다. 그래서 구성을 그 모양으로
비춰 주기만 하면 신규 등록이 그대로 돈다.

🔴 없는 값을 지어내지 않는다
  구성에는 아직 CDN 이미지·고시정보·A/S 같은 칸이 없다. 비워 두면 preflight 가
  **무엇이 없는지 정확히 말해 준다** — 그게 사장님이 볼 답이다.
  가짜 전화번호나 빈 고시로 채우면 마켓에 그대로 게시된다(폴백 금지).

🔴 초안을 **다시 쓰지 않고 갈아끼운다**
  구성마다 초안 한 줄만 둔다(`origin='set'`, `model_code`+이름으로 찾음).
  누를 때마다 새로 만들면 초안 표가 쓰레기로 찬다.
"""
from __future__ import annotations

import json

from lemouton.registration.models import ProductDraft

#: 이 초안이 구성에서 왔다는 표시 — 크롤 초안(`origin='crawl'`)과 섞이면 안 된다.
ORIGIN = 'set'


class DraftIncomplete(Exception):
    """초안을 만들 수 없다 — 사장님에게 그대로 보여줄 사유."""


def _price_for(session, *, set_id: int, market: str):
    """그 구성·그 마켓의 판매가. 정책이 정한 값을 **가격 엔진으로** 뽑는다.

    🔴 여기서 산식을 다시 쓰지 않는다 — `unified.compute_market_price` 가 정본이다.
      같은 숫자를 두 곳에서 만들면 반드시 갈린다.
    """
    from lemouton.policy.as_template import PREFIX_TO_MARKET
    from lemouton.policy.to_payload import price_template_for

    tpl = price_template_for(session, set_id=set_id)
    if tpl is None:
        return None
    prefix = next((p for p, m in PREFIX_TO_MARKET.items() if m == market), None)
    if not prefix:
        return None
    # 원가(최종매입가)가 있어야 마진을 붙인다. 없으면 값을 만들지 않는다(폴백 금지).
    cost = _cost_for(session, set_id=set_id)
    if not cost:
        return None
    try:
        from lemouton.pricing.unified import compute_market_price
        return compute_market_price(tpl, prefix, 'sourcing', cost).final_price
    except Exception:                       # noqa: BLE001
        return None


def _cost_for(session, *, set_id: int):
    """구성의 원가 — 옵션들 중 **가장 비싼** 최종매입가.

    ★ 왜 최댓값인가 — 한 구성 안 옵션들의 매입가가 다르면, 제일 비싼 것을 기준으로
      해야 어느 옵션이 팔려도 역마진이 안 난다. 평균을 쓰면 비싼 옵션에서 손해다.
    """
    from lemouton.policy.to_payload import _stock_by_sku
    from lemouton.sets.models import SetOption, SetProduct
    from lemouton.sourcing.option_sources import pick_cheapest_buyable

    ps_skus = [r[0] for r in session.query(SetOption.canonical_sku)
               .join(SetProduct, SetProduct.id == SetOption.set_product_id)
               .filter(SetProduct.set_id == set_id).all()]
    if not ps_skus:
        return None
    from lemouton.sets.models import ProductSet
    ps = session.get(ProductSet, set_id)
    by_sku = _stock_by_sku(session, ps.model_code) if ps else {}
    costs = []
    for sku in ps_skus:
        picked = pick_cheapest_buyable([dict(x) for x in (by_sku.get(sku) or [])])
        if picked:
            v = picked.get('final_purchase_price') or picked.get('crawled_price')
            if v:
                costs.append(int(v))
    return max(costs) if costs else None


def upsert(session, *, set_id: int, market: str, view=None):
    """구성 → 그 마켓용 초안 한 줄(있으면 갱신). 호출자가 commit.

    Args:
        view: `to_payload.build_for_set()['view']` — 정책이 적용된 사본.
            주면 그 이름·옵션을 쓴다(마켓마다 이름이 다르므로 마켓별로 받아야 한다).
    """
    from lemouton.policy import to_payload as TP
    from lemouton.sets.models import ProductSet
    from lemouton.sourcing.models import Model

    ps = session.get(ProductSet, set_id)
    if ps is None:
        raise ValueError(f'그런 구성이 없습니다: {set_id}')
    if view is None:
        view = TP.set_view(session, set_id=set_id)
    m = session.get(Model, ps.model_code)

    # 🔴 판매가를 **먼저** 구한다 — 초안을 만들어 둔 채로 가격을 계산하면, 계산 중
    #   도는 조회가 자동 플러시를 일으켜 **판매가 없는 빈 초안이 DB 로 밀려 들어간다**
    #   (NOT NULL 위반으로 터졌다 — 실측). 값이 없으면 초안을 아예 안 만든다:
    #   `sale_price` 는 비울 수 없는 칸이라 0 을 넣게 되는데 0 은 지어낸 가격이다.
    price = _price_for(session, set_id=set_id, market=market)
    if not price or price <= 0:
        raise DraftIncomplete(
            '판매가를 계산하지 못했습니다 — 정책의 판매가 규칙과 소싱처 원가(최종매입가)가 '
            '둘 다 있어야 합니다. 없는 값을 0원으로 지어내지 않습니다.')

    # 구성 하나 = 초안 하나. `source_url` 에 구성 번호를 적어 두어 되찾는다
    #   (ProductDraft 에 set_id 칸이 없다 — 칸을 늘리는 대신 이미 있는 칸을 쓴다).
    tag = f'set:{set_id}'
    d = (session.query(ProductDraft)
         .filter(ProductDraft.origin == ORIGIN, ProductDraft.source_url == tag,
                 ProductDraft.deleted_at.is_(None)).first())
    if d is None:
        d = ProductDraft(origin=ORIGIN, source_url=tag, status='draft',
                         sale_price=price)
        session.add(d)
    d.sale_price = price

    d.model_code = ps.model_code
    d.name = getattr(view, 'name', '') or ''
    d.brand = getattr(view, 'brand', '') or ''
    d.options_json = getattr(view, 'options_json', '[]')
    d.detail_html = getattr(view, 'detail_html', '') or ''
    d.source_site = ''                      # 구성은 소싱처가 여럿이라 한 곳을 못 적는다
    d.source_category_path = (m.category if m else '') or ''

    # 🔴 아래 칸들은 **비워 둔다** — 구성에 아직 없는 값이다.
    #   지어내면 가짜 전화번호·빈 고시가 마켓에 게시된다. preflight 가 무엇이
    #   없는지 정확히 말해 주는 것이 옳은 답이다.
    #   (images_json · cdn_images_json · notice_json · after_service_* · origin_area_code)
    session.flush()
    return d


def _empty(raw) -> bool:
    """안 채운 칸인가. `'{}'`·`'[]'`·`'null'` 도 **비어 있는 것**이다.

    ★ 기본값이 `'{}'` 이라 문자열 유무만 보면 「고시정보 있음」으로 잘못 읽는다(실측).
    """
    if not (raw or '').strip():
        return True
    try:
        return not json.loads(raw)
    except (TypeError, ValueError):
        return False        # 깨진 값 — 비었다고 하지 않는다(다시 저장하라고 해야 한다)


def missing_fields(draft) -> list[str]:
    """이 초안이 신규 등록에 **아직 못 채운 칸** — 사람 말로.

    preflight 가 마켓별로 더 정확히 말해 주지만, 그 전에 「구성에 아예 없는 것」을
    먼저 알려 주면 사장님이 어디를 손볼지 바로 안다.
    """
    out = []
    if not (draft.sale_price or 0) > 0:
        out.append('판매가(정책·원가가 있어야 계산됩니다)')
    if _empty(draft.cdn_images_json) and _empty(draft.images_json):
        out.append('상품 이미지')
    if not (draft.detail_html or '').strip():
        out.append('상세설명')
    # 🔴 `notice_json` 기본값이 `'{}'` 이다 — 문자열 유무만 보면 「고시정보 있음」으로
    #   잘못 읽어 **없는데 있다고** 말한다(실측으로 걸렸다).
    if _empty(draft.notice_json):
        out.append('고시정보')
    if not (draft.after_service_phone or '').strip():
        out.append('A/S 전화번호')
    return out
