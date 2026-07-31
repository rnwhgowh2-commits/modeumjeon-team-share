"""정책 규칙 — 만들기 · 항목값 저장 · 상품에 붙이기 · 채움 현황.

값은 **항목 하나당 설정 묶음 하나**로 저장한다(`field_key=item_key`, `value=JSON`).
항목 정의는 대량등록 가공 규칙 13항목을 그대로 쓴다 — lemouton/policy/fields.py 주석 참조.

🔴 **저장하지 않은 항목은 「아직 안 정함」이다.**
   화면이 기본값을 보여주더라도, 사장님이 저장하지 않았으면 정해진 것이 아니다.
   `values_for()` 는 저장된 항목만 돌려주고, `readiness()` 가 「가격 아직 못 씀」을 알린다.
   가격 계산에 물리는 것은 「판매가」 항목이 저장된 뒤다(현재 미배선).
"""
from __future__ import annotations

import json

from sqlalchemy import select

from lemouton.policy.fields import (
    COMMON_KEY, MARKET_KEYS, PRICE_REQUIRED_ITEMS, all_item_keys, item_keys_for,
)
from lemouton.policy.models import BundlePolicyLink, MarketPolicy, MarketPolicyValue


class PolicyError(Exception):
    """사용자에게 그대로 보여줄 수 있는 실패 사유."""


def create_policy(session, *, name: str, memo: str = '') -> MarketPolicy:
    name = (name or '').strip()
    if not name:
        raise PolicyError('정책 이름을 넣어 주세요.')
    dup = session.scalar(select(MarketPolicy).where(
        MarketPolicy.name == name, MarketPolicy.deleted_at.is_(None)))
    if dup is not None:
        raise PolicyError(f'「{name}」 이름의 정책이 이미 있어요.')
    p = MarketPolicy(name=name, memo=(memo or '').strip() or None)
    session.add(p)
    session.flush()
    return p


def save_item(session, *, policy: MarketPolicy, market: str,
              item_key: str, config: dict) -> None:
    """항목 하나의 설정을 저장한다. config 가 비면 「안 정함」으로 되돌린다."""
    # 「마켓 공통」도 값을 담는 자리다 — 마켓은 아니지만 저장은 여기로 들어온다.
    if market not in MARKET_KEYS and market != COMMON_KEY:
        raise PolicyError(f'모르는 마켓이에요: {market}')
    if item_key not in all_item_keys():
        raise PolicyError(f'모르는 항목이에요: {item_key}')
    row = session.scalar(select(MarketPolicyValue).where(
        MarketPolicyValue.policy_id == policy.id,
        MarketPolicyValue.market == market,
        MarketPolicyValue.field_key == item_key))
    if not config:
        if row is not None:
            session.delete(row)     # 비우면 「안 정함」 — 0 으로 남기지 않는다
        session.flush()
        return
    body = json.dumps(config, ensure_ascii=False)
    if row is None:
        session.add(MarketPolicyValue(policy_id=policy.id, market=market,
                                      field_key=item_key, value=body))
    else:
        row.value = body
        # 화면에서 직접 저장한 값은 「공통에서 받은 값」이 아니다.
        row.from_common_at = None
    session.flush()


def save_values(session, *, policy: MarketPolicy, market: str, values: dict) -> int:
    """여러 항목을 한 번에. {item_key: config dict}. 바뀐 항목 수를 돌려준다."""
    before = values_for(session, policy.id, market)
    for k, cfg in (values or {}).items():
        save_item(session, policy=policy, market=market, item_key=k,
                  config=dict(cfg or {}))
    after = values_for(session, policy.id, market)
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    return len(changed)


def values_for(session, policy_id: int, market: str) -> dict:
    """저장된 항목만. {item_key: config dict}. 안 정한 항목은 **키 자체가 없다**."""
    out = {}
    for v in session.scalars(select(MarketPolicyValue).where(
            MarketPolicyValue.policy_id == policy_id,
            MarketPolicyValue.market == market)):
        try:
            out[v.field_key] = json.loads(v.value) if v.value else {}
        except (TypeError, ValueError):
            out[v.field_key] = {}       # 깨진 값은 「안 정함」처럼 취급(조용히 쓰지 않는다)
    return out


def readiness(session, policy_id: int) -> dict:
    """마켓별 채움 현황 — {market: {filled, total, price_ready, missing:[...]}}.

    price_ready=False 면 그 마켓 가격 계산에 이 정책을 쓰면 안 된다.
    """
    out = {}
    for mk in MARKET_KEYS:
        got = values_for(session, policy_id, mk)
        keys = item_keys_for(mk)
        missing = [k for k in PRICE_REQUIRED_ITEMS if not got.get(k)]
        out[mk] = {'filled': len([k for k in keys if got.get(k)]),
                   'total': len(keys),
                   'price_ready': not missing, 'missing': missing}
    return out


def apply_to(session, *, policy: MarketPolicy, model_codes: list[str]) -> int:
    """상품들에 정책을 붙인다(노션 「그룹핑 — 체크 후 적용」). 이미 붙어 있으면 갈아끼운다."""
    codes = [c for c in dict.fromkeys(model_codes or []) if c]
    if not codes:
        raise PolicyError('적용할 상품을 하나도 고르지 않았어요.')
    from lemouton.sourcing.models import Model
    known = set(session.scalars(select(Model.model_code).where(
        Model.model_code.in_(codes))))
    unknown = [c for c in codes if c not in known]
    if unknown:
        raise PolicyError(f'없는 상품이 섞여 있어요: {", ".join(unknown[:5])}')
    cur = {l.model_code: l for l in session.scalars(select(BundlePolicyLink).where(
        BundlePolicyLink.model_code.in_(codes)))}
    for c in codes:
        row = cur.get(c)
        if row is None:
            session.add(BundlePolicyLink(model_code=c, policy_id=policy.id))
        else:
            row.policy_id = policy.id
    session.flush()
    return len(codes)


def policy_of(session, model_code: str) -> MarketPolicy | None:
    link = session.get(BundlePolicyLink, model_code)
    if link is None:
        return None
    p = session.get(MarketPolicy, link.policy_id)
    return p if p is not None and p.deleted_at is None else None


def set_default(session, *, policy: MarketPolicy) -> None:
    """기본 정책은 하나뿐 — 새로 지정하면 이전 것은 풀린다."""
    for p in session.scalars(select(MarketPolicy).where(MarketPolicy.is_default == 1)):
        p.is_default = 0
    policy.is_default = 1
    session.flush()


def applied_count(session, policy_id: int) -> int:
    from sqlalchemy import func
    return session.query(func.count()).select_from(BundlePolicyLink).filter(
        BundlePolicyLink.policy_id == policy_id).scalar() or 0
