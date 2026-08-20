# -*- coding: utf-8 -*-
"""마켓별 **업로드 불가 카테고리** 검사 — 노션 「(5) 카테고리 맵핑 ※마켓별 업로드 불가
카테고리 검사 기능」.

■ 마켓에 물어보지 않는다
  이미 6마켓 카테고리 사전을 전수 수집해 뒀다(`MarketCategory` — 2026-07 기준 59,048건).
  올려 보고 실패해서 아는 대신, **사전과 대조해 미리** 막는다.

■ 🔴 사전이 없으면 「불가」라고 하지 않는다
  아직 수집 안 한 마켓의 카테고리를 전부 「등록 불가」로 막으면, 올릴 수 있는 상품이
  통째로 멈춘다. 사전이 비어 있으면 **검사하지 않았다**고 말한다(모르면 멈추되,
  「모른다」를 「안 된다」로 바꾸지 않는다).

■ 무엇을 막나 (근거가 확실한 것만)
  1. 사전에 없는 코드      — 그 마켓에 존재하지 않는 카테고리
  2. 사라진 코드           — 재수집에서 없어진 것(`removed_at`)
  3. 리프가 아닌 코드      — 마켓은 대개 맨 끝 카테고리에만 상품을 받는다
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

OK = 'ok'
NOT_FOUND = 'not_found'        # 사전에 없다
REMOVED = 'removed'            # 마켓에서 사라졌다
NOT_LEAF = 'not_leaf'          # 끝 카테고리가 아니다
NO_DICT = 'no_dict'            # 그 마켓 사전이 아직 없다 — 검사 못 함
NO_CODE = 'no_code'            # 카테고리를 아직 안 정했다


def _codes(raw) -> list[str]:
    """ESM 은 맵핑을 'sd코드/site코드' 로 저장한다 — 둘 중 하나만 사전에 있을 수 있다."""
    s = str(raw or '').strip()
    if not s:
        return []
    return [p for p in ({s} | set(s.split('/'))) if p.strip()]


def check(session, *, market: str, code) -> dict:
    """(마켓, 카테고리 코드) → {'state', 'reason', 'path'}.

    state 가 OK 또는 NO_DICT 가 아니면 그 마켓에 올리면 안 된다.
    """
    from lemouton.registration.models import MarketCategory

    cands = _codes(code)
    if not cands:
        return {'state': NO_CODE, 'path': None,
                'reason': '카테고리를 아직 정하지 않았습니다.'}

    rows = (session.query(MarketCategory)
            .filter(MarketCategory.market == market,
                    MarketCategory.code.in_(cands)).all())
    if not rows:
        # 사전 자체가 비었는지 먼저 본다 — 「사전 없음」과 「없는 코드」는 다른 말이다.
        have = (session.query(MarketCategory)
                .filter(MarketCategory.market == market).first())
        if have is None:
            return {'state': NO_DICT, 'path': None,
                    'reason': f'{market} 카테고리 사전이 아직 없어 등록 가능한 '
                              f'카테고리인지 검사하지 못했습니다 — 「불가」라는 뜻이 '
                              f'아닙니다. 카테고리 사전을 먼저 수집해 주세요.'}
        return {'state': NOT_FOUND, 'path': None,
                'reason': f'이 마켓에 없는 카테고리입니다({code}) — 그대로 올리면 '
                          f'등록이 거부됩니다. 카테고리 맵핑을 다시 확정해 주세요.'}

    # 살아 있는 행을 먼저 본다(사라진 코드와 짝 코드가 함께 잡힐 수 있다).
    alive = [r for r in rows if r.removed_at is None]
    if not alive:
        return {'state': REMOVED, 'path': rows[0].full_path,
                'reason': f'마켓에서 없어진 카테고리입니다({code} · '
                          f'{rows[0].full_path}) — 맵핑을 다시 확정해 주세요.'}

    leaf = [r for r in alive if r.is_leaf]
    if not leaf:
        r = alive[0]
        return {'state': NOT_LEAF, 'path': r.full_path,
                'reason': f'끝 카테고리가 아닙니다({code} · {r.full_path}) — '
                          f'대부분의 마켓은 맨 끝 카테고리에만 상품을 받습니다.'}
    return {'state': OK, 'path': leaf[0].full_path, 'reason': ''}


def as_skip(result: dict):
    """검사 결과 → `process_apply` 의 사유 1건. 통과면 None.

    ★ 사전이 없어 검사 못 한 것은 **막지 않는다**(blocking=False) — 「모른다」를
      「안 된다」로 바꾸면 올릴 수 있는 상품이 통째로 멈춘다. 대신 기능 공백(gap)으로
      표시해, 상품 문제와 섞이지 않게 한다.
    """
    from lemouton.registration.process_apply import _skip
    st = (result or {}).get('state')
    if st in (OK, None):
        return None
    if st == NO_DICT:
        return _skip('category', 'auto_map', 'CATEGORY_DICT_MISSING',
                     result['reason'], False, gap=True)
    if st == NO_CODE:
        return None      # 카테고리 미정은 crosscheck_delegated 가 이미 말한다
    return _skip('category', 'market_cat_code', 'CATEGORY_NOT_UPLOADABLE',
                 result['reason'], True)
