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
    # [2026-08-13 2단계] 정책이 만든 운영값을 초안으로 옮긴다 —
    #   여기가 끊겨 있어 상품 칸 기본값(3,000·5,000·국내산)이 그대로 마켓에 나갔다.
    for k, v in policy_fields_from(view).items():
        setattr(d, k, v)
    d.source_site = ''                      # 구성은 소싱처가 여럿이라 한 곳을 못 적는다
    d.source_category_path = (m.category if m else '') or ''

    # ── A/S — 회사에 하나뿐인 값이라 전역 설정에서 가져온다 (사장님 확정 A안) ──
    #   🔴 **없으면 비워 둔다.** 예전 모음전 코드는 `or "02-0000-0000"` 로 때웠는데
    #     그건 가짜 번호를 실제 판매 상품에 게시하는 것이다. 비면 preflight 가 막는다.
    from lemouton.pricing.settings import get_settings
    g = get_settings(session)
    d.after_service_phone = (getattr(g, 'after_service_phone', None) or '') if g else ''
    d.after_service_guide = (getattr(g, 'after_service_guide', None) or '') if g else ''

    # ── 이미지 — 소싱처 크롤이 이미 받아 둔 옵션 사진을 **전부** 싣는다 (확정 A안) ──
    #   첫 장이 대표가 된다. 한 장만 싣던 안(C)은 흰색을 산 손님이 검정 사진을 보게 된다.
    #   🔴 새로 만들지 않는다 — 여기 담는 것은 **공개 주소**뿐이고, 스스가 요구하는
    #     네이버 CDN 으로 옮기는 일은 등록 직전 `image_prep.prepare_cdn_images` 가
    #     LIVE 게이트 뒤에서 한다(그게 이미 있는 경로다).
    d.images_json = json.dumps(option_images(session, set_id), ensure_ascii=False)

    # 🔴 고시정보(notice_json)는 **여기서 채우지 않는다** — 전역·소싱처별 기본값을
    #   `notice_defaults.apply_notice_defaults` 가 **컴파일 직전에** 병합한다.
    #   미리 써 넣으면 「사장님이 넣은 값」과 「기본값이 채운 값」이 뭉개진다.
    session.flush()
    return d


#: 정책이 만든 운영값 → 초안 칸. 값 이름이 같아 그대로 옮긴다.
#:   🔴 여기 있는 칸만 옮긴다. 사본에는 화면용 값(source_category_path 등)도 있어
#:     통째로 옮기면 초안에 엉뚱한 값이 박힌다.
#:
#: 🔴🔴 **모음전은 사본을 그대로 컴파일하지 않는다.** 사본을 초안 행에 옮겨 담고
#:   그 행을 컴파일한다(`send/runner.py:272` → `upsert` → `register_draft`).
#:   그래서 사본에만 실린 값은 **이 목록에 없으면 조용히 사라진다** —
#:   대량등록에서는 되는데 모음전에서만 안 되는 얼굴을 한다.
#:   값을 새로 이었으면 여기에도 넣었는지 반드시 확인할 것.
_POLICY_FIELDS = ('delivery_fee', 'return_fee', 'origin_area_code',
                  'minor_purchasable', 'tax_type', 'manufacturer',
                  'auto_pricing_min')


def policy_fields_from(view) -> dict:
    """사본에서 초안으로 옮길 운영값만 골라낸다.

    🔴 **정책이 값을 만들었을 때만 옮긴다.** 정책이 말하지 않은 칸을 건드리면
      상품에 저장된 값(또는 기본값)을 지우게 된다 — 배송비를 지우면 빈 칸이
      「무료배송」으로 읽혀 그 돈을 우리가 떠안는다.

    🔴 **0 은 값이다.** 배송비 0 = 무료배송이라, `if v` 로 거르면 무료배송이
      유료로 나간다. `None`·빈 문자열만 「안 정함」으로 본다.
    """
    out = {}
    for k in _POLICY_FIELDS:
        v = getattr(view, k, None)
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        out[k] = v
    return out


def option_images(session, set_id: int) -> list:
    """구성에 담긴 옵션들의 사진 주소 — 순서대로, 중복 없이.

    🔴 [2026-08-13] **공개 이름이다** — 정책 사본(policy/to_payload.set_view)도 같은
      함수를 쓴다. 여기서만 고치면 「사본이 본 사진」과 「초안에 실리는 사진」이 갈린다.

    ★ 첫 장이 대표가 된다. 구성이 정한 옵션 순서를 그대로 따르므로, 대표로 쓸
      사진을 바꾸려면 옵션 순서를 바꾸면 된다.
    ★ 같은 색의 여러 사이즈가 같은 사진을 가리키는 일이 흔하다 — 중복은 뺀다
      (마켓은 같은 사진을 여러 장으로 받으면 거부하거나 그대로 중복 노출한다).
    """
    from lemouton.sets.models import SetOption, SetProduct
    from lemouton.sourcing.models import Option

    skus = [r[0] for r in
            session.query(SetOption.canonical_sku)
            .join(SetProduct, SetProduct.id == SetOption.set_product_id)
            .filter(SetProduct.set_id == set_id)
            .order_by(SetOption.sort_order, SetOption.id).all()]
    if not skus:
        return []
    by_sku = {o.canonical_sku: o for o in
              session.query(Option).filter(Option.canonical_sku.in_(skus)).all()}
    out, seen = [], set()
    for sku in skus:                        # 구성이 정한 순서를 지킨다
        o = by_sku.get(sku)
        url = (getattr(o, 'image_url', '') or '').strip() if o else ''
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _loads_ok(raw):
    """저장된 JSON → 파이썬 값. 못 읽으면 빈 목록(테스트·화면이 같이 쓴다)."""
    try:
        v = json.loads(raw or '[]')
        return v if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


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
