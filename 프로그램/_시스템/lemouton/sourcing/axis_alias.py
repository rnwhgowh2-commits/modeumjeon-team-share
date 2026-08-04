# -*- coding: utf-8 -*-
"""축 매핑 저장소 — 「우리 축 값 ↔ 소싱처 표기」를 소싱처 단위로 기억한다.

설계: docs/사전점검_옵션URL매핑_설계.md §15 (축 맞추기 확정안), §16 1단계

왜 필요한가
  소싱처는 `BLACK`, 우리는 `검정` 이라 부른다. 조합(색×사이즈)마다 맞추면 6색×10사이즈
  = 60번이지만, **축**만 맞추면 색 6 + 사이즈 10 = 16번이고, 한 번 맞춘 것은 그 소싱처의
  다음 상품에서 다시 묻지 않는다(0번). 이 표가 그 「다시 묻지 않음」을 담는 곳이다.

규칙 (사장님 확정 2026-08-02)
  · 저장 단위 = **소싱처**. 무신사에서 맞춘 것이 롯데온에 새지 않는다.
  · 축 이름은 **고정이 아니다**. 매트릭스에서 지은 이름 그대로(색상·사이즈·모델·재질…).
  · **1:1** — 우리 값 하나에 소싱처 값 하나. 두 우리 값이 같은 소싱처 값을 쓰면
    그 소싱처 옵션의 재고가 두 배로 계산되어 초과 판매가 난다 → `AliasConflict` 로 막는다.
  · 되돌리기(`clear_alias`)는 한 번에. 되돌리면 그 소싱처 값이 풀려 다른 값이 쓸 수 있다.
  · `origin` 으로 「사장님이 고른 것(manual)」과 「자동이 고른 것(auto)」을 구분한다.
    나중에 값이 이상할 때 자동 탓인지 수기 탓인지 가리기 위한 것 (시안 v6 파란 「수기」 표시).

비교 기준
  저장은 **사장님이 본 표기 그대로** 하고, 비교(중복·역방향 조회)만 정규화형으로 한다.
  정규화 = `shared.sku_format.normalize_label` (소문자 + 공백·`-`·`_`·`.` 제거).
  화면에는 원문이 보여야 하므로 원문을 버리지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (Boolean, Column, DateTime, Index, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Session

from shared.db import Base
from shared.sku_format import normalize_label


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AliasConflict(Exception):
    """이미 다른 우리 값이 그 소싱처 표기를 쓰고 있다 (1:1 위반)."""


class SourceAxisAlias(Base):
    """(소싱처, 축 이름, 우리 값) → 소싱처 표기."""

    __tablename__ = "source_axis_aliases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_key = Column(String(32), nullable=False, index=True)   # musinsa · lotteon …
    axis_name = Column(String(64), nullable=False)                # 색상 · 사이즈 · 모델 …
    our_value = Column(String(128), nullable=False)               # 검정
    source_value = Column(String(255), nullable=False, default="")   # BLACK (원문 보존)
    source_value_norm = Column(String(255), nullable=False, default="")  # black (비교용)
    origin = Column(String(8), nullable=False, default="manual")  # manual | auto
    # [2026-08-02] 「이 소싱처엔 이 값이 없다」 — 사장님이 **정한** 것.
    #   이게 없으면 사전이 틀리게 붙였을 때 거부할 방법이 없다(라이브에서 잡힌 결함).
    #   True 면 source_value 는 빈 값이고, 1:1 잠금에서도 표기를 차지하지 않는다.
    is_absent = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        # 우리 값 하나 = 소싱처 값 하나
        UniqueConstraint("source_key", "axis_name", "our_value",
                         name="uq_axis_alias_our"),
        # 잠금·역방향 조회 (같은 소싱처 표기를 누가 쓰나)
        Index("ix_axis_alias_srcval", "source_key", "axis_name", "source_value_norm"),
    )


# ── 내부 ────────────────────────────────────────────────────────────────

def _clean(name: str, value) -> str:
    v = (value or "").strip() if isinstance(value, str) else ""
    if not v:
        raise ValueError(f"{name} 이(가) 비었습니다.")
    return v


def _release_confirm(session: Session, source_key: str) -> None:
    """맞춤이 바뀌면 그 소싱처 확인 도장을 푼다 (import 는 순환 방지로 지연)."""
    try:
        from .axis_confirm import release_source
        release_source(session, source_key)
    except Exception:
        pass


def _row(session: Session, source_key: str, axis_name: str, our_value: str):
    return (session.query(SourceAxisAlias)
            .filter_by(source_key=source_key, axis_name=axis_name, our_value=our_value)
            .first())


# ── 쓰기 ────────────────────────────────────────────────────────────────

def set_alias(session: Session, *, source_key: str, axis_name: str,
              our_value: str, source_value: str,
              origin: str = "manual") -> SourceAxisAlias:
    """축 한 줄을 맞춘다. 같은 우리 값이면 덮어쓴다(행이 늘지 않는다).

    Raises:
        ValueError: 넷 중 하나라도 비었을 때.
        AliasConflict: 그 소싱처 표기를 **다른** 우리 값이 이미 쓰고 있을 때.
    """
    source_key = _clean("소싱처", source_key)
    axis_name = _clean("축 이름", axis_name)
    our_value = _clean("우리 값", our_value)
    source_value = _clean("소싱처 표기", source_value)
    norm = normalize_label(source_value)
    if not norm:
        raise ValueError("소싱처 표기 이(가) 비었습니다.")
    if origin not in ("manual", "auto"):
        origin = "manual"

    # 1:1 — 같은 표기를 다른 우리 값이 쓰고 있으면 막는다(재고 이중계상 차단)
    taken = (session.query(SourceAxisAlias)
             .filter_by(source_key=source_key, axis_name=axis_name,
                        source_value_norm=norm, is_absent=False)
             .first())
    if taken is not None and taken.our_value != our_value:
        raise AliasConflict(
            f"「{source_value}」 은(는) 이미 「{taken.our_value}」 이(가) 쓰고 있습니다. "
            f"먼저 그 줄에서 놓아야 합니다.")

    row = _row(session, source_key, axis_name, our_value)
    if row is None:
        row = SourceAxisAlias(source_key=source_key, axis_name=axis_name,
                              our_value=our_value)
        session.add(row)
    row.source_value = source_value
    row.source_value_norm = norm
    row.origin = origin
    row.is_absent = False
    # [2026-08-02] 맞춤이 바뀌면 그 소싱처의 「확인 도장」을 푼다 — 안 그러면
    #   「확인했다」가 옛 상태를 가리켜 바뀐 값이 확인받은 것처럼 보인다.
    _release_confirm(session, source_key)
    session.flush()
    return row


def set_absent(session: Session, *, source_key: str, axis_name: str,
               our_value: str) -> SourceAxisAlias:
    """「이 소싱처엔 이 값이 없다」고 정한다.

    사전이 틀리게 붙였을 때 **거부하는 유일한 방법**이다. 이걸 정해 두면
    `match_one` 이 그 우리 값에는 어떤 표기도 안 붙인다(사전보다 우선).
    되돌리려면 `clear_alias` — 그러면 다시 사전에 맡긴다.
    """
    source_key = _clean("소싱처", source_key)
    axis_name = _clean("축 이름", axis_name)
    our_value = _clean("우리 값", our_value)
    row = _row(session, source_key, axis_name, our_value)
    if row is None:
        row = SourceAxisAlias(source_key=source_key, axis_name=axis_name,
                              our_value=our_value)
        session.add(row)
    row.source_value = ""
    row.source_value_norm = ""      # 빈 값 — 1:1 잠금에서 표기를 차지하지 않는다
    row.origin = "manual"
    row.is_absent = True
    _release_confirm(session, source_key)
    session.flush()
    return row


def clear_alias(session: Session, source_key: str, axis_name: str,
                our_value: str) -> bool:
    """맞춘 것을 되돌린다. 지웠으면 True, 원래 없었으면 False."""
    row = _row(session, source_key, axis_name, our_value)
    if row is None:
        return False
    session.delete(row)
    _release_confirm(session, source_key)
    session.flush()
    return True


# ── 읽기 ────────────────────────────────────────────────────────────────

def get_map(session: Session, source_key: str, axis_name: str) -> dict[str, str]:
    """{우리 값: 소싱처 표기} — 화면 드롭다운의 현재 선택값."""
    return {r.our_value: r.source_value
            for r in session.query(SourceAxisAlias)
            .filter_by(source_key=source_key, axis_name=axis_name, is_absent=False).all()}


def taken_values(session: Session, source_key: str, axis_name: str) -> dict[str, str]:
    """{소싱처 표기: 그것을 쓰는 우리 값} — 드롭다운 회색 잠금 표시용."""
    return {r.source_value: r.our_value
            for r in session.query(SourceAxisAlias)
            .filter_by(source_key=source_key, axis_name=axis_name, is_absent=False).all()}


def resolve(session: Session, source_key: str, axis_name: str,
            source_value: str) -> str | None:
    """소싱처 표기 → 우리 값. 못 찾으면 None. (대소문자·띄어쓰기 무시)"""
    norm = normalize_label(source_value)
    if not norm:
        return None
    row = (session.query(SourceAxisAlias)
           .filter_by(source_key=source_key, axis_name=axis_name,
                      source_value_norm=norm, is_absent=False)
           .first())
    return row.our_value if row else None


def list_aliases(session: Session, source_key: str,
                 axis_name: str | None = None) -> list[dict]:
    """화면 표시용 목록. axis_name 을 주면 그 축만."""
    q = session.query(SourceAxisAlias).filter_by(source_key=source_key)
    if axis_name:
        q = q.filter_by(axis_name=axis_name)
    rows = q.order_by(SourceAxisAlias.axis_name, SourceAxisAlias.our_value).all()
    return [{
        "id": r.id,
        "source_key": r.source_key,
        "axis_name": r.axis_name,
        "our_value": r.our_value,
        "source_value": r.source_value,
        "origin": r.origin,
        "absent": bool(r.is_absent),
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    } for r in rows]


def absent_values(session: Session, source_key: str, axis_name: str) -> set[str]:
    """「이 소싱처엔 없다」고 정해 둔 우리 값들."""
    return {r.our_value for r in session.query(SourceAxisAlias)
            .filter_by(source_key=source_key, axis_name=axis_name, is_absent=True).all()}


def is_absent(session: Session, source_key: str, axis_name: str, our_value: str) -> bool:
    row = _row(session, source_key, axis_name, our_value)
    return bool(row is not None and row.is_absent)
