# -*- coding: utf-8 -*-
"""정책 × 마켓 → **어느 계정으로 보낼지** (2026-08-24 Phase 4-3).

■ 왜 필요했나 (실측)
  전송 경로가 계정을 정하는 자리는 한 곳뿐이다 —
  `webapp/routes/bulk/drafts.py:preflight_rows` 의
  `account_key = str(keys.get(market) or '').strip() or 'default'`.
  그런데 모음전 전송(`send/runner.py:_register`)은 `keys` 를 **안 넘긴다.**
  즉 마켓마다 계정이 여러 개여도 **늘 'default' 계정으로 나갔다.**
  고를 방법 자체가 화면에도 없었다.

■ 🔴 안 고른 상태가 정상이다
  값이 없으면 `'default'` — 지금까지와 똑같이 동작한다. 이 칸이 생겼다고
  달라지는 정책은 하나도 없어야 한다.

■ 🔴 없는 계정을 저장하지 않는다
  화면엔 계정이 걸린 것처럼 보이는데 전송은 엉뚱한 데로 가거나 죽는다.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

#: 안 고른 마켓이 쓰는 계정. 이 문자열의 정본은 `sets/models.py:SetChannel.account_key`.
DEFAULT_KEY = 'default'


def all_for(policy) -> dict:
    """{마켓: 계정키}. 안 정했거나 값이 깨졌으면 빈 dict.

    🔴 깨진 값에서 터지지 않는다 — 읽다 실패했다고 전송을 멈추면 안 된다
      (`service.enabled_markets` 와 같은 규율).
    """
    raw = getattr(policy, 'market_accounts', None)
    if not raw:
        return {}
    try:
        got = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning('정책 %s 의 마켓별 계정 값이 깨져 있습니다 — 기본 계정으로 봅니다',
                       getattr(policy, 'id', '?'))
        return {}
    if not isinstance(got, dict):
        return {}
    return {str(k): str(v) for k, v in got.items() if k and v}


def account_for(policy, market: str) -> str:
    """그 마켓에 쓸 계정 키. 안 골랐으면 `'default'`."""
    return all_for(policy).get(str(market or '').strip()) or DEFAULT_KEY


def keys_for(policy, markets) -> dict:
    """`preflight_rows(keys=...)` 에 그대로 넣을 모양. {마켓: 계정키}.

    안 고른 마켓은 **키 자체를 안 넣는다** — 'default' 를 굳이 실어 보내면
    「일부러 기본 계정을 골랐다」와 「안 골랐다」가 구분되지 않는다.
    """
    got = all_for(policy)
    return {mk: got[mk] for mk in (markets or []) if got.get(mk)}


def set_accounts(session, *, policy, values: dict) -> dict:
    """마켓별 계정을 정한다. 빈 값·None 은 「안 고름」으로 지운다.

    Raises:
        ValueError: 없는 마켓이거나, 그 마켓에 없는 계정을 고른 경우.
    """
    from lemouton.policy.fields import MARKET_KEYS
    from lemouton.sourcing.models_v2 import UploadAccount

    out = all_for(policy)
    for mk, key in (values or {}).items():
        mk = str(mk or '').strip()
        if mk not in MARKET_KEYS:
            raise ValueError(f'모르는 마켓입니다: {mk}')
        key = str(key or '').strip()
        if not key or key == DEFAULT_KEY:
            out.pop(mk, None)
            continue
        # 🔴 없는 계정을 저장하면 화면엔 걸린 것처럼 보이는데 전송이 엉뚱한 데로 간다.
        acc = (session.query(UploadAccount)
               .filter_by(account_key=key, market=mk).first())
        if acc is None:
            raise ValueError(f'{mk} 에 그런 계정이 없습니다: {key}')
        out[mk] = key
    policy.market_accounts = json.dumps(out, ensure_ascii=False) if out else None
    return out


def choices_for(session, markets=None) -> dict:
    """화면이 드롭다운을 그릴 근거 — {마켓: [{key, label}]}. 쓰는 계정만."""
    from lemouton.policy.fields import MARKET_KEYS
    from lemouton.sourcing.models_v2 import UploadAccount

    want = list(markets or MARKET_KEYS)
    out = {mk: [] for mk in want}
    rows = (session.query(UploadAccount)
            .filter(UploadAccount.market.in_(want))
            .order_by(UploadAccount.display_name).all())
    for a in rows:
        if not getattr(a, 'is_active', True):
            continue
        out.setdefault(a.market, []).append(
            {'key': a.account_key, 'label': a.display_name or a.account_key})
    return out
