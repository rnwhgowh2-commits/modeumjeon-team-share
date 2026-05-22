"""[v3] 소싱처 사전 + 옵션×소싱처 매핑 + 가격 자동/수기 설정.

설계 (사용자 확정 v5.1):
  · SourceRegistry      = 전역 소싱처 사전 (이름 + 메인 URL · 사용자 자유 등록·정렬)
  · OptionSourceLink    = 옵션 × 소싱처 → 상세 URL + 캐시된 가격·재고
  · OptionPriceConfig   = 옵션별 자동 ON/OFF · 마진율 · 수수료율 (배송비는 PriceTemplate)

배송비:
  · §2 PriceTemplate 의 ss_delivery_fee / coupang_delivery_fee 활용 (이미 존재)
  · 자동계산식: 판매가 = 원가 × (1 + 마진율) × (1 + 수수료율) + 배송비
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Boolean, Float, Text, DateTime,
    ForeignKey, Index, UniqueConstraint,
)

from shared.db import Base


class SourceRegistry(Base):
    """소싱처 사전 — 전역. 옵션 매트릭스 dropdown 의 소스 목록.

    UI: /sources 페이지에서 추가/삭제/이름변경/순서변경.
    각 소싱처는 메인 URL 1개만 등록 (예: 무신사 = musinsa.com).
    옵션 상세 URL 은 OptionSourceLink.product_url 에서 별도 관리.
    """
    __tablename__ = "source_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False)        # "무신사"
    main_url = Column(String(512))                                 # "https://musinsa.com"
    sort_order = Column(Integer, default=0, nullable=False)
    note = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class OptionSourceUrl(Base):
    """옵션 × 소싱처 → 상세 URL + 캐시된 가격·재고.

    1 옵션이 N개 소싱처에 등록 가능 (르무통 클래식 그레이-230 = 무신사·SSF·29CM).
    [Phase 3] 한 소싱처에 URL 여러 개 허용 (다중 URL) — UniqueConstraint 제거.
    """
    __tablename__ = "option_source_urls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_sku = Column(
        String(128),
        ForeignKey("options.canonical_sku", ondelete="CASCADE"),
        nullable=False,
    )
    source_id = Column(
        Integer,
        ForeignKey("source_registry.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_url = Column(Text, nullable=False)         # 옵션 상세 URL
    price_cached = Column(Integer)                     # 마지막 추출 가격 (검증용)
    stock_cached = Column(Integer)                     # 마지막 추출 재고
    last_checked_at = Column(DateTime)                 # 마지막 검증 시각
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # [Phase 3] (canonical_sku, source_id) UniqueConstraint 제거 — 한 소싱처 다중 URL 허용.
    __table_args__ = (
        Index("ix_option_source_urls_v3_sku", "canonical_sku"),
        Index("ix_option_source_urls_v3_src", "source_id"),
    )


class OptionPriceConfig(Base):
    """옵션별 가격 자동/수기 + 마진율·수수료율.

    auto_enabled=True (디폴트): 자동계산 = (마진율 + 수수료율 + 배송비)
      · margin_rate / ss_fee_rate / cp_fee_rate: NULL 이면 PriceTemplate 값 사용
      · 옵션마다 override 가능
    auto_enabled=False: 수기 = manual_ss_price / manual_cp_price 사용
    재고: manual_stock 은 항상 사용자 입력 (자동 ON/OFF 무관)
    """
    __tablename__ = "option_price_config"

    canonical_sku = Column(
        String(128),
        ForeignKey("options.canonical_sku", ondelete="CASCADE"),
        primary_key=True,
    )
    auto_enabled = Column(Boolean, default=True, nullable=False)

    # auto_enabled=True 시 사용 (NULL = PriceTemplate 값 상속)
    margin_rate = Column(Float)                # 0.10 = 10%
    ss_fee_rate = Column(Float)                # 0.08
    cp_fee_rate = Column(Float)                # 0.14

    # auto_enabled=False 시 사용
    manual_ss_price = Column(Integer)
    manual_cp_price = Column(Integer)

    # 재고 (자동/수기 무관)
    manual_stock = Column(Integer)

    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────────────────────
#  헬퍼 — 가격 자동계산 공식
# ─────────────────────────────────────────────────────────────────────────────

def calc_auto_price(
    purchase_price: int,
    margin_rate: float,
    fee_rate: float,
    shipping_fee: int,
    rounding_unit: int = 100,
) -> tuple[int, dict]:
    """판매가 = 원가 × (1 + 마진율) × (1 + 수수료율) + 배송비.

    [ai-workflow Phase 1 — 가격 계산기 통합]
    실제 계산은 lemouton.pricing.unified.compute_sale_price_unified 에 위임한다.
    가격 계산이 3곳(스케줄러·매트릭스·재고관리)으로 흩어져 값이 어긋나던 것을
    단일 함수로 통일 — "화면값 = 마켓 업로드값" 보장.
    반환 형식 (rounded_price, breakdown_dict) 은 기존 호출자 호환 위해 유지.

    Returns:
        (rounded_price, breakdown_dict) — breakdown 으로 산출과정 표시.
    """
    from lemouton.pricing.unified import compute_sale_price_unified
    result = compute_sale_price_unified(
        purchase_price, margin_rate, fee_rate,
        shipping_fee=shipping_fee, rounding_unit=rounding_unit,
    )
    return result.final_price, result.breakdown
