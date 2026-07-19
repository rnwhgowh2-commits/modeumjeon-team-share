"""등급 설정 저장소 — 사장님이 화면에서 고친 값을 보관한다.

설계서: 2026-07-19-크롤주기-변동주기-등급-design.md §4
  "모든 수치는 제안값. 최종은 사장님이 화면에서 설정."

지금까지 :class:`~lemouton.sources.crawl_grade.GradeConfig` 는 **코드 기본값뿐**이라
고칠 데가 없었다. 이 모듈이 그 값을 DB 에 담는다.

━━ 설계 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · **행은 최대 하나** (전역 설정). 소싱처별로 나누는 건 나중에 — 지금 나누면
    "어느 게 이겼나" 를 매번 따져야 한다.
  · **읽기는 행을 만들지 않는다.** 읽었다고 저장하면 「사장님이 정한 값」과
    「그냥 기본값」을 구분할 수 없게 된다.
  · **검증은 저장할 때 한다.** 저장되고 나서 읽을 때 터지면 화면이 통째로 죽는다.
    GradeConfig.__post_init__ 가 이미 규칙을 알고 있으니 그걸 그대로 쓴다.
"""
from __future__ import annotations

import json

from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.sql import func

from lemouton.sources.crawl_grade import GradeConfig
from shared.db import Base

_SINGLETON_ID = 1


class GradeConfigRow(Base):
    """등급 설정 1행(전역). 값은 JSON 으로 담아 항목이 늘어도 마이그레이션이 없다."""

    __tablename__ = "crawl_grade_config"

    id = Column(Integer, primary_key=True)
    payload_json = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


def _load(session) -> dict:
    row = session.get(GradeConfigRow, _SINGLETON_ID)
    if not row:
        return {}
    try:
        return json.loads(row.payload_json or "{}") or {}
    except (ValueError, TypeError):
        return {}          # 깨진 값은 기본값으로 — 화면이 죽는 것보다 낫다


def get_grade_config(session) -> GradeConfig:
    """지금 쓰이는 등급 설정. 저장된 게 없으면 코드 기본값.

    ★ 읽기만 하고 **행을 만들지 않는다**.
    """
    d = _load(session)
    if not d:
        return GradeConfig()
    base = GradeConfig()
    return GradeConfig(
        boundaries=tuple(d.get("boundaries") or base.boundaries),
        coefficients=tuple(d.get("coefficients") or base.coefficients),
        ceiling_per_day=float(d.get("ceiling_per_day", base.ceiling_per_day)),
        floor_per_day=float(d.get("floor_per_day", base.floor_per_day)),
    )


def save_grade_config(session, *, boundaries=None, coefficients=None,
                      ceiling_per_day=None, floor_per_day=None) -> GradeConfig:
    """전달된 항목만 갱신. 호출자가 commit.

    ★ 저장 전에 :class:`GradeConfig` 로 한 번 만들어 본다 — 규칙 위반이면 여기서
      ValueError 가 나고 DB 는 안 건드린다.
    """
    cur = get_grade_config(session)
    merged = GradeConfig(                       # ← 여기서 검증됨
        boundaries=tuple(boundaries) if boundaries is not None else cur.boundaries,
        coefficients=tuple(coefficients) if coefficients is not None else cur.coefficients,
        ceiling_per_day=(float(ceiling_per_day) if ceiling_per_day is not None
                         else cur.ceiling_per_day),
        floor_per_day=(float(floor_per_day) if floor_per_day is not None
                       else cur.floor_per_day),
    )
    payload = json.dumps({
        "boundaries": list(merged.boundaries),
        "coefficients": list(merged.coefficients),
        "ceiling_per_day": merged.ceiling_per_day,
        "floor_per_day": merged.floor_per_day,
    }, ensure_ascii=False)

    row = session.get(GradeConfigRow, _SINGLETON_ID)
    if row:
        row.payload_json = payload
    else:
        session.add(GradeConfigRow(id=_SINGLETON_ID, payload_json=payload))
    session.flush()
    return merged


def reset_grade_config(session) -> GradeConfig:
    """코드 기본값으로 되돌린다(행 삭제). 저장한 적 없어도 안전."""
    row = session.get(GradeConfigRow, _SINGLETON_ID)
    if row:
        session.delete(row)
        session.flush()
    return GradeConfig()


def is_customized(session) -> bool:
    """사장님이 손댄 적이 있나 — 화면에 「기본값 사용 중」을 띄우기 위해."""
    return session.get(GradeConfigRow, _SINGLETON_ID) is not None
