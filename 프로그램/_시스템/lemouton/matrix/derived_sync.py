# -*- coding: utf-8 -*-
"""원본 묶음 ↔ 거기서 만든 상품의 소싱처 연결 맞추기. 설계서 규칙 3.

🔴 왜 필요한가 — 상품을 만들 때 옵션을 **복사**한다(PR#545). 프로그램 전체가
   「옵션은 상품 하나에 매달린다」를 전제로 돌아서, 참조로 두면 새 상품이 조용히
   전송에서 빠지기 때문이다. 그런데 복사한 뒤 원본에서 소싱처를 고치면
   **이미 만든 상품에는 안 내려간다.** 같은 「블랙 265」인데 상품마다 다른
   소싱처를 보게 되고 **가격·재고가 갈린다.**

   규칙 3 — 「원본에서 고치면 그 옵션을 쓰는 **모든 상품에 즉시 반영**된다.」
   복사 구조를 유지한 채 그 규칙을 지키려면 **원본 → 복사본으로 내려보내야** 한다.

🔴 짝은 **축 값**(색상·사이즈)으로 짓는다 — 열쇠(`canonical_sku`)는 복사하며
   새로 발급되므로 짝짓기에 쓸 수 없다.

🔴 원본이 진실이다 — 상품에만 남은 옛 연결은 뗀다. 그게 「옛 주소를 계속 보는」 상태다.
🔴 짝을 못 찾으면 **손대지 않고 그대로 알린다**(unmatched). 지어내지 않는다.
"""
from __future__ import annotations


def axis_key(option) -> tuple:
    """옵션 짝짓기 키 — 축 값들."""
    from lemouton.sourcing.option_combo import option_axis_values
    return tuple(str(v).strip() for v in option_axis_values(option))


def plan_sync(origin_by_key: dict, made: dict) -> dict:
    """무엇을 더하고 뗄지만 정한다(DB 안 건드림).

    Args:
        origin_by_key: {축키: {source_option_id, ...}}  — 원본이 가진 연결
        made: {canonical_sku: (축키, {source_option_id, ...})} — 상품의 옵션

    Returns:
        {'add': [(sku, source_option_id)...], 'remove': [...], 'unmatched': [sku...]}
    """
    add: list[tuple[str, int]] = []
    remove: list[tuple[str, int]] = []
    unmatched: list[str] = []
    for sku, (key, have) in sorted(made.items()):
        want = origin_by_key.get(key)
        if want is None:
            unmatched.append(sku)          # 원본에 없는 옵션 — 손대지 않는다
            continue
        for sid in sorted(want - have):
            add.append((sku, sid))
        for sid in sorted(have - want):
            remove.append((sku, sid))
    return {'add': add, 'remove': remove, 'unmatched': sorted(unmatched)}


def _origin_map(session, matrix):
    """원본 묶음의 {축키: {소싱처 연결}}."""
    from lemouton.sources.models import OptionSourceLink
    from lemouton.sourcing.models import Option
    opts = session.query(Option).filter_by(model_code=matrix.model_code).all()
    if not opts:
        return {}
    skus = [o.canonical_sku for o in opts]
    links: dict[str, set] = {}
    for sku, sid in (session.query(OptionSourceLink.canonical_sku,
                                   OptionSourceLink.source_option_id)
                     .filter(OptionSourceLink.canonical_sku.in_(skus)).all()):
        links.setdefault(sku, set()).add(sid)
    out: dict[tuple, set] = {}
    for o in opts:
        out.setdefault(axis_key(o), set()).update(links.get(o.canonical_sku, set()))
    return out


def check(session, *, apply: bool = False) -> dict:
    """원본에서 만든 상품들의 소싱처 연결이 원본과 같은지 본다.

    apply=False 면 **읽기만** 한다 — 무엇이 갈렸는지 먼저 눈으로 보고 나서 맞춘다.
    """
    from lemouton.matrix.models import BundleMatrixLink, MatrixOption
    from lemouton.sources.models import OptionSourceLink
    from lemouton.sourcing.models import Option

    total = {'products': 0, 'add': 0, 'remove': 0, 'unmatched': 0,
             'drifted_products': []}
    for link in session.query(BundleMatrixLink).all():
        mx = session.get(MatrixOption, link.matrix_option_id)
        if mx is None or not mx.model_code:
            continue
        if mx.model_code == link.model_code:
            continue                       # 원본 자신 — 맞출 것이 없다
        origin = _origin_map(session, mx)
        if not origin:
            continue

        opts = session.query(Option).filter_by(model_code=link.model_code).all()
        if not opts:
            continue
        skus = [o.canonical_sku for o in opts]
        have: dict[str, set] = {s: set() for s in skus}
        for sku, sid in (session.query(OptionSourceLink.canonical_sku,
                                       OptionSourceLink.source_option_id)
                         .filter(OptionSourceLink.canonical_sku.in_(skus)).all()):
            have[sku].add(sid)
        made = {o.canonical_sku: (axis_key(o), have[o.canonical_sku]) for o in opts}

        plan = plan_sync(origin, made)
        total['products'] += 1
        total['add'] += len(plan['add'])
        total['remove'] += len(plan['remove'])
        total['unmatched'] += len(plan['unmatched'])
        if plan['add'] or plan['remove']:
            total['drifted_products'].append(
                {'model_code': link.model_code, 'from': mx.display_no or mx.model_code,
                 'add': len(plan['add']), 'remove': len(plan['remove'])})

        if apply:
            for sku, sid in plan['add']:
                session.add(OptionSourceLink(canonical_sku=sku,
                                             source_option_id=sid))
            for sku, sid in plan['remove']:
                (session.query(OptionSourceLink)
                 .filter_by(canonical_sku=sku, source_option_id=sid)
                 .delete(synchronize_session=False))

    total['applied'] = bool(apply)
    return total
