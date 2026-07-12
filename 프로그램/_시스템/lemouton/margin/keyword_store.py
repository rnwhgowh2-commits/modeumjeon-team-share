# -*- coding: utf-8 -*-
"""카드별 분류 키워드 설정 저장/조회 — 팀 공유 단일 row.

원본(C:/dev/대량등록 마진계산기)은 단일 사용자 card_keywords.json 파일이었다.
팀 공유 앱에서는 이를 DB 한 행(CardKeywordConfig, id=1)으로 승격한다:
멀티유저가 같은 설정을 보고, 파일이 아니라 DB 에 영속한다.

표(row)가 비어 있으면 card_keywords_seed.json 으로 시드한다 — 원본 기본값과
동일하며, margin_embed.html 의 _getCardKeywords() 내장 폴백과도 일치한다.
"""
import json
import os
from typing import Optional

from lemouton.margin.models import CardKeywordConfig

_SEED_PATH = os.path.join(os.path.dirname(__file__), "card_keywords_seed.json")

_CONFIG_ID = 1


def _load_seed() -> dict:
    """번들된 시드 JSON 로드 — 원본 card_keywords.json 그대로."""
    with open(_SEED_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _row(session) -> Optional[CardKeywordConfig]:
    return session.get(CardKeywordConfig, _CONFIG_ID)


def get_config(session) -> dict:
    """전체 설정 dict 반환. 행이 없으면 시드로 생성 후 반환.

    반환값은 top-level `cards` 를 포함한 전체 설정(원본 계약 그대로).
    """
    row = _row(session)
    if row is None:
        seed = _load_seed()
        row = CardKeywordConfig(id=_CONFIG_ID, config=seed)
        session.add(row)
        session.commit()
        return seed
    return row.config or {}


def save_config(session, config: dict) -> dict:
    """전체 설정을 통째로 저장(upsert). 저장한 config 를 반환."""
    row = _row(session)
    if row is None:
        row = CardKeywordConfig(id=_CONFIG_ID, config=config)
        session.add(row)
    else:
        # JSON 컬럼은 in-place 변경을 감지 못하므로 새 dict 를 재대입한다.
        row.config = config
    session.commit()
    return config
