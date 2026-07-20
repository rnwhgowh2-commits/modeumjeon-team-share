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
    ss_boxhero_sale_price = Column(Integer, default=115900)   # 사입 지정가
    ss_external_sale_price = Column(Integer, default=128900)  # 소싱 지정가
    ss_fee_rate = Column(Float, default=0.06)
    # [DEPRECATED 2026-05-25] 단일 모드 — 소싱/사입 분리로 대체. 백워드 호환용 유지.
    ss_margin_mode = Column(String(16), default="rate")
    ss_margin_rate = Column(Float, default=0.0945)
    ss_margin_amount = Column(Integer, default=0)
    # [NEW 2026-05-25] 소싱처 책정 — mode in ('rate','amount','fixed')
    ss_mode_sourcing = Column(String(8), default='rate')
    ss_rate_sourcing = Column(Float, default=0.0945)
    ss_amount_sourcing = Column(Integer, default=0)
    # [NEW 2026-05-25] 사입 책정
    ss_mode_purchase = Column(String(8), default='rate')
    ss_rate_purchase = Column(Float, default=0.0945)
    ss_amount_purchase = Column(Integer, default=0)
    ss_delivery_fee = Column(Integer, default=3000)   # 0 = 무료배송
    ss_return_fee = Column(Integer, default=0)        # 반품비
    ss_exchange_fee = Column(Integer, default=0)      # 교환비
    ss_extra_json = Column(Text, default='{}')
    # 쿠팡 전용
    coupang_normal_price = Column(Integer, default=149000)
    coupang_boxhero_sale_price = Column(Integer, default=128900)   # 사입 지정가
    coupang_external_sale_price = Column(Integer, default=128900)  # 소싱 지정가
    coupang_fee_rate = Column(Float, default=0.1155)
    # [2026-07-20] 스스·쿠팡 외 마켓 수수료 — 값은 사장님이 화면에서 넣는다.
    #   ★ 기본값 None(미설정). 0 이나 6% 같은 임의값을 깔지 않는다 —
    #     모르는 수수료를 아는 척하면 마진이 틀리고, 그게 곧 금전 손실이다.
    #     미설정인 마켓은 자동 가격 계산에서 계속 제외된다(reconcile.PRICED_MARKETS).
    lotteon_fee_rate = Column(Float, nullable=True)
    eleven11_fee_rate = Column(Float, nullable=True)
    auction_fee_rate = Column(Float, nullable=True)
    gmarket_fee_rate = Column(Float, nullable=True)
    # [DEPRECATED 2026-05-25]
    coupang_margin_mode = Column(String(16), default="rate")
    coupang_margin_rate = Column(Float, default=0.1242)
    coupang_margin_amount = Column(Integer, default=0)
    # [NEW 2026-05-25]
    coupang_mode_sourcing = Column(String(8), default='rate')
    coupang_rate_sourcing = Column(Float, default=0.1242)
    coupang_amount_sourcing = Column(Integer, default=0)
    coupang_mode_purchase = Column(String(8), default='rate')
    coupang_rate_purchase = Column(Float, default=0.1242)
    coupang_amount_purchase = Column(Integer, default=0)
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

    # [2026-05-25] 판매가 정책 (색상 통일 / 옵션별 cheapest)
    # 'cheapest' (기본) — 각 옵션마다 소싱처 MIN 가격 + 마진 → 마진 최대 (SmartStore SEO 불리)
    # 'color'    — 같은 색상은 동일 판매가 (소싱처 MAX 기준) → 역마진 방지 + SEO 유리
    pricing_policy = Column(String(16), default='cheapest', nullable=False)

    # [2026-07-15] 마켓별 색상 통일 — 스스/쿠팡 각각. 'color'=켜짐 / 'cheapest'=꺼짐(기본).
    #   레거시 pricing_policy(전역)는 백워드 호환용으로만 남김. 실제 적용은 아래 마켓별 값 우선.
    #   unify_rule: 'max'(가장 비싼 사이즈 기준·손해 방지) | 'src_cheapest'(최저가·마진 최대)
    ss_pricing_policy = Column(String(16), default='cheapest', nullable=False)
    ss_unify_rule = Column(String(16), default='max', nullable=False)
    coupang_pricing_policy = Column(String(16), default='cheapest', nullable=False)
    coupang_unify_rule = Column(String(16), default='max', nullable=False)

    # [2026-05-25] 매입가 산정 우선순위 (사입 카드 0원 차단 — V5 시안)
    # 'template' (기본) — 템플릿 boxhero_purchase_price 우선 → 0이면 옵션 평균매입가 폴백
    # 'avg'              — 옵션 boxhero_avg_purchase_price 우선 → 0이면 템플릿값 폴백
    # 둘 다 0이면 사입 카드 차단 (UI 빨간 🚫 + ＋ 평균매입가 입력 버튼)
    price_source_priority = Column(String(16), default='template', nullable=False)

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
