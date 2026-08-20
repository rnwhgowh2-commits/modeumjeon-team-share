# -*- coding: utf-8 -*-
"""「구성」 — 상품 하나가 마켓에 나가는 **한 벌**. 정책이 붙는 단위.

■ 화면에서 부르는 말 = **「구성」** (2026-08-02 사장님 확정)
  작업 중에는 「벌」이라 부르다가, 프로그램이 이미 「구성」(구성 만들기·구성 목록·구성명)을
  쓰고 있어 그리로 통일했다. **화면 문구에 「벌」을 다시 쓰지 말 것** — 사장님이 두 가지
  말을 외워야 한다. 코드 이름(`ProductSet`·`set_id`)은 그대로 둔다.

■ 무엇인가
  「한 상품에 정책 여러 개」 = 같은 상품을 정책마다 다르게 가공해 **같은 마켓에 각각** 올리기.
  그 단위는 이미 집에 있었다 — **구성(ProductSet)** 이다.

  🔴 구성을 가르는 건 **정책**이지 「단품/세트」가 아니다.
     단품+단품 · 세트+세트 · 단품+세트 무엇이든 된다. 그래서 구성 이름이 같아도 값이 갈린다.

■ 왜 한 구성이 마켓 상품 하나인가
  `SetChannel` 에 `UNIQUE(set_id, market, account_key)` 가 걸려 있다. 한 구성은
  한 마켓·한 계정에 상품을 **하나만** 올릴 수 있다. 그러니 마켓에 두 개를 올리려면
  구성이 둘이어야 한다. 「단품, 단품」이면 구성을 2개 만든다.

■ 재고
  나누지 않는다(사장님 확정 「데이터 연동」). `reconcile.market_targets_for(sku)` 가
  그 옵션이 걸린 **모든** 구성·마켓을 돌려주므로, 구성이 둘이면 둘 다에 같은 재고가 나가고
  하나 팔리면 다음 사이클에 둘 다 같이 준다. 이미 그렇게 돌고 있다.
"""
from __future__ import annotations


def bundles_of(session, model_codes: list[str]) -> dict[str, list[dict]]:
    """{상품코드: [벌…]} — 화면 목록이 한 번에 읽어 가는 모양.

    벌 = {set_id, name(구성 이름·보조), policy_id, policy_name}
    구성이 없는 상품은 빈 목록이다(아직 마켓에 안 나가는 상품 — 라이브 90개 중 89개).
    """
    from lemouton.policy.models import MarketPolicy, SetPolicyLink
    from lemouton.sets.models import ProductSet

    if not model_codes:
        return {}
    sets = (session.query(ProductSet)
            .filter(ProductSet.model_code.in_(model_codes),
                    ProductSet.is_active.is_(True))
            .order_by(ProductSet.id).all())
    if not sets:
        return {}
    links = dict(session.query(SetPolicyLink.set_id, SetPolicyLink.policy_id)
                 .filter(SetPolicyLink.set_id.in_([x.id for x in sets])).all())
    names = dict(session.query(MarketPolicy.id, MarketPolicy.name)
                 .filter(MarketPolicy.deleted_at.is_(None)).all())
    out: dict[str, list[dict]] = {}
    for ps in sets:
        pid = links.get(ps.id)
        out.setdefault(ps.model_code, []).append({
            'set_id': ps.id, 'name': ps.name,
            'policy_id': pid, 'policy': names.get(pid)})
    return out


def attach_to_sets(session, *, policy_id: int, set_ids: list[int]) -> int:
    """고른 **벌들**에 정책을 붙인다(갈아 끼움). 붙인 개수를 돌려준다."""
    from lemouton.policy.models import MarketPolicy, SetPolicyLink
    from lemouton.policy.service import PolicyError
    from lemouton.sets.models import ProductSet

    ids = [int(x) for x in (set_ids or [])]
    if not ids:
        return 0
    if session.get(MarketPolicy, policy_id) is None:
        raise PolicyError('정책을 찾을 수 없어요.')
    live = {x.id for x in session.query(ProductSet).filter(ProductSet.id.in_(ids)).all()}
    missing = [i for i in ids if i not in live]
    if missing:
        raise PolicyError(f'없는 벌이 있어요: {missing[:3]}')

    n = 0
    for sid in ids:
        link = session.get(SetPolicyLink, sid)
        if link is None:
            session.add(SetPolicyLink(set_id=sid, policy_id=policy_id))
        else:
            link.policy_id = policy_id
        n += 1
    session.flush()
    return n


def add_bundle(session, *, model_code: str, policy_id: int,
               copy_from_set_id: int | None = None, name: str = '') -> dict:
    """이 상품에 **벌을 하나 더** 만든다 — 「정책 하나 더 붙이기」의 실체.

    Args:
        copy_from_set_id: 옵션을 그대로 베껴 올 벌. None 이면 **지금 있는 첫 벌**을 벤다.
                          벌이 하나도 없으면 빈 벌을 만든다(옵션은 나중에 고른다).
        name: 벌 이름. 비우면 **정책 이름**으로 부른다(사장님 확정 — 벌은 정책이 가른다).

    🔴 옵션을 베끼지 않으면 새 벌은 **아무것도 안 담긴 채** 만들어져 마켓에 못 올라간다.
      화면 기본값이 「지금 벌과 똑같이」인 이유다.
    """
    from lemouton.policy.models import MarketPolicy, SetPolicyLink
    from lemouton.policy.service import PolicyError
    from lemouton.sets.models import ProductSet, SetOption, SetProduct
    from lemouton.sourcing.models import Model

    if session.get(Model, model_code) is None:
        raise PolicyError('상품을 찾을 수 없어요.')
    pol = session.get(MarketPolicy, policy_id)
    if pol is None or pol.deleted_at is not None:
        raise PolicyError('정책을 찾을 수 없어요.')

    mine = (session.query(ProductSet)
            .filter_by(model_code=model_code, is_active=True)
            .order_by(ProductSet.id).all())
    src = None
    if copy_from_set_id:
        src = next((x for x in mine if x.id == copy_from_set_id), None)
        if src is None:
            raise PolicyError('베껴 올 벌을 찾을 수 없어요.')
    elif mine:
        src = mine[0]

    ps = ProductSet(model_code=model_code, name=(name or pol.name).strip()[:255])
    session.add(ps)
    session.flush()

    copied = 0
    if src is not None:
        for sp in session.query(SetProduct).filter_by(set_id=src.id).all():
            new_sp = SetProduct(set_id=ps.id, model_code=sp.model_code,
                                quantity=sp.quantity)
            session.add(new_sp)
            session.flush()
            for so in (session.query(SetOption)
                       .filter_by(set_product_id=sp.id)
                       .order_by(SetOption.sort_order).all()):
                session.add(SetOption(set_product_id=new_sp.id,
                                      canonical_sku=so.canonical_sku,
                                      sort_order=so.sort_order))
                copied += 1

    session.add(SetPolicyLink(set_id=ps.id, policy_id=policy_id))
    session.flush()
    return {'set_id': ps.id, 'name': ps.name, 'policy': pol.name,
            'copied_options': copied, 'copied_from': (src.id if src else None)}
