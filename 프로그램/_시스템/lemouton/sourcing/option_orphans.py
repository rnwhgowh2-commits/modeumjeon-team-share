"""매트릭스 밖 옵션(유령) — 판정 · 목록 · 정리.

설계서 — docs/superpowers/specs/2026-08-02-옵션값-이름바꾸기-design.md

🔴 유령이란 — **지금 단계 설계(BundleOptionStep)의 어느 조합에도 해당하지 않는 옵션.**
   테스트 이름(`색상1`)으로 만들어 두고 이름을 고친 흔적, 축에서 값을 뺀 뒤 남은 것들이다.
   이 옵션들은 `is_active` 가 켜진 채 남아 **마켓에 그대로 올라갈 수 있었다**
   (판매 게이트는 `is_active`·`crawl_blocked` 만 본다 — uploader/preview.py).

🔴 DB 에 「유령」 칸을 만들지 않는다 — 축 값이 설계 안에 있나로 **그때그때 판정**한다.
   칸을 만들면 설계와 칸이 갈리고, 갈리면 어느 쪽이 맞는지 아무도 모른다.

🔴 설계가 없으면 아무것도 유령이라고 부르지 않는다 — 무엇이 밖인지 알 수 없기 때문이다.
   단정하지 않는 편이 팔리는 상품을 잘못 내리는 것보다 낫다.
"""
from __future__ import annotations

import json
import re

from .models import BundleOptionStep, Option
from .option_combo import generate_combinations, steps_from_rows

# 유령을 지우려 할 때 「걸린 데」로 볼 표 — options.canonical_sku 를 가리키는 모든 칸.
# 🔴 표 이름을 손으로 적지 않는다. 로컬 SQLite 는 FK 를 안 잡아 손으로 적은 목록의
#    누락이 테스트를 통과해 버리고, 라이브 PostgreSQL 에서만 터진다.
_LINK_TARGET = 'options.canonical_sku'


def axes_of(opt) -> tuple:
    """옵션의 축 값 — `axis_values_json` 우선, 없으면 옛 칸(color/size) 폴백."""
    try:
        vals = json.loads(getattr(opt, 'axis_values_json', None) or '[]')
        if vals:
            return tuple(vals)
    except (ValueError, TypeError):
        pass
    return tuple(v for v in [getattr(opt, 'color_code', '') or '',
                             getattr(opt, 'size_code', '') or ''] if v)


def design_axes(session, model_code: str) -> set[tuple] | None:
    """지금 단계 설계가 그리는 조합 전부. 설계가 없으면 None(= 판정 불가)."""
    rows = session.query(BundleOptionStep).filter_by(model_code=model_code).all()
    if not rows:
        return None
    steps = steps_from_rows(rows)
    combos = generate_combinations(steps)
    if not combos:
        return None
    return {tuple(c['values']) for c in combos}


def list_orphans(session, model_code: str) -> list[dict]:
    """매트릭스 밖 옵션 목록 — 화면이 그대로 그릴 수 있는 모양으로."""
    inside = design_axes(session, model_code)
    if inside is None:
        return []
    opts = [o for o in session.query(Option).filter_by(model_code=model_code).all()
            if axes_of(o) not in inside]
    if not opts:
        return []
    blocked = blockers(session, [o.canonical_sku for o in opts])
    out = []
    for o in sorted(opts, key=lambda x: (x.display_no or '', x.canonical_sku)):
        vals = list(axes_of(o))
        out.append({
            'canonical_sku': o.canonical_sku,
            'display_no': o.display_no,
            'axis_values': vals,
            'label': ' '.join(vals),
            'is_active': bool(o.is_active),
            'linked_to': blocked.get(o.canonical_sku, []),
            'deletable': not blocked.get(o.canonical_sku),
        })
    return out


def _link_columns():
    """`options.canonical_sku` 를 가리키는 (표, 칸) 전부 — metadata 에서 뽑는다."""
    from shared.db import Base
    out = []
    for table in Base.metadata.tables.values():
        if table.name == 'options':
            continue
        for col in table.columns:
            for fk in col.foreign_keys:
                if str(fk.target_fullname) == _LINK_TARGET:
                    out.append((table, col))
    return out


