"""[v2] 소싱 정규화 DB 모델.

핵심: 같은 URL을 N 모음전이 입력해도 SourceProduct 1행만 생기게.
크롤러는 SourceProduct 단위로 1번만 fetch → 모든 모음전이 공유.

설계 문서: docs/architecture_v2.md §3.1
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    UniqueConstraint, Index,
)

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class SourceProduct(Base):
    """소싱처 상품 — 1 (site, url) = 1 row. 전역 단일 진실."""
    __tablename__ = "source_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site = Column(String(32), nullable=False)
    url = Column(Text, nullable=False)
    external_product_id = Column(String(128))
    product_name = Column(String(255))

    last_fetched_at = Column(DateTime)
    last_status = Column(String(16))
    last_error_msg = Column(Text)
    last_price = Column(Integer)
    last_stock = Column(Integer)

    # 2026-05-13 추가: 사이트가 판매가에 자동 적용한 카드 할인 정보.
    # JSON 직렬화 dict: {"issuer": "국민카드", "rate": 5.0, "label": "국민카드 5%"} 또는 NULL.
    # 매트릭스 팝업 시안 B 가 "판매가" 라인 옆 보조 텍스트로 렌더링.
    auto_card_discount_json = Column(Text)

    # ★ 2026-05-15 추가: 상품 단위 동적 혜택 (옵션 dict 에서 추출).
    # JSON 직렬화 dict: point_rate / gift_point_amount / ssg_money_rate / already_applied /
    #   card_benefit_price / lotteon_coupons / money_active 등 사이트 특화 동적 키들.
    # compute_breakdown 이 lookup 해서 매트릭스 매입가 산식에 추가 차감으로 자동 반영.
    dynamic_benefits_json = Column(Text)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint('site', 'url', name='uq_source_product_site_url'),
        Index('ix_source_products_site', 'site'),
        Index('ix_source_products_status', 'last_status'),
    )


class SourceOption(Base):
    """소싱처 옵션 — 1 SourceProduct × (color_text, size_text) = 1 row."""
    __tablename__ = "source_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_product_id = Column(Integer, ForeignKey('source_products.id'), nullable=False)
    color_text = Column(String(64))
    size_text = Column(String(32))
    external_option_id = Column(String(128))

    current_price = Column(Integer)
    current_stock = Column(Integer)
    last_fetched_at = Column(DateTime)

    # ★ 2026-05-15 — 옵션별 동적 혜택 (사이트 자체 가변값 — 카드사/적립률/카드혜택가 등)
    #   크롤러 옵션 dict 의 동적 키 (point_rate, point_amount, gift_point_amount,
    #   auto_card_discount, ssg_money_*, card_benefit_*, lotteon_coupons 등) JSON.
    #   compute_breakdown 이 이 JSON 을 lookup 해서 매트릭스 매입가 산식에 자동 반영.
    dynamic_benefits_json = Column(Text)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            'source_product_id', 'color_text', 'size_text',
            name='uq_source_option_product_color_size',
        ),
        Index('ix_source_options_product', 'source_product_id'),
    )


class ModelSourceLink(Base):
    """모음전 ↔ SourceProduct M:N 매핑.

    한 모음전이 여러 사이트의 URL 가질 수 있고,
    한 URL이 여러 모음전에 공유될 수 있음.
    """
    __tablename__ = "model_source_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_code = Column(String(64), ForeignKey('models.model_code'), nullable=False)
    source_product_id = Column(Integer, ForeignKey('source_products.id'), nullable=False)

    created_at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('model_code', 'source_product_id', name='uq_model_source_link'),
        Index('ix_model_source_links_model', 'model_code'),
        Index('ix_model_source_links_source', 'source_product_id'),
    )


class CardDiscountUserPref(Base):
    """2026-05-13 추가: 사용자 카드 보유 미반영 설정 (3 scope).

    scope:
      - 'option': 옵션·사이트 단위 (canonical_sku + source_id)
      - 'bundle': 모음전·사이트 단위 (bundle_code + source_id)
      - 'global': 사이트 글로벌 (source_id 만)

    조회 우선순위: option > bundle > global > default ON.
    enabled = 0 (OFF, 카드 미보유 → 카드할인 미반영).
    """
    __tablename__ = "card_discount_user_pref"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(String(16), nullable=False)
    canonical_sku = Column(String(128))
    bundle_code = Column(String(64))
    source_id = Column(Integer, nullable=False)
    enabled = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class OptionSourceLink(Base):
    """옵션 ↔ SourceOption M:N 매핑.

    canonical_sku 가 여러 SourceOption (사이트별 옵션) 과 매핑됨.
    한 SourceOption 이 여러 옵션에 공유될 수도 있음 (옵션 슬롯 재사용 케이스).
    """
    __tablename__ = "option_source_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_sku = Column(String(128), ForeignKey('options.canonical_sku'), nullable=False)
    source_option_id = Column(Integer, ForeignKey('source_options.id'), nullable=False)

    created_at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('canonical_sku', 'source_option_id', name='uq_option_source_link'),
        Index('ix_option_source_links_sku', 'canonical_sku'),
        Index('ix_option_source_links_source', 'source_option_id'),
    )
