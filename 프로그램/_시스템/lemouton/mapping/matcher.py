"""맵핑 자동 매칭 엔진 — alias 사전 + 내장 정규화 규칙.

흐름:
  market_values (마켓 표기 dict) → canonical_values (재고관리 마스터 dict) + status

매칭 우선순위 (per 차원):
  1. 캐노니컬 직접 일치 (예: 사용자가 마켓 표기를 캐노니컬과 동일하게 입력)
  2. alias 사전 일치 (manual + learned)
  3. 정규화 후 사전 재룩업 (공백·단위 제거 등)
  4. 정규화 후 캐노니컬 재룩업
  5. 영한 흔한 색상 내장 매핑

상태 판정 (가중치 합산):
  ≥ 80 → auto  (즉시 연결)
  50~79 → review (사용자 검토 필요)
  < 50 → unmatched (수동 picker)

UI 에 점수 숫자는 노출 안 함 — 백엔드 내부 결정만.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from lemouton.mapping.models import AliasDimension, AliasCanonical, AliasMapping


# ============ 내장 정규화 ============

# 흔한 단위 — 정규화 시 제거
_UNIT_SUFFIXES = ["mm", "cm", "kr", "us", "eu", "jp"]

# 영한 흔한 색상 (소문자 → 한국어 표준)
_COLOR_EN_KO = {
    "blue": "블루", "navy": "블루", "black": "블랙", "white": "화이트",
    "gray": "그레이", "grey": "그레이", "red": "레드", "pink": "핑크",
    "green": "그린", "yellow": "옐로우", "orange": "오렌지", "purple": "퍼플",
    "brown": "브라운", "beige": "베이지", "ivory": "아이보리",
}


def normalize(value: str) -> str:
    """공백·하이픈 제거 + 단위 제거 + 소문자 + 영한 색상 흔한 매핑."""
    if not value:
        return ""
    v = str(value).strip().lower()
    v = re.sub(r"[\s\-_]+", "", v)
    # 단위 접미사 제거
    for suf in _UNIT_SUFFIXES:
        if v.endswith(suf):
            v = v[: -len(suf)]
    # 영한 색상 매핑
    if v in _COLOR_EN_KO:
        v = _COLOR_EN_KO[v]
    return v


# ============ 매칭 결과 ============

@dataclass
class DimMatch:
    """1 차원의 매칭 결과."""
    dimension: AliasDimension
    market_value: str
    canonical: Optional[AliasCanonical]
    matched_by: str  # 'direct' | 'alias' | 'normalized' | 'none'


@dataclass
class MatchResult:
    """옵션 1개의 매칭 결과 — 모든 차원 통합."""
    dim_matches: list[DimMatch] = field(default_factory=list)
    score: int = 0
    status: str = "unmatched"  # 'auto' | 'review' | 'unmatched'

    @property
    def canonical_values(self) -> dict[str, str]:
        """매칭된 차원만 — {차원이름: 캐노니컬값}."""
        return {
            m.dimension.name: m.canonical.value
            for m in self.dim_matches if m.canonical is not None
        }

    @property
    def unmatched_dims(self) -> list[str]:
        return [m.dimension.name for m in self.dim_matches if m.canonical is None]


# ============ 1 차원 매칭 ============

def _match_dim(session: Session, dimension: AliasDimension, market_value: str) -> DimMatch:
    """1 차원의 1 market_value 를 캐노니컬로 매칭."""
    if not market_value or not market_value.strip():
        return DimMatch(dimension=dimension, market_value=market_value, canonical=None, matched_by="none")

    mv = market_value.strip()

    # 1. 캐노니컬 직접 일치
    c = (
        session.query(AliasCanonical)
        .filter(AliasCanonical.dimension_id == dimension.id, AliasCanonical.value == mv)
        .first()
    )
    if c:
        return DimMatch(dimension, market_value, c, "direct")

    # 2. alias 사전 일치 — 같은 차원 안에서만 (canonical join)
    m = (
        session.query(AliasMapping)
        .join(AliasCanonical, AliasMapping.canonical_id == AliasCanonical.id)
        .filter(AliasCanonical.dimension_id == dimension.id, AliasMapping.alias == mv)
        .first()
    )
    if m:
        return DimMatch(dimension, market_value, m.canonical, "alias")

    # 3. 정규화 후 alias 재룩업
    nv = normalize(mv)
    if nv:
        # alias 정규화 비교 — DB 안 alias 들을 normalize() 한 결과와 비교
        # (DB 측 normalize 함수가 없으므로 차원 내 모든 alias 를 fetch 후 in-memory 비교)
        rows = (
            session.query(AliasMapping, AliasCanonical)
            .join(AliasCanonical, AliasMapping.canonical_id == AliasCanonical.id)
            .filter(AliasCanonical.dimension_id == dimension.id)
            .all()
        )
        for am, ca in rows:
            if normalize(am.alias) == nv:
                return DimMatch(dimension, market_value, ca, "normalized")

        # 4. 정규화 후 캐노니컬 재룩업
        canons = (
            session.query(AliasCanonical)
            .filter(AliasCanonical.dimension_id == dimension.id)
            .all()
        )
        for ca in canons:
            if normalize(ca.value) == nv:
                return DimMatch(dimension, market_value, ca, "normalized")

    return DimMatch(dimension, market_value, None, "none")


# ============ 옵션 1개 매칭 (모든 차원 통합) ============

def match_option(session: Session, market_values: dict[str, str]) -> MatchResult:
    """1 옵션의 모든 차원을 매칭.

    market_values: {"모델": "클래식", "색상": "파랑", "사이즈": "230mm"}
    """
    dims = (
        session.query(AliasDimension)
        .filter(AliasDimension.is_active.is_(True))
        .order_by(AliasDimension.sort_order, AliasDimension.id)
        .all()
    )
    total_weight = sum(d.weight for d in dims) or 1  # 0 division 방지
    result = MatchResult()
    score_sum = 0

    for d in dims:
        mv = market_values.get(d.name, "")
        m = _match_dim(session, d, mv)
        result.dim_matches.append(m)
        if m.canonical is not None:
            score_sum += d.weight

    # 가중치 합이 100 아닐 수도 — 정규화: percentage
    if total_weight > 0:
        result.score = int(round(score_sum / total_weight * 100))
    else:
        result.score = 0

    if result.score >= 80:
        result.status = "auto"
    elif result.score >= 50:
        result.status = "review"
    else:
        result.status = "unmatched"

    return result


# ============ 배치 매칭 (모음전 옵션 N개 한 번에) ============

def match_options_batch(session: Session, options: list[dict]) -> list[MatchResult]:
    """모음전 옵션 N개를 한 번에 매칭.

    options: [{"모델": "클래식", "색상": "파랑", "사이즈": "230mm"}, ...]
    """
    return [match_option(session, mv) for mv in options]


# ============ 학습 (inline picker 매핑 후 사전에 자동 추가) ============

def learn_alias(
    session: Session,
    dimension_name: str,
    market_value: str,
    canonical_value: str,
) -> Optional[AliasMapping]:
    """수동 매핑 결과를 사전에 학습 (source='learned').

    이미 캐노니컬·별칭 짝이 존재하면 None 반환.
    """
    from datetime import datetime, timezone
    mv = (market_value or "").strip()
    cv = (canonical_value or "").strip()
    if not mv or not cv or not dimension_name:
        return None

    d = session.query(AliasDimension).filter(AliasDimension.name == dimension_name).first()
    if not d:
        return None

    c = (
        session.query(AliasCanonical)
        .filter(AliasCanonical.dimension_id == d.id, AliasCanonical.value == cv)
        .first()
    )
    if not c:
        # 캐노니컬도 없으면 자동 생성 (학습 단계에서 새 SKU 만난 경우)
        c = AliasCanonical(dimension_id=d.id, value=cv)
        session.add(c)
        session.flush()

    # 중복 check
    existing = (
        session.query(AliasMapping)
        .filter(AliasMapping.canonical_id == c.id, AliasMapping.alias == mv)
        .first()
    )
    if existing:
        return None

    m = AliasMapping(
        canonical_id=c.id, alias=mv, source="learned",
        learned_at=datetime.now(timezone.utc),
    )
    session.add(m)
    session.flush()
    return m
