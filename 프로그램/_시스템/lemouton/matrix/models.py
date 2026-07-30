"""매트릭스 옵션 — 원본(U) · 파생(P).

노션 스펙 (2026-07-30 사장님 확정):
  · **원본 매트릭스 옵션**(U…) — 축(모델·색상·사이즈)으로 펼친 옵션 묶음.
    지금 구조에서 **모델(Model) 하나가 곧 원본 매트릭스 하나**다.
    멤버는 `Option.model_code` 가 이미 알고 있으므로 여기 또 저장하지 않는다
    (같은 사실을 두 곳에 두면 반드시 갈린다).
  · **파생 매트릭스 옵션**(P…) — 개별 옵션을 골라 만든 새 묶음. 원본을 가리킨다.
    멤버는 골라 담은 것이라 명시 저장이 필요하다.
  · 🔴 소싱처 URL·사입품번은 **원본에서만 고칠 수 있다.**
    파생은 원본의 옵션을 그대로 가리키므로, 파생에서 고치면 원본이 바뀐다.
    그래서 화면에서 막고 「원본으로 가기」로 보낸다(service.edit_target 참조).

기존 Model→Option 소유 관계는 **하나도 건드리지 않는다**. 그 위에 얹기만 한다.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)

from shared.db import Base

KIND_ORIGIN = 'origin'
KIND_DERIVED = 'derived'


def _utcnow():
    return datetime.now(timezone.utc)


class MatrixOption(Base):
    """매트릭스 옵션 묶음 1개. 원본이면 model_code, 파생이면 origin_id 를 가진다."""
    __tablename__ = 'matrix_options'

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 표시번호 — 원본 'U20260730-000001' / 파생 'P20260730-000001' (shared/display_no.py)
    display_no = Column(String(24), index=True)
    name = Column(String(255), nullable=False)              # 매트릭스 옵션명
    kind = Column(String(8), nullable=False)                # origin | derived

    # 원본 전용 — 어느 모델에서 펼쳐졌나 (모델 1 : 원본 1)
    model_code = Column(String(64), ForeignKey('models.model_code'), index=True)
    # 파생 전용 — 어느 원본에서 갈라졌나
    origin_id = Column(Integer, ForeignKey('matrix_options.id'), index=True)

    memo = Column(Text)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(DateTime)

    __table_args__ = (
        # 모델 하나에 원본 매트릭스는 하나뿐 — 둘이 되면 어느 쪽이 진짜인지 알 수 없다.
        UniqueConstraint('model_code', 'kind', name='uq_matrix_option_model_kind'),
        Index('ix_matrix_options_kind', 'kind'),
    )


class BundleMatrixLink(Base):
    """모상품이 **어느 매트릭스에서 옵션을 가져왔는가** — 추적용.

    옵션 자체는 복제해 새 모델이 소유한다(build_service 주석 참조).
    여기 기록은 「이 상품은 저 묶음에서 왔다」를 화면에 보여주기 위한 것이지,
    옵션 목록의 진실 원천이 아니다.
    """
    __tablename__ = 'bundle_matrix_links'

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_code = Column(String(64), ForeignKey('models.model_code'),
                        nullable=False, index=True)
    matrix_option_id = Column(Integer, ForeignKey('matrix_options.id'),
                              nullable=False, index=True)
    copied_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)


class MatrixOptionMember(Base):
    """파생 매트릭스에 담긴 개별 옵션. **원본은 여기 채우지 않는다**(모델이 이미 안다)."""
    __tablename__ = 'matrix_option_members'

    id = Column(Integer, primary_key=True, autoincrement=True)
    matrix_option_id = Column(Integer, ForeignKey('matrix_options.id'),
                              nullable=False, index=True)
    canonical_sku = Column(String(128), ForeignKey('options.canonical_sku'),
                           nullable=False, index=True)
    sort_no = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('matrix_option_id', 'canonical_sku',
                         name='uq_matrix_member'),
    )
