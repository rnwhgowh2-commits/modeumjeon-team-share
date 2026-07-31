# -*- coding: utf-8 -*-
"""「마켓 공통」 ↔ 마켓 — 넣기 · 불러오기 · 값 출처 판정.

사장님 확정 2026-07-31 —
  「마켓 공통에서 채우고, 적용할 마켓만 체크해서 적용. 이것은 1회성임.
   한번 설정하고 각 마켓에서 수정하면 수정한대로 적용되는 것.
   나중에 마켓 공통에서 다시 수정하고 반영하고 싶은 마켓 체크해서 하면 됨.」

🔴 **공통은 따라다니지 않는다.** 넣는 순간 값이 복사되고 끝이다. 그래서 공통 탭의
   값은 「마지막에 넣은 값」이지 지금 그 마켓의 값이 아니다 — 화면이 이걸 말해야 한다.

왜 service.py 에 넣지 않았나 — service.py 는 이미 만들기·저장·적용·현황을 다 갖고 있다.
여기에 넣기/불러오기까지 넣으면 한 파일이 여섯 가지 일을 한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from lemouton.policy.fields import COMMON_KEY, MARKET_KEYS, item_keys_for
from lemouton.policy.models import MarketPolicyValue
from lemouton.policy.service import PolicyError, values_for


def _utcnow():
    return datetime.now(timezone.utc)


def _check_markets(markets: list[str]) -> list[str]:
    picked = [m for m in dict.fromkeys(markets or []) if m]
    if not picked:
        raise PolicyError('넣을 마켓을 하나도 고르지 않았어요.')
    unknown = [m for m in picked if m not in MARKET_KEYS]
    if unknown:
        raise PolicyError(f'모르는 마켓이에요: {", ".join(unknown)}')
    return picked


def _write(session, *, policy_id: int, market: str, item_key: str,
           config: dict, from_common: bool) -> None:
    """값 한 칸을 쓴다. 공통에서 온 것이면 시각을 남기고, 아니면 지운다."""
    row = session.scalar(select(MarketPolicyValue).where(
        MarketPolicyValue.policy_id == policy_id,
        MarketPolicyValue.market == market,
        MarketPolicyValue.field_key == item_key))
    body = json.dumps(config, ensure_ascii=False)
    stamp = _utcnow() if from_common else None
    if row is None:
        session.add(MarketPolicyValue(policy_id=policy_id, market=market,
                                      field_key=item_key, value=body,
                                      from_common_at=stamp))
    else:
        row.value = body
        row.from_common_at = stamp
    session.flush()


def push_to_markets(session, *, policy, markets: list[str],
                    item_keys: list[str] | None = None) -> int:
    """「마켓 공통」 값을 고른 마켓에 넣는다. 넣은 마켓 수를 돌려준다.

    🔴 **덮어쓴다.** 그 마켓이 따로 고쳐 둔 값이 있으면 사라진다 —
      화면이 넣기 전에 그 사실을 보여줘야 한다.
    """
    picked = _check_markets(markets)
    common = values_for(session, policy.id, COMMON_KEY)
    if item_keys is not None:
        want = set(item_keys)
        common = {k: v for k, v in common.items() if k in want}
    if not common:
        raise PolicyError('「마켓 공통」에 저장된 항목이 없어요 — 먼저 채워 주세요.')
    for mk in picked:
        allowed = set(item_keys_for(mk))
        for k, cfg in common.items():
            if k not in allowed:
                continue        # 그 마켓에 없는 항목은 건너뛴다(조용히 만들지 않는다)
            _write(session, policy_id=policy.id, market=mk, item_key=k,
                   config=cfg, from_common=True)
    session.flush()
    return len(picked)


def pull_from_common(session, *, policy, market: str,
                     item_keys: list[str] | None = None) -> int:
    """그 마켓이 「마켓 공통」을 불러온다. 바뀐 항목 수를 돌려준다.

    넣기(push)와 방향만 다르고 결과는 같다 — 값이 복사되고 끝난다.
    """
    if market == COMMON_KEY:
        raise PolicyError('「마켓 공통」이 자기 자신을 불러올 수는 없어요.')
    if market not in MARKET_KEYS:
        raise PolicyError(f'모르는 마켓이에요: {market}')
    common = values_for(session, policy.id, COMMON_KEY)
    if item_keys is not None:
        want = set(item_keys)
        common = {k: v for k, v in common.items() if k in want}
    if not common:
        raise PolicyError('「마켓 공통」에 저장된 항목이 없어요 — 먼저 채워 주세요.')
    allowed = set(item_keys_for(market))
    n = 0
    for k, cfg in common.items():
        if k not in allowed:
            continue
        _write(session, policy_id=policy.id, market=market, item_key=k,
               config=cfg, from_common=True)
        n += 1
    session.flush()
    return n


# ── 값 출처 판정 ────────────────────────────────────────────────────────

def origin_of(session, policy_id: int, market: str) -> dict:
    """{item_key: 'common' | 'own'}. 값이 없는 항목은 **키 자체가 없다**.

    화면에서는 키가 없으면 「없음」으로 그린다.
    """
    out = {}
    for v in session.scalars(select(MarketPolicyValue).where(
            MarketPolicyValue.policy_id == policy_id,
            MarketPolicyValue.market == market)):
        out[v.field_key] = 'common' if v.from_common_at else 'own'
    return out


def market_summary(session, policy_id: int) -> dict:
    """마켓마다 한 단어 + 날짜 — {market: {'state': ..., 'at': datetime|None}}.

    state: 'common'(공통에서 받음) · 'own'(직접 고침) · 'none'(아직 없음)
    한 마켓 안에 공통과 직접이 섞여 있으면 **'own'** 으로 본다 —
    「공통 따름」이라고 말했다가 실제로 다르면 그게 더 나쁘다.

    ★ 마켓마다 따로 묻지 않고 **한 번에 읽어** 마켓별로 나눈다. 목록 화면은
      정책마다 이 함수를 부르는데, 마켓별로 물으면 정책 50개 = 300번이 된다.
    """
    per_market: dict[str, list] = {mk: [] for mk in MARKET_KEYS}
    for v in session.scalars(select(MarketPolicyValue).where(
            MarketPolicyValue.policy_id == policy_id)):
        # 「마켓 공통」 줄은 마켓 요약에 넣지 않는다 — 마켓이 아니다.
        if v.market in per_market:
            per_market[v.market].append(v)

    out = {}
    for mk in MARKET_KEYS:
        rows = per_market[mk]
        if not rows:
            out[mk] = {'state': 'none', 'at': None}
            continue
        stamps = [r.from_common_at for r in rows if r.from_common_at]
        state = 'common' if len(stamps) == len(rows) else 'own'
        out[mk] = {'state': state, 'at': max(stamps) if stamps else None}
    return out
