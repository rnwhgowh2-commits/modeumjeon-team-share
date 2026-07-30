"""정책 규칙 — 만들기 · 값 저장 · 상품에 붙이기 · 채움 현황.

🔴 **비어 있는 값은 「안 정함」이지 0 이 아니다.**
   수수료율이 비었는데 0 으로 읽으면 마진이 부풀어 그대로 마켓에 나간다.
   그래서 `values_for()` 는 빈 값을 아예 돌려주지 않고, `readiness()` 가
   「아직 못 쓴다」를 명시적으로 알려준다. 가격 계산에 물리는 것은
   **필수 항목이 다 채워진 뒤**다(현재 미배선 — 채워지면 그때 연결).
"""
from __future__ import annotations

from sqlalchemy import select

from lemouton.policy.fields import MARKET_KEYS, all_field_keys, fields_for
from lemouton.policy.models import BundlePolicyLink, MarketPolicy, MarketPolicyValue

# 가격 계산에 물리려면 반드시 있어야 하는 항목 — 하나라도 비면 계산에 안 쓴다.
PRICE_REQUIRED = ('fee_rate', 'margin_rate')


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


def save_values(session, *, policy: MarketPolicy, market: str,
                values: dict) -> int:
    """한 마켓의 항목값을 저장한다. 빈 문자열은 「안 정함」으로 되돌린다."""
    if market not in MARKET_KEYS:
        raise PolicyError(f'모르는 마켓이에요: {market}')
    known = all_field_keys()
    bad = [k for k in values if k not in known]
    if bad:
        raise PolicyError(f'모르는 항목이에요: {", ".join(bad[:5])}')
    cur = {v.field_key: v for v in session.scalars(select(MarketPolicyValue).where(
        MarketPolicyValue.policy_id == policy.id, MarketPolicyValue.market == market))}
    n = 0
    for k, raw in values.items():
        v = (str(raw).strip() if raw is not None else '')
        row = cur.get(k)
        if not v:
            if row is not None:
                session.delete(row)     # 비우면 「안 정함」 — 0 으로 남기지 않는다
                n += 1
            continue
        if row is None:
            session.add(MarketPolicyValue(policy_id=policy.id, market=market,
                                          field_key=k, value=v))
            n += 1
        elif row.value != v:
            row.value = v
            n += 1
    session.flush()
    return n


def values_for(session, policy_id: int, market: str) -> dict:
    """채워진 값만. 비어 있는 항목은 **키 자체가 없다**(0 으로 오해 금지)."""
    return {v.field_key: v.value for v in session.scalars(select(MarketPolicyValue).where(
        MarketPolicyValue.policy_id == policy_id, MarketPolicyValue.market == market))}


def readiness(session, policy_id: int) -> dict:
    """마켓별 채움 현황 — {market: {filled, total, price_ready, missing:[...]}}.

    price_ready=False 면 그 마켓 가격 계산에 이 정책을 쓰면 안 된다.
    """
    out = {}
    for mk in MARKET_KEYS:
        got = values_for(session, policy_id, mk)
        total = sum(len(g['fields']) for g in fields_for(mk))
        missing = [k for k in PRICE_REQUIRED if not got.get(k)]
        out[mk] = {'filled': len(got), 'total': total,
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