def blockers(session, skus) -> dict[str, list[str]]:
    """옵션마다 「걸린 데」 표 이름 목록. 빈 목록이면 지워도 되는 옵션."""
    from sqlalchemy import select

    wanted = [s for s in (skus or []) if s]
    if not wanted:
        return {}
    found: dict[str, list[str]] = {}
    # 🔴 자르는 크기는 `lemouton/matrix/readiness._CHUNK` **한 곳에서만** 정한다.
    #    예전엔 여기에 500 을 또 적어 뒀는데, 같은 숫자가 두 곳에 살면 한쪽만 고쳐졌을
    #    때 그쪽만 계속 터진다. 진짜 한도가 얼마인지와 「그런데 왜 그보다 훨씬 작게
    #    자르는지」도 그 옆에 실측과 함께 적혀 있다 — 여기 옮겨 적지 않는다.
    #    🔴 값은 함수 안에서 읽는다(맨 위에서 당겨 오면 값이 굳어 저쪽을 고쳐도 안 따라온다).
    #    `audit_all` 이 **전 상품 유령을 한꺼번에** 넘기므로 자르기가 실제로 필요하다.
    from lemouton.matrix.readiness import _CHUNK
    for table, col in _link_columns():
        for i in range(0, len(wanted), _CHUNK):
            rows = session.execute(select(col).where(
                col.in_(wanted[i:i + _CHUNK])).distinct()).scalars().all()
            for sku in rows:
                if sku:
                    found.setdefault(sku, []).append(table.name)
    return found


def audit_all(session, *, limit_bundles: int | None = None) -> dict:
    """**전 상품 전수 조사** — 어느 상품에 유령이 몇 개 있나.

    한 상품씩 묻지 않는다. 한 번에 훑어야 「전수」라고 말할 수 있다.
    설계가 없는 상품은 판정 불가라 **아예 세지 않는다**(없다고 단정하지 않는다).

    Returns:
        {'bundles_scanned', 'bundles_without_design', 'bundles_with_orphans',
         'orphans', 'orphans_selling', 'orphans_deletable', 'items': [...]}
    """
    from lemouton.sourcing.models import Model

    steps_by_code: dict[str, list] = {}
    for r in session.query(BundleOptionStep).all():
        steps_by_code.setdefault(r.model_code, []).append(r)

    names = dict(session.query(Model.model_code, Model.model_name_display).all())
    raw = dict(session.query(Model.model_code, Model.model_name_raw).all())

    opts_by_code: dict[str, list] = {}
    for o in session.query(Option).all():
        opts_by_code.setdefault(o.model_code, []).append(o)

    all_codes = set(opts_by_code)
    no_design = sorted(c for c in all_codes if c not in steps_by_code)

    found: list[tuple[str, list]] = []
    scanned = 0
    for code in sorted(steps_by_code):
        if code not in opts_by_code:
            continue
        combos = generate_combinations(steps_from_rows(steps_by_code[code]))
        if not combos:
            continue                      # 값 없는 축 — 판정 불가
        scanned += 1
        inside = {tuple(c['values']) for c in combos}
        ghosts = [o for o in opts_by_code[code] if axes_of(o) not in inside]
        if ghosts:
            found.append((code, ghosts))
        if limit_bundles and len(found) >= limit_bundles:
            break

    blocked = blockers(session, [o.canonical_sku for _c, gs in found for o in gs])

    items = []
    for code, ghosts in found:
        items.append({
            'model_code': code,
            'name': names.get(code) or raw.get(code) or code,
            'options': len(opts_by_code[code]),
            'orphans': len(ghosts),
            'selling': sum(1 for o in ghosts if o.is_active),
            'deletable': sum(1 for o in ghosts if not blocked.get(o.canonical_sku)),
            'labels': [' '.join(axes_of(o)) for o in ghosts[:8]],
        })
    items.sort(key=lambda x: (-x['selling'], -x['orphans'], x['model_code']))

    total = sum(i['orphans'] for i in items)
    return {
        'bundles_scanned': scanned,
        'bundles_without_design': len(no_design),
        'bundles_with_orphans': len(items),
        'orphans': total,
        'orphans_selling': sum(i['selling'] for i in items),
        'orphans_deletable': sum(i['deletable'] for i in items),
        'items': items,
    }


# 「테스트로 만들어 두고 안 지운 것」으로 보이는 값 — 이름만으로 의심하는 규칙.
#   🔴 설계(BundleOptionStep)가 없는 상품이 대부분이라, 매트릭스 대조만으로는
#      아무것도 판정할 수 없다. 이름은 판정이 아니라 **눈에 띄게 하는 그물**이다.
#      여기 걸렸다고 지우지 않는다 — 사람이 보고 정한다.
_SUSPECT = re.compile(
    r'(?:^|[\s_\-])(?:색상|사이즈|옵션|컬러)\s*\d+$'      # 색상1 · 사이즈2 · 옵션 3
    r'|^(?:색상|사이즈|옵션|컬러)\s*\d+$'
    r'|테스트|검증색|임시|샘플'
    r'|\b(?:test|tmp|temp|sample|dummy|asdf|qwer)\b',
    re.IGNORECASE)


