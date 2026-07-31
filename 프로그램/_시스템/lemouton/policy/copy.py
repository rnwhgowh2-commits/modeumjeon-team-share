# -*- coding: utf-8 -*-
"""정책 복사 — 노션 「생성된 정책 복사기능」.

「한가지 상품에도 여러 정책으로 정책별로 가공하여 마켓에 업로드 가능」이 목적이다.

🔴 **붙은 상품은 복사하지 않는다.** 상품 하나에 정책 하나라, 복사본이 같은 상품을
   가져가면 원본에서 조용히 떨어진다.
🔴 **기본 정책 표시도 따라오지 않는다.** 기본은 하나뿐이라, 복사가 기본을 가져가면
   원본이 기본에서 밀린다.
"""
from __future__ import annotations

from sqlalchemy import select

from lemouton.policy.models import MarketPolicy, MarketPolicyValue
from lemouton.policy.service import PolicyError


def _free_name(session, base: str) -> str:
    """「… (복사)」, 그것도 있으면 「… (복사 2)」."""
    taken = set(session.scalars(select(MarketPolicy.name).where(
        MarketPolicy.deleted_at.is_(None))))
    cand = f'{base} (복사)'
    if cand not in taken:
        return cand
    n = 2
    while f'{base} (복사 {n})' in taken:
        n += 1
    return f'{base} (복사 {n})'


def copy_policy(session, *, policy: MarketPolicy, name: str = '') -> MarketPolicy:
    """정책과 그 값 전부를 복사한다. 붙은 상품·기본 표시는 따라오지 않는다."""
    want = (name or '').strip()
    if want:
        dup = session.scalar(select(MarketPolicy).where(
            MarketPolicy.name == want, MarketPolicy.deleted_at.is_(None)))
        if dup is not None:
            raise PolicyError(f'「{want}」 이름의 정책이 이미 있어요.')
    else:
        want = _free_name(session, policy.name)

    new = MarketPolicy(name=want, memo=policy.memo, is_default=0,
                       brand=getattr(policy, 'brand', None),
                       enabled_markets=getattr(policy, 'enabled_markets', None))
    session.add(new)
    session.flush()

    # 「공통에서 받았다」는 표시(from_common_at)도 같이 옮긴다 —
    #   복사본에서 「직접 고침」으로 잘못 뜨면 사장님이 다시 불러오게 된다.
    for v in session.scalars(select(MarketPolicyValue).where(
            MarketPolicyValue.policy_id == policy.id)):
        session.add(MarketPolicyValue(
            policy_id=new.id, market=v.market, field_key=v.field_key,
            value=v.value, from_common_at=v.from_common_at))
    session.flush()
    return new
