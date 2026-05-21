"""[E] 템플릿·조합·학습사전·기타URL·가격이력 — 신규 테이블."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, String, Text, DateTime, ForeignKey, Boolean
from shared.db import Base


class PriceTemplate(Base):
    __tablename__ = "price_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    # 공통
    boxhero_purchase_price = Column(Integer, default=95000)
    winner_premium_price = Column(Integer, default=149000)
    guardrail_lower = Column(Integer, default=99000)
    guardrail_upper = Column(Integer, default=120000)
    rounding_unit = Column(Integer, default=100)
    external_margin_mode_emergency = Column(String(16), default="rate")
    external_margin_value_emergency = Column(Float, default=0.0945)
    # 스마트스토어 전용
    ss_normal_price = Column(Integer, default=149000)
    ss_boxhero_sale_price = Column(Integer, default=115900)
    ss_external_sale_price = Column(Integer, default=128900)
    ss_fee_rate = Column(Float, default=0.06)
    ss_margin_mode = Column(String(16), default="rate")
    ss_margin_rate = Column(Float, default=0.0945)
    ss_margin_amount = Column(Integer, default=0)
    ss_delivery_fee = Column(Integer, default=3000)   # 0 = 무료배송
    ss_return_fee = Column(Integer, default=0)        # 반품비
    ss_exchange_fee = Column(Integer, default=0)      # 교환비
    ss_extra_json = Column(Text, default='{}')
    # 쿠팡 전용
    coupang_normal_price = Column(Integer, default=149000)
    coupang_boxhero_sale_price = Column(Integer, default=128900)
    coupang_external_sale_price = Column(Integer, default=128900)
    coupang_fee_rate = Column(Float, default=0.1155)
    coupang_margin_mode = Column(String(16), default="rate")
    coupang_margin_rate = Column(Float, default=0.1242)
    coupang_margin_amount = Column(Integer, default=0)
    coupang_delivery_fee = Column(Integer, default=3500)  # 0 = 무료배송
    coupang_return_fee = Column(Integer, default=0)       # 반품비
    coupang_exchange_fee = Column(Integer, default=0)     # 교환비
    coupang_extra_json = Column(Text, default='{}')

    # ★ STEP 7 Task 0.2 — 박스히어로 사입 마진 (R2, 3계층 중 공통 템플릿 default)
    # 외부 사입 (소싱처) vs 자체 사입 (박스히어로) 별도. 옵션·모델 오버라이드 시 그것 우선.
    boxhero_margin_mode_self = Column(String(8), default='rate')        # 자체 사입 (박스히어로)
    boxhero_margin_value_self = Column(Integer, default=2500)           # 25.00%
    boxhero_margin_mode_external = Column(String(8), default='rate')    # 외부 사입 (소싱처)
    boxhero_margin_value_external = Column(Integer, default=2000)       # 20.00%

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class ColorTemplate(Base):
    __tablename__ = "color_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    color_codes_json = Column(Text, nullable=False)
    note = Column(Text)


class SizeTemplate(Base):
    __tablename__ = "size_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    category = Column(String(64), nullable=False)
    size_codes_json = Column(Text, nullable=False)
    note = Column(Text)


class ComboSet(Base):
    """모음전 안 다중 조합 셋트 — 한 모음전에 N개 가능."""
    __tablename__ = "combo_sets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    model_code = Column(String(64), ForeignKey("models.model_code"), nullable=False)
    name = Column(String(120))
    color_codes_json = Column(Text, nullable=False)
    size_codes_json = Column(Text, nullable=False)
    sort_order = Column(Integer, default=0)


class ColorSuggestionRule(Base):
    """학습 사전 — 표준 색상 코드별 추천 변형 누적."""
    __tablename__ = "color_suggestion_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    standard_code = Column(String(32), nullable=False)
    suggested_variant = Column(String(120), nullable=False)
    is_builtin = Column(Boolean, default=False)
    use_count = Column(Integer, default=0)


class SizeSuggestionRule(Base):
    __tablename__ = "size_suggestion_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(64), nullable=False)
    standard_size = Column(String(32), nullable=False)
    suggested_variant = Column(String(120), nullable=False)
    is_builtin = Column(Boolean, default=False)


class EtcSourceUrl(Base):
    """옵션별 기타 소싱처 URL (5개 사이트 외)."""
    __tablename__ = "etc_source_urls"
    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_sku = Column(String(128), ForeignKey("options.canonical_sku"), nullable=False)
    site_name = Column(String(64), nullable=False)
    url = Column(Text, nullable=False)


class PriceTrackHistory(Base):
    """옵션별 시계열 가격·재고 (차트용).

    v2: source_option_id 추가 (정규화된 SourceOption 단위 시계열).
    canonical_sku 는 백워드 호환을 위해 유지 (Phase D 에서 제거 예정).
    """
    __tablename__ = "price_track_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_sku = Column(String(128), nullable=False, index=True)
    source = Column(String(32), nullable=False)
    price = Column(Integer)
    stock = Column(Integer)
    captured_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    # v2: SourceOption 단위 정규화 (nullable — 마이그레이션 진행 중 일부 행은 None)
    source_option_id = Column(Integer, ForeignKey('source_options.id'), index=True)