def scan_suspicious_values(session) -> dict:
    """전 상품 — 값 이름이 테스트처럼 보이는 옵션 훑기(설계 유무와 무관).

    설계가 없는 상품은 매트릭스 대조가 불가능하므로 이 그물로 따로 본다.
    """
    from lemouton.sourcing.models import Model

    names = dict(session.query(Model.model_code, Model.model_name_display).all())
    raw = dict(session.query(Model.model_code, Model.model_name_raw).all())

    hits: dict[str, list] = {}
    total_options = 0
    for o in session.query(Option).all():
        total_options += 1
        vals = axes_of(o)
        if any(_SUSPECT.search(str(v)) for v in vals):
            hits.setdefault(o.model_code, []).append(o)

    blocked = blockers(session, [o.canonical_sku for gs in hits.values() for o in gs])
    items = []
    for code, gs in hits.items():
        items.append({
            'model_code': code,
            'name': names.get(code) or raw.get(code) or code,
            'hits': len(gs),
            'selling': sum(1 for o in gs if o.is_active),
            'deletable': sum(1 for o in gs if not blocked.get(o.canonical_sku)),
            'labels': sorted({' '.join(axes_of(o)) for o in gs})[:10],
        })
    items.sort(key=lambda x: (-x['selling'], -x['hits'], x['model_code']))
    return {
        'options_total': total_options,
        'suspect_bundles': len(items),
        'suspect_options': sum(i['hits'] for i in items),
        'suspect_selling': sum(i['selling'] for i in items),
        'items': items,
    }


def purge(session, options) -> dict:
    """매트릭스 밖이 된 옵션을 **없던 것처럼** 치운다.

    사장님 확정(2026-08-02) — 「정정하면 기존 것은 사라지고 신규만 남는다.」
    묻지 않고, 버튼도 만들지 않는다. 다만 **기록이 걸린 것은 지우지 않는다** —
    지우면 그 옵션이 팔렸던 지난 주문·정산을 되짚을 수 없다. 그런 건 판매만 끈다.

    Returns:
        {'deleted': [sku], 'kept': [sku]}  — kept = 기록이 있어 판매만 끈 것
    """
    opts = list(options or [])
    if not opts:
        return {'deleted': [], 'kept': []}
    blocked = blockers(session, [o.canonical_sku for o in opts])
    deleted, kept = [], []
    for o in opts:
        if blocked.get(o.canonical_sku):
            if o.is_active:
                o.is_active = False
            kept.append(o.canonical_sku)
        else:
            deleted.append(o.canonical_sku)
            session.delete(o)
    session.flush()
    return {'deleted': deleted, 'kept': kept}


def resolve_orphans(session, model_code: str, skus, action: str = 'off') -> dict:
    """유령 정리 — `off`(판매 끄기) 또는 `delete`(안전 삭제).

    🔴 매트릭스 **안** 옵션은 이 창구로 건드리지 않는다(`refused`).
       팔리는 상품을 실수로 내리는 길을 아예 막는다.
    🔴 `delete` 라도 걸린 데가 있으면 지우지 않는다 — 끄고 `kept` 로 돌려준다.
       기록이 끊기면 지난 주문·정산을 되짚을 수 없다.
    """
    inside = design_axes(session, model_code)
    wanted = [s for s in dict.fromkeys(skus or []) if s]
    if not wanted:
        return {'turned_off': 0, 'deleted': 0, 'kept': [], 'refused': []}

    opts = (session.query(Option)
            .filter(Option.model_code == model_code,
                    Option.canonical_sku.in_(wanted)).all())
    by_sku = {o.canonical_sku: o for o in opts}

    targets, refused = [], []
    for sku in wanted:
        o = by_sku.get(sku)
        if o is None or inside is None or axes_of(o) in inside:
            refused.append(sku)
        else:
            targets.append(o)

    kept: list[str] = []
    turned_off = 0
    deleted = 0
    blocked = blockers(session, [o.canonical_sku for o in targets]) \
        if action == 'delete' else {}

    for o in targets:
        if action == 'delete' and not blocked.get(o.canonical_sku):
            session.delete(o)
            deleted += 1
            continue
        if action == 'delete':
            kept.append(o.canonical_sku)
        if o.is_active:
            o.is_active = False
        turned_off += 1
    session.commit()
    return {'turned_off': turned_off, 'deleted': deleted,
            'kept': kept, 'refused': refused}
