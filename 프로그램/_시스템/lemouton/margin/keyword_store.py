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

    시드 삽입 경쟁: 최초 사용 시 동시 요청 둘이 모두 "행 없음"을 보고 각자
    id=1 을 INSERT 하면 하나가 PK/UNIQUE 충돌로 500 난다. IntegrityError 를
    잡아 rollback 후 이미 생긴 행을 다시 읽어 돌려준다(멱등) — 읽기 경로(GET·
    analyze)가 첫 사용에서 조용히 깨지지 않도록.
    """
    from sqlalchemy.exc import IntegrityError

    row = _row(session)
    if row is None:
        seed = _load_seed()
        row = CardKeywordConfig(id=_CONFIG_ID, config=seed)
        session.add(row)
        try:
            session.commit()
            return seed
        except IntegrityError:
            # 다른 요청이 먼저 시드함 — 그 행을 읽어 반환한다.
            session.rollback()
            row = _row(session)
            if row is None:  # 충돌인데 행도 없음 = 설명 불가 → 조용히 삼키지 않는다.
                raise
            return row.config or {}
    return row.config or {}


def save_config(session, config: dict) -> dict:
    """전체 설정을 통째로 저장(upsert). 저장한 config 를 반환.

    ■ 알려진 한계 — 카드별 동시 편집 손실(last-writer-wins). 라우트의 {card,data}
      경로는 "전체 blob 읽기 → 카드 하나 수정 → 전체 blob 쓰기" 다. 두 팀원이 서로
      다른 카드를 동시에 저장하면 나중 쓰기가 먼저 쓰기를 덮어 한 편집이 조용히
      유실된다. 팀 2~5명이 키워드를 드물게 편집하는 현 규모에선 수용 가능한
      last-writer-wins 로 본다(과설계 회피). 문제가 되면 하드닝 방향은 (a) 카드 단위
      원자적 UPDATE(전체 blob 대신 JSON path 갱신) 또는 (b) updated_at 낙관적 잠금
      (읽은 시각과 저장 시각 불일치 시 409) 이다. — 지금은 의도적으로 안 한다(YAGNI).
    """
    row = _row(session)
    if row is None:
        row = CardKeywordConfig(id=_CONFIG_ID, config=config)
        session.add(row)
    else:
        # JSON 컬럼은 in-place 변경을 감지 못하므로 새 dict 를 재대입한다.
        row.config = config
    session.commit()
    return config
