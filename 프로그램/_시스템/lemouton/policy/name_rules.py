# -*- coding: utf-8 -*-
"""0층 — 상품명 조립 규칙 저장소를 정책에 태우는 곳.

■ 왜 이 파일이 있나 (2026-08-24)
  Phase 1 이 `NameRule` 표와 `market_policies.name_rule_id` 칸을 만들었지만
  **읽는 곳이 한 곳도 없었다.** 표만 있고 배선이 없으면 화면에서 규칙을 골라도
  나가는 상품명은 하나도 안 바뀐다. 이 파일이 그 다리다.

■ 무엇이 규칙 것이고 무엇이 정책 것인가
  규칙(0층)이 갖는 것 : 조립 순서(token_order) · 치환표(replacements) ·
                        마켓별 개별조합(market_overrides) · 길이 재는 법(max_len_mode)
  정책이 갖는 것       : 글자수 상한(max_len) · 이음말(separator) ·
                        중복 단어 제거(dedupe_words) 등 나머지 전부
  → 규칙을 골라도 정책이 정한 나머지 값은 살아 있다. 규칙을 **부분적으로** 도입할 수 있다.

■ 🔴 규칙을 안 고른 정책(`name_rule_id` 가 NULL)은 지금까지와 **완전히 같다.**
  이 칸이 생겼다고 동작이 달라지는 정책은 하나도 없어야 한다.
"""
from __future__ import annotations

import logging

from lemouton.policy.models import NameRule

logger = logging.getLogger(__name__)

#: 규칙이 소유하는 칸 — 규칙을 고르면 이 칸들만 정책 값을 덮어쓴다.
RULE_OWNED_KEYS = ('token_order', 'replacements', 'max_len_mode')


def get(session, rule_id):
    """규칙 한 벌. 없으면 None (지어내지 않는다)."""
    if not rule_id:
        return None
    return session.get(NameRule, int(rule_id))


def resolve(session, *, rule_id, market: str = '') -> dict | None:
    """그 규칙 × 그 마켓에 실제로 적용될 값. 규칙이 없으면 None.

    마켓별 개별조합이 있으면 **그 칸만** 덮어쓴다 — 개별조합에 `token_order` 만
    적어 두면 치환표는 공통 것을 그대로 쓴다.
    """
    rule = get(session, rule_id)
    if rule is None:
        if rule_id:
            # 지워진 규칙을 가리키는 정책 — 조용히 넘기면 「규칙이 왜 안 먹지」가 된다.
            logger.warning('없는 상품명 규칙을 가리키고 있습니다: rule_id=%s', rule_id)
        return None

    out = {
        'token_order': list(rule.token_order or []),
        'replacements': list(rule.replacements or []),
        'max_len_mode': rule.max_len_mode or 'byte',
    }
    over = (rule.market_overrides or {}).get(str(market or '').strip())
    if isinstance(over, dict):
        for k in RULE_OWNED_KEYS:
            if k in over:
                out[k] = over[k]
    return out


def apply_to_rules(session, *, policy, market: str, rules: dict) -> dict:
    """정책이 고른 규칙을 규칙 묶음에 얹어 돌려준다.

    🔴 **원본 dict 를 그 자리에서 고치지 않는다.** 같은 묶음을 마켓마다 돌려 쓰는
      호출부가 있어, 한 마켓 처리가 다음 마켓에 새면 조용히 틀린 이름이 나간다.
    """
    got = resolve(session, rule_id=getattr(policy, 'name_rule_id', None), market=market)
    if got is None:
        return rules

    out = dict(rules or {})
    name_cfg = dict(out.get('name') or {})
    # 규칙이 실제로 가진 값만 덮어쓴다 — 빈 조립 순서로 정책 값을 지우면
    # 상품명이 통째로 사라진다.
    if got['token_order']:
        name_cfg['token_order'] = got['token_order']
    if got['replacements']:
        name_cfg['replacements'] = got['replacements']
    name_cfg['max_len_mode'] = got['max_len_mode']
    out['name'] = name_cfg
    return out


# ── 화면·API 가 쓰는 목록 ────────────────────────────────────────────────

def list_rules(session) -> list:
    """규칙 세트 목록 — 최근 고친 순."""
    return list(session.query(NameRule).order_by(NameRule.updated_at.desc()).all())


# ── 상품명에 넣을 수 있는 조각 ────────────────────────────────────────────
#
# 🔴 **여기 없는 조각을 화면에 단추로 내놓으면 안 된다.** 사장님이 눌렀는데 아무것도
#   안 붙으면 「규칙이 안 먹는다」가 되고, 그 오해를 푸는 데 한참 걸린다.
#   조각을 늘리려면 `registration/process_apply.py:_build_name` 에 먼저 붙이고,
#   그 값을 사본(`policy/to_payload.py:set_view`)이 실어 주는지까지 확인한 뒤 여기 적는다.
#
# 🔴 색상·사이즈가 여기 없는 이유: **옵션마다 다른 값**이라 상품 하나의 이름에 넣으면
#   어느 색을 골라도 틀린다(파랑·빨강이 섞인 상품에 「블랙」이 붙는다).
#   옵션별 이름은 다른 문제라 Phase 4 에서 따로 다룬다.

TOKENS = (
    {'key': 'brand', 'label': '브랜드',
     'hint': '상품의 브랜드 (예: 나이키)'},
    {'key': 'origin_name', 'label': '상품명',
     'hint': '소싱처에서 가져온 원래 이름 — 대부분 이게 뼈대가 된다'},
    {'key': 'model_no', 'label': '품번',
     'hint': '제조사 품번 (예: CW2288-111) · 비어 있으면 그 자리는 빠진다'},
    {'key': 'product_no', 'label': '상품번호',
     'hint': '우리 상품 번호 · 비어 있으면 모델 코드를 쓴다'},
    {'key': 'category', 'label': '카테고리',
     'hint': '맨 끝 분류만 쓴다 (「신발>스니커즈」 → 「스니커즈」)'},
)

TOKEN_KEYS = frozenset(t['key'] for t in TOKENS)


def normalize_order(raw) -> list:
    """조립 순서를 저장할 수 있는 모양으로. 빈 줄은 버린다.

    조각 이름이 아니면 **임의 텍스트**다 — 「정품」처럼 늘 붙이고 싶은 말을 넣는 용도.
    """
    out = []
    for x in (raw or []):
        t = str(x if x is not None else '').strip()
        if t:
            out.append(t)
    return out
