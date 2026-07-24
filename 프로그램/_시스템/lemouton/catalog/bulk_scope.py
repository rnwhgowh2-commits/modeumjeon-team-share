# -*- coding: utf-8 -*-
"""대량등록 탭 — 우리가 대량등록으로 올린 상품 현황.

★ [2026-07-24 검증에서 발견] 이 탭이 **거짓 기능**이었다. 눌러도 내용이 안 바뀌고
  같은 숫자를 보여줬다. 눌러도 아무 일 없는 버튼은 만들지 않는다.

세는 기준은 `product_draft_markets.status` — 마켓에 실제로 올라갔는지의 우리 기록이다.
  ok        → 올라감(판매중)
  pending   → 아직 안 올림
  blocked   → 잠금에 막혀 안 올림
  failed    → 실패 — 마켓에 있는지 **모른다**
  uncertain → 확인 전 잠금 — 있을 수도 없을 수도. **모름**

★ failed·uncertain 을 '판매중'으로 세면 없는 상품을 있다고 보고하는 셈이고,
  '안 올림'으로 세면 있는 상품을 없다고 하는 셈이다. 둘 다 거짓이라 **모름**으로 둔다.
"""
from __future__ import annotations

#: 대량등록 기록 상태 → 화면의 통일 상태
_MAP = {
    'ok': 'sale',
    'pending': 'waiting',
    'blocked': 'waiting',
    'failed': 'unknown',
    'uncertain': 'unknown',
}


def bulk_counts(session) -> dict:
    """{마켓: {계정: {상태: 건수}}} — 현황 화면이 읽는 모양 그대로."""
    from lemouton.registration.models import ProductDraft, ProductDraftMarket

    rows = (session.query(ProductDraftMarket)
            .join(ProductDraft, ProductDraft.id == ProductDraftMarket.draft_id)
            .filter(ProductDraft.deleted_at.is_(None))
            .all())
    out: dict = {}
    for r in rows:
        status = _MAP.get((r.status or '').strip().lower(), 'unknown')
        acc = out.setdefault(r.market, {}).setdefault(r.account_key or 'default', {})
        acc[status] = acc.get(status, 0) + 1
    return out
