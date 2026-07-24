# -*- coding: utf-8 -*-
"""계정 커버리지 — 등록해 둔 계정 중 **주문이 하나도 안 들어오는** 곳을 찾는다.

## 왜 필요한가

2026-07-24 실측: 11번가 주문 `20260722086813881` 이 우리 시스템 어디에도 없었다.
브랜드웨이 계정을 아직 등록하지 않아서였는데, 화면에는 **경고가 한 줄도 없었다.**
사장님이 주문번호를 직접 들고 오지 않았다면 아무도 몰랐을 것이다.

## 무엇을 찾을 수 있고, 무엇은 못 찾나

- ✅ **등록해 뒀는데 조용한 계정** — 키가 만료됐거나, 서버 IP 등록이 풀렸거나,
  정말로 그 기간에 판매가 없었거나. 셋을 우리가 구분할 수는 없지만 **드러내면**
  사장님이 판단할 수 있다.
- ❌ **아예 등록 안 한 계정** — 마켓에 「당신 계정이 몇 개냐」를 묻는 API 가 없다.
  키가 없으면 존재 자체를 알 방법이 없다. 지어내지 않는다.
  → 그래서 화면 문구도 "등록 안 된 계정이 있다"가 아니라 "등록한 계정 중
    N곳이 조용하다"로 쓴다(아는 것만 말한다).
"""
from __future__ import annotations

import datetime as _dt

KST = _dt.timezone(_dt.timedelta(hours=9))


def _norm(v) -> str:
    """'브랜드타임(11번가)' 와 '브랜드타임' 을 같은 것으로 본다.

    주문 행의 쇼핑몰별칭에는 마켓 이름이 괄호로 붙는 경우가 있다(마켓마다 다름).
    이름만 비교하면 멀쩡한 계정이 '조용하다'로 잘못 잡힌다.
    """
    s = str(v or "").strip()
    if s.endswith(")") and "(" in s:
        s = s[:s.rindex("(")].strip()
    return s


def survey(*, days: int = 21, session=None) -> dict:
    """마켓별로 등록 계정 ↔ 실제로 주문이 들어온 계정을 대조한다.

    Returns {days, markets:[{market, registered, seen, silent}], silent_total}
    """
    from lemouton.markets import order_store as _store
    from lemouton.markets.order_export import _active_accounts, market_label, supported_markets

    now = _dt.datetime.now(KST)
    since = (now - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
    until = now.strftime("%Y-%m-%d")

    out, silent_total = [], 0
    for m in sorted(supported_markets()):
        registered = [n for _p, n in (_active_accounts(m) or []) if n]
        if not registered:
            continue                      # 등록이 아예 없는 마켓은 할 말이 없다
        rows = _store.load([m], since=since, until=until,
                           include_claims=False, session=session)
        seen = {_norm(r.get("쇼핑몰별칭")) for r in rows}
        seen.discard("")
        silent = [n for n in registered if _norm(n) not in seen]
        silent_total += len(silent)
        out.append({"market": m, "label": market_label(m),
                    "registered": registered,
                    "seen": sorted(seen), "silent": silent})
    return {"days": days, "markets": out, "silent_total": silent_total}
