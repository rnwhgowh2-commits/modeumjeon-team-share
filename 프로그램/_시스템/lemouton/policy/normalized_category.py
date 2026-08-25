# -*- coding: utf-8 -*-
"""정규 카테고리 — 소싱처와 마켓 사이의 **가운데 층** (2026-08-25 Phase 7-1).

■ 왜 가운데 층을 두나 (사장님 확정 「삼바것 따라가기」)
  지금 우리 방식은 **소싱처 카테고리 → 마켓 카테고리 직접 매핑**이다
  (`registration/models.py:CategoryMapRow`). 그래서 소싱처 카테고리 하나를
  **마켓 6곳에 각각** 이어야 한다 — 소싱처가 늘 때마다 일이 6배로 늘고,
  같은 「여성>원피스」를 소싱처마다 다시 잇는다.

  삼바는 가운데에 **정규 카테고리**를 두고 두 번에 나눠 잇는다::

      소싱처 카테고리 ──▶ 정규 카테고리 ──▶ 마켓 카테고리
       (소싱처마다)        (한 벌)          (마켓마다 한 번만)

  소싱처가 새로 늘어도 「그 소싱처 → 정규」만 이으면 6마켓이 한꺼번에 풀린다.
  삼바 코드 주석도 이 계층을 「기존 소싱→마켓 직접 매핑을 **대체**하기 위한 신규
  계층」이라고 적어 두었다 — 우리가 지금 겪는 문제를 삼바도 겪고 이렇게 풀었다.

■ 🔴 자동 확정하지 않는다 (2026-08-25 사장님 확정)
  「제안은 제안일 뿐이다 — 확신도가 얼마든 자동 확정하지 않는다」는 기존
  `registration/category_suggest.py` 의 정직성 원칙을 그대로 잇는다.
  카테고리가 틀리면 마켓이 등록을 거부하거나 엉뚱한 분류로 올라간다.
  **보류함 = `normalized_category_id` 가 비어 있는 행**이다 — 별도 표를 만들지 않는다.

■ 🔴 이 표들은 아직 **전송 경로에 안 붙어 있다** (Phase 7-1 = 데이터 바닥).
  기존 `CategoryMapRow` 가 여전히 정본이고, 동작은 하나도 안 바뀐다.
  붙이는 것은 Phase 7-2 다 — 그때 이 파일 머리말을 고쳐야 한다.
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from lemouton.policy.models import _utcnow
from shared.db import Base

# ── 마켓 매핑 상태 (삼바 상수를 그대로 따른다) ────────────────────────────
#: 아직 안 이었다 — **이게 보류함이다.**
UNMAPPED = 'UNMAPPED'
#: 이었다.
MAPPED = 'MAPPED'
#: 그 마켓에 올릴 수 없는 분류다(계정 권한 등). 「안 이은 것」과 구분한다.
BLOCKED = 'BLOCKED'
#: 인증(KC 등)이 있어야 올릴 수 있다.
REQUIRES_CERT = 'REQUIRES_CERT'

STATUSES = (UNMAPPED, MAPPED, BLOCKED, REQUIRES_CERT)

#: 사장님이 읽는 말 — 영문 코드를 화면에 내보내지 않는다.
STATUS_LABEL = {
    UNMAPPED: '아직 안 이음',
    MAPPED: '이었음',
    BLOCKED: '이 마켓엔 못 올림',
    REQUIRES_CERT: '인증 필요',
}


class NormalizedCategory(Base):
    """정규 카테고리 한 칸. 소싱처·마켓 양쪽이 가리키는 **공용 기준**이다.

    🔴 마켓 카테고리 트리를 **실시간으로 따라가지 않는다**(삼바와 같은 판단).
      마켓이 분류 체계를 개편해도 이 트리는 자동으로 안 바뀐다 — 자동으로 따라가면
      어제 이어 둔 상품이 오늘 다른 분류로 조용히 옮겨 간다.
    """
    __tablename__ = 'normalized_categories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    #: '여성>원피스>미니' 처럼 '>' 로 잇는다 — 화면·검색이 이 글자를 그대로 쓴다.
    path = Column(String(500), nullable=False, unique=True)
    parent_id = Column(Integer, ForeignKey('normalized_categories.id'))
    depth = Column(Integer, default=0, nullable=False)
    #: 이 칸이 **어느 마켓 트리에서 왔나**(씨앗을 부을 때). 손으로 더한 칸은 NULL.
    source_market = Column(String(20))
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class SourceCategoryLink(Base):
    """소싱처 카테고리 → 정규 카테고리.

    🔴 `normalized_category_id` 가 **NULL 인 행이 보류함**이다. 크롤이 새 소싱처
      카테고리를 만나면 여기 NULL 로 쌓이고, 사장님이 이어 주면 채워진다.
      「없다」가 아니라 「아직 안 이었다」 — 별도 표를 만들면 원천이 두 벌이 된다.
    """
    __tablename__ = 'source_category_links'

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String(40), nullable=False, index=True)
    source_path = Column(String(500), nullable=False)
    normalized_category_id = Column(Integer, ForeignKey('normalized_categories.id'),
                                    index=True)
    #: 제안 근거 점수(0~1). 손으로 이은 것은 NULL.
    #: 🔴 점수가 아무리 높아도 **자동으로 잇지 않는다** — 사장님이 눌러야 이어진다.
    confidence = Column(Integer)
    #: 상위 후보 몇 개 — 화면이 고를 거리를 보여 준다. [{id, path, score}]
    candidates_json = Column(Text)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('source_id', 'source_path', name='uq_source_category_links'),
    )


class MarketCategoryLink(Base):
    """정규 카테고리 → 마켓 카테고리. 마켓마다 한 줄.

    🔴 「못 올림(BLOCKED)」·「인증 필요(REQUIRES_CERT)」를 **상태로 구분**한다.
      예전에는 이런 예외가 코드에 하드코딩돼 있어(삼바도 같은 문제를 겪었다)
      왜 안 올라가는지 화면이 말해 주지 못했다.
    """
    __tablename__ = 'market_category_links'

    id = Column(Integer, primary_key=True, autoincrement=True)
    normalized_category_id = Column(Integer, ForeignKey('normalized_categories.id'),
                                    nullable=False, index=True)
    market = Column(String(20), nullable=False, index=True)
    #: 마켓이 쓰는 코드. ESM 은 'ESM코드/사이트코드' 조합 — 기존 관례 그대로.
    market_cat_code = Column(String(80))
    market_cat_path = Column(String(500))
    status = Column(String(16), default=UNMAPPED, nullable=False)
    #: 「KC인증 필요」·「계정 권한상 못 씀」처럼 **사람이 읽을 사유**.
    note = Column(Text)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('normalized_category_id', 'market',
                         name='uq_market_category_links'),
    )
