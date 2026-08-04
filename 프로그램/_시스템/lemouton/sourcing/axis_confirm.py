# -*- coding: utf-8 -*-
"""소싱처별 「확인 도장」 — 사장님이 눈으로 한 번 본 것을 남긴다.

사장님 확정 (2026-08-02)
  「소싱처별 매칭된 결과를 보여주도록 해. 사용자가 직접 한번 확인하는게 필수야. 그래야 사고가 안나.」

왜 소싱처 단위인가
  같은 색을 소싱처마다 다르게 부른다(무신사 「BLACK」 · 롯데온 「블랙」 · 어떤 곳은 「흑색」).
  무신사를 확인한 것이 롯데온을 확인해준 게 아니다.

핵심 규칙
  **그 소싱처의 맞춤이 바뀌면 도장이 풀린다.** 안 그러면 「확인했다」가 옛 상태를 가리켜,
  바뀐 값이 확인받은 것처럼 보인다 — 이 프로젝트가 반복해 당한 「조용한 실패」다.
  풀리는 시점 = `axis_alias.set_alias` / `clear_alias` 가 그 소싱처를 건드릴 때.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Session

from shared.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AxisConfirmation(Base):
    """(상품, 소싱처) 하나당 한 줄. 있으면 「확인함」, 없으면 「아직 안 봄」."""

    __tablename__ = "axis_confirmations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_code = Column(String(64), nullable=False, index=True)
    source_key = Column(String(32), nullable=False)
    confirmed_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("model_code", "source_key", name="uq_axis_confirm"),
    )


def _clean(name: str, v) -> str:
    s = (v or "").strip() if isinstance(v, str) else ""
    if not s:
        raise ValueError(f"{name} 이(가) 비었습니다.")
    return s


def confirm(session: Session, model_code: str, source_key: str) -> AxisConfirmation:
    """「이 소싱처 확인했습니다」 도장. 두 번 눌러도 한 줄만 남는다."""
    model_code = _clean("상품", model_code)
    source_key = _clean("소싱처", source_key)
    row = (session.query(AxisConfirmation)
           .filter_by(model_code=model_code, source_key=source_key).first())
    if row is None:
        row = AxisConfirmation(model_code=model_code, source_key=source_key)
        session.add(row)
    row.confirmed_at = _utcnow()
    session.flush()
    return row


def unconfirm(session: Session, model_code: str, source_key: str) -> bool:
    """도장을 뗀다. 뗐으면 True, 원래 없었으면 False."""
    row = (session.query(AxisConfirmation)
           .filter_by(model_code=model_code, source_key=source_key).first())
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def release_source(session: Session, source_key: str) -> int:
    """그 소싱처의 도장을 **전 상품에서** 푼다.

    맞춤(별칭)이 바뀌면 그 소싱처의 「확인했다」는 옛 상태를 가리키게 되므로,
    상품을 가리지 않고 모두 푼다. 별칭 자체가 소싱처 단위로 공유되기 때문이다.
    """
    if not (source_key or "").strip():
        return 0
    n = (session.query(AxisConfirmation)
         .filter_by(source_key=source_key)
         .delete(synchronize_session=False))
    session.flush()
    return int(n or 0)


def is_confirmed(session: Session, model_code: str, source_key: str) -> bool:
    return (session.query(AxisConfirmation)
            .filter_by(model_code=model_code, source_key=source_key)
            .first()) is not None


def confirmed_map(session: Session, model_code: str,
                  source_keys: list[str]) -> dict[str, bool]:
    """{소싱처: 확인함?} — 화면 열 머리의 도장 표시용."""
    keys = [k for k in (source_keys or []) if k]
    if not keys:
        return {}
    done = {r.source_key for r in session.query(AxisConfirmation)
            .filter(AxisConfirmation.model_code == model_code,
                    AxisConfirmation.source_key.in_(keys)).all()}
    return {k: (k in done) for k in keys}
