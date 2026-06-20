"""[A] 소싱 통합 레이어 — DB 모델."""
from sqlalchemy import (
    Column, String, Integer, Boolean, ForeignKey, Float, Text,
    DateTime, Index, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from shared.db import Base


class BundleGroup(Base):
    """[v3 시나리오 C] 1 모음전 안에 N 개 Model cluster.

    예: '그레이 운동화 모음전' 그룹 = [클래식 그레이 + 메이트 그레이 + 스타일 그레이]
    기존 모음전(1 모델) 도 자기 자신을 group_code 로 갖는 그룹 1개로 변환됨 (호환성).
    """
    __tablename__ = "bundle_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_code = Column(String(64), nullable=False, unique=True)
    group_name = Column(String(255), nullable=False)
    brand = Column(String(64))
    category = Column(String(64))
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    # [v3] 마켓별 옵션 축 구성 (1~3축). JSON:
    #   {"smartstore": {"axes": [{"name":"색상","source":"color_code"}, ...]},
    #    "coupang":    {"axes": [...]}}
    # source 후보: color_code | size_code | model_code
    option_config_json = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    models = relationship("Model", back_populates="bundle_group")


class Model(Base):
    """모델 마스터 — 1행 = 1 르무통 모델."""
    __tablename__ = "models"

    model_code = Column(String(64), primary_key=True)
    model_name_raw = Column(String(255), nullable=False)
    model_name_display = Column(String(255))
    category = Column(String(100))
    brand = Column(String(100), default="르무통", nullable=False)
    # 품번 — 박스히어로 'model_name' 컬럼 원본 (예: 'FV5420-002')
    # 우리 양식 export/import 의 '품번' 필드와 매핑
    article_no = Column(String(64))

    # 소싱처 URL (5개)
    url_lemouton = Column(Text)
    url_musinsa = Column(Text)
    url_ssf = Column(Text)
    url_lotteon = Column(Text)
    url_ss_lemouton = Column(Text)

    # 마켓 ID
    naver_product_id = Column(String(64))            # originProductNo (sync API 용)
    naver_channel_product_id = Column(String(64))    # channelProductNo (셀러센터 검색·진입 용 — 엑셀 "상품번호")
    coupang_product_id = Column(String(64))            # productId (구매자 페이지 URL 용)
    coupang_seller_product_id = Column(String(64))   # sellerProductId (셀러센터 상품수정 + GET·매핑 API 용)

    # [B] 추가 — 가격 오버라이드
    boxhero_purchase_price_override = Column(Integer)
    boxhero_ss_price_override = Column(Integer)
    boxhero_coupang_price_override = Column(Integer)
    external_ss_price_override = Column(Integer)
    external_coupang_price_override = Column(Integer)
    coupang_winner_premium_override = Column(Integer)

    # 가드레일 오버라이드
    guardrail_lower_override = Column(Integer)
    guardrail_upper_override = Column(Integer)

    # 외부 마진 오버라이드 (비상)
    external_margin_mode_override = Column(String(16))   # 'rate' | 'amount'
    external_ss_margin_value_override = Column(Float)
    external_coupang_margin_value_override = Column(Float)
    use_margin_formula_for_external = Column(Boolean, default=False)

    # ★ STEP 7 Task 0.2 — 박스히어로 마진 모델 단위 오버라이드 (R2)
    boxhero_margin_mode_override = Column(String(8))     # 'rate'|'amount'
    boxhero_margin_value_override = Column(Integer)      # rate=*100, amount=원

    # [C] 추가 — 마켓별 상품명 오버라이드
    naver_product_name_override = Column(String(255))
    coupang_product_name_override = Column(String(255))

    note = Column(Text)

    # [E] 템플릿 매핑 + 마켓 활성화
    price_template_id = Column(Integer, ForeignKey("price_templates.id"))
    color_template_id = Column(Integer, ForeignKey("color_templates.id"))
    size_template_id = Column(Integer, ForeignKey("size_templates.id"))
    market_active_ss = Column(Boolean, default=True)
    market_active_coupang = Column(Boolean, default=True)

    # 마지막 크롤·업로드 성공 시각 (모음전 단위 집계)
    last_crawled_at = Column(DateTime)
    last_uploaded_at = Column(DateTime)

    # 자동화 ON/OFF — v6 Phase 3.5 (2026-05-07)
    # 24시간 상시 자동화 모드에서 모음전별로 일시 정지 가능. 기본 True (모든 신규 모음전 자동화 ON).
    auto_enabled = Column(Boolean, default=True, nullable=False)

    # 가격 모드 v3 — 'color_unified' (기본, 색상 통일가) | 'per_option_cheapest' (옵션별 cheapest 동적)
    ss_price_mode = Column(String(32), default='color_unified')

    # 시나리오 C v3 — 1 모음전 N 모델 cluster 지원
    bundle_group_id = Column(Integer, ForeignKey('bundle_groups.id'), nullable=True, index=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    options = relationship("Option", back_populates="model", cascade="all, delete-orphan")
    bundle_group = relationship("BundleGroup", back_populates="models")


class BundleSourceUrl(Base):
    """소싱처별 다중 URL — 같은 소싱처에 N개 URL 등록 가능 (2026-05-09).

    legacy: Model.url_lemouton 등 단일 컬럼은 유지 (옵션 sources 동기화 호환).
    이 테이블 = 다중 URL 의 source-of-truth. legacy 컬럼은 첫 번째 URL 로 sync.

    [2026-05-24] label 추가 — 사용자가 URL 구분용 라벨 입력 (예: "통합 모음전" / "단품 - 그레이").
    nullable; 빈값이면 UI 에서 URL 자체로 표시.
    """
    __tablename__ = "bundle_source_urls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_code = Column(String(64), ForeignKey("models.model_code"), nullable=False, index=True)
    source_key = Column(String(32), nullable=False)  # lemouton/musinsa/ssf/lotteon/ss_lemouton
    url = Column(Text, nullable=False)
    label = Column(String(120))  # [2026-05-24] 선택 입력 — URL 구분용 라벨
    # [2026-06-20] 유형 사전지정 — dan(단품)/mo(색상 모음전)/deal(모델 모음전). NULL=미지정.
    url_type = Column(String(8))
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # [2026-05-24] 옵션 ↔ URL N:N 매핑
    option_links = relationship(
        "OptionSourceUrlLink",
        back_populates="source_url",
        cascade="all, delete-orphan",
    )


class OptionSourceUrlLink(Base):
    """옵션 ↔ 소싱처 URL N:N 매핑 (2026-05-24).

    한 옵션이 같은 소싱처에서 URL 여러개에 매핑 가능
    (예: 무신사 통합 모음전 + 단품 - 그레이 두 페이지 모두 크롤링).

    UNIQUE(option_canonical_sku, bundle_source_url_id) — 중복 매핑 차단.
    옵션·URL 삭제 시 CASCADE.
    """
    __tablename__ = "option_source_url_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    option_canonical_sku = Column(
        String(128),
        ForeignKey("options.canonical_sku", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bundle_source_url_id = Column(
        Integer,
        ForeignKey("bundle_source_urls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    source_url = relationship("BundleSourceUrl", back_populates="option_links")

    __table_args__ = (
        UniqueConstraint(
            "option_canonical_sku",
            "bundle_source_url_id",
            name="uq_option_source_url_link",
        ),
        Index(
            "ix_oss_url_option",
            "bundle_source_url_id",
            "option_canonical_sku",
        ),
    )


class Option(Base):
    """옵션 매핑 — 1행 = 1 색상×사이즈."""
    __tablename__ = "options"

    canonical_sku = Column(String(128), primary_key=True)
    model_code = Column(String(64), ForeignKey("models.model_code"), nullable=False)
    color_code = Column(String(32), nullable=False)
    color_display = Column(String(64))
    size_code = Column(String(32), nullable=False)
    size_display = Column(String(64))

    # [Phase 2] 단계형 옵션 — N축 단계 값 (step 순서 JSON list). 예: ["블랙","260"]
    # 레거시 2축 옵션은 color_code/size_code 사용 — option_combo.option_axis_values() 가 폴백.
    axis_values_json = Column(Text)

    # [Phase 3] 오프라인 전용 옵션 — 소싱처 URL 없이 사입 재고만 (크롤 경고 X, 사입가 기준)
    offline_only = Column(Boolean, default=False, nullable=False)

    # [2026-05-27 D1] 사용자가 매트릭스에서 OFF 한 옵션. URL 매핑이 있어 데이터 보존 중.
    # is_active=False 인 옵션은 모달에서 노란 빗금(mapped-off)으로 표시.
    # True (기본) = 활성. 셀 클릭으로 토글.
    is_active = Column(Boolean, default=True, nullable=False)

    # [2026-06-13] 크롤 실패/유효가격 없음으로 자동 판매차단된 옵션. is_active(사용자 수동)와 분리.
    #   판매가능 = is_active(수동 ON) AND NOT crawl_blocked(크롤 정상). 크롤 시작 시 리셋되고
    #   유효가격이 다시 잡히면 자동 해제. 옛 가격/재고로 잘못 판매되는 사고 방지.
    crawl_blocked = Column(Boolean, default=False, nullable=False)

    # 소싱처별 옵션 ID (NULL 가능)
    option_id_lemouton = Column(String(128))
    option_id_musinsa = Column(String(128))
    option_id_ssf = Column(String(128))
    option_id_lotteon = Column(String(128))
    option_id_ss_lemouton = Column(String(128))

    # 마켓 옵션 ID
    naver_option_id = Column(String(128))
    coupang_option_id = Column(String(128))

    # 박스히어로 매핑
    boxhero_sku = Column(String(64))
    barcode = Column(String(64))  # 박스히어로 EAN-13 바코드 (라벨 인쇄용)

    # ★ STEP 7 Task 0.2 — 박스히어로 재고관리 (R2 옵션 매트릭스, ADR-002)
    boxhero_stock_total = Column(Integer, default=0)               # 자동 집계 (위치별 합)
    boxhero_avg_purchase_price = Column(Integer, default=0)        # 이동평균 매입가
    boxhero_avg_updated_at = Column(DateTime)                      # 평균 갱신 시각
    # 옵션 단위 사입 마진 오버라이드 (3계층 중 가장 우선 — 옵션>모델>템플릿)
    option_boxhero_margin_mode = Column(String(8))                 # 'rate'|'amount'|None
    option_boxhero_margin_value = Column(Integer)                  # rate=*100 (예: 25.00% → 2500), amount=원
    option_external_margin_mode = Column(String(8))                # 외부 사입 (소싱처) 별도
    option_external_margin_value = Column(Integer)

    # ★ 사입재고 활성화 토글 — ON 이면 매트릭스에서 '자체 판매가'를 우선 적용
    # OFF 이면 외부 (소싱처) 판매가 사용. 사용자 명시 요구.
    use_purchase_inventory = Column(Boolean, default=False, nullable=False)

    # ★ M4/P3/C9 (2026-05-08) — 사입 우선순위 + 수기 판매가
    # purchase_priority: 'auto' (default — 사입재고≥1→사입, 0→소싱) | 'source' | 'purchase'
    # purchase_manual_price: option_boxhero_margin_mode='manual' 일 때 직접 판매가 (₩ 정수)
    purchase_priority = Column(String(16), default='auto', nullable=False)
    purchase_manual_price = Column(Integer)

    # ★ (2026-05-25 M) 마켓별 지정가 활성화 — 소싱·사입 카드 각 마켓 따로 ON/OFF
    # 마켓별 active=ON 이면 그 마켓 가격을 fixed 값으로 덮어쓰기. OFF 면 자동값.
    src_fixed_ss_active = Column(Boolean, default=False, nullable=False)
    src_fixed_cp_active = Column(Boolean, default=False, nullable=False)
    src_fixed_ss_price = Column(Integer)
    src_fixed_cp_price = Column(Integer)
    pur_fixed_ss_active = Column(Boolean, default=False, nullable=False)
    pur_fixed_cp_active = Column(Boolean, default=False, nullable=False)
    pur_fixed_ss_price = Column(Integer)
    pur_fixed_cp_price = Column(Integer)
    # [DEPRECATED 2026-05-25] 이전 A1 카드 단위 active — M 전환 후 미사용. DB 컬럼 안전상 유지.
    src_fixed_active = Column(Boolean, default=False, nullable=False)
    pur_fixed_active = Column(Boolean, default=False, nullable=False)
    # [DEPRECATED 2026-05-25] 이전 C1 — 미사용
    fixed_ss_price = Column(Integer)
    fixed_cp_price = Column(Integer)

    # ★ 제품 이미지 (박스히어로 1:1)
    image_url = Column(String(500))

    # 르무통 공홈 한정 사이즈
    lemouton_only = Column(Boolean, default=False, nullable=False)

    # [B] 옵션 단위 오버라이드
    option_ss_price_override = Column(Integer)
    option_coupang_price_override = Column(Integer)
    use_margin_formula_option = Column(Boolean, default=False)

    # [E] 옵션 단위 템플릿 오버라이드 + 마켓 노출
    price_template_id_override = Column(Integer, ForeignKey("price_templates.id"))
    market_visible_ss = Column(Boolean, default=True)
    market_visible_coupang = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    model = relationship("Model", back_populates="options")

    __table_args__ = (
        Index("ix_options_model_color", "model_code", "color_code"),
        Index("ix_options_boxhero_sku", "boxhero_sku"),
    )


class ColorDict(Base):
    """색상 정규화 사전."""
    __tablename__ = "color_dict"

    color_code = Column(String(32), primary_key=True)
    variants_json = Column(Text, nullable=False)
    note = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DiscoveryQueueItem(Base):
    """미매핑 큐 — 자동 디스커버리에서 발견된 신규 후보."""
    __tablename__ = "discovery_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(32), nullable=False)
    raw_text = Column(Text, nullable=False)
    raw_payload_json = Column(Text)
    suggested_model_code = Column(String(64))
    suggested_color_code = Column(String(32))
    suggested_size_code = Column(String(32))
    confidence = Column(Float)
    status = Column(String(16), default="pending", nullable=False)
    resolved_canonical_sku = Column(String(128))
    note = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime)


class MarketRegistry(Base):
    """마켓 마스터 — 가격설정 → 크롤 영역의 마켓 동적 N개 지원 (2026-05-24).

    기본 2개: 스마트스토어(smartstore), 쿠팡(coupang). 사용자가 11번가/G마켓 등 추가 가능.
    판매자계정 페이지에서 관리 (이름/색/약식 글자 모두 수기 변경).

    로고 규칙 (디폴트):
      한글 이름 → 앞 2글자 (예: 스마트스토어 → '스마')
      영문 이름 → 앞 2글자 소문자 (예: SSG → 'ss')
      디폴트가 마음에 안 들면 logo_letter 직접 수정 가능.
    """
    __tablename__ = "market_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_key = Column(String(40), nullable=False, unique=True, index=True)
    label = Column(String(80), nullable=False)            # '스마트스토어', '쿠팡', ...
    logo_color = Column(String(20), nullable=False, default='#3B82F6')   # 헥스 컬러
    logo_letter = Column(String(8), nullable=False, default='?')         # 박스 안 글자 (2자)
    sort_order = Column(Integer, default=100, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_builtin = Column(Boolean, default=False, nullable=False)  # smartstore/coupang = True (삭제 불가)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class BundleRun(Base):
    """모음전 단위 실행 이력.

    phase = 'full' | 'crawl' | 'upload'
    crawl 일 때 details_json.sources = {<source_key>: {ok, items_crawled, error, ...}}
    upload 일 때 details_json.markets = {<market_key>: {ok, uploaded, skipped, failed, error}}
    full 일 때 둘 다 포함.

    model_code = NULL 이면 전체 실행 (예: '전체 크롤링 실행' 토글바 버튼).
    """
    __tablename__ = "bundle_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_code = Column(String(64), index=True)  # NULL = bulk
    phase = Column(String(16), nullable=False)
    triggered_by = Column(String(32), default="manual", nullable=False)
    started_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime)
    status = Column(String(16), default="running", nullable=False)
    details_json = Column(Text)
    error = Column(Text)

    __table_args__ = (
        Index("ix_bundle_runs_started_at", "started_at"),
        Index("ix_bundle_runs_model_phase", "model_code", "phase"),
    )


# ════════════════════════════════════════════════════════════
#  소싱처별 동적 혜택 (v8 A1+B1+C4 — 2026-05-11)
# ════════════════════════════════════════════════════════════

class SourceBenefitTemplate(Base):
    """소싱처별 기본 혜택 템플릿 (사이트 단위 default).

    혜택 = 이름 + 타입(rate/amount) + 값. 사용자가 동적으로 add/delete.
    적용 범위: 그 사이트의 모든 옵션 (옵션별 override 없을 때).

    누적 차감식: 판매가 → 항목별 enabled 차감 → 매입가
    """
    __tablename__ = "source_benefit_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, nullable=False, index=True)  # source_registry.id
    benefit_name = Column(String(120), nullable=False)
    benefit_type = Column(String(10), nullable=False, default='rate')  # 'rate' | 'amount'
    value = Column(Float, nullable=False, default=0.0)  # rate: 0.01 = 1% / amount: 5000 = 5,000원
    # 2026-06-05: 표시 카테고리 — '정액'|'정률'|'결제'|'캐시백'|'기타' (NULL=이름/타입 휴리스틱 자동분류)
    category = Column(String(16))
    # 2026-06-08: 혜택 태그 (최종 매입가 계산 엔진 M2a)
    apply_mode = Column(String(16))   # preapplied|deduct|accrue|payment|cashback (NULL=미분류→category 휴리스틱)
    pay_method = Column(String(16))   # affiliate_card|naver_pay|other_pay (payment 혜택만, NULL=미지정)
    channel = Column(String(16))      # naver_via|normal (NULL=normal)
    enabled = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        Index("ix_sbt_source_sort", "source_id", "sort_order"),
    )


class SourcingSource(Base):
    """[v6 P5.5] 사용자가 추가한 신규 소싱처 메타 (시안 A — 메타 등록).

    기본 5개 (lemouton/musinsa/ssf/lotteon/ss_lemouton) 외 사용자가 직접 추가하는 소싱처.
    어댑터 코드 없이도 URL 만 저장 가능 — 추후 어댑터 작성 시 자동 활성화.
    """
    __tablename__ = "sourcing_sources"
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_key = Column(String(40), nullable=False, unique=True, index=True)  # 'ssg', '29cm' 등
    label = Column(String(80), nullable=False)  # 'SSG.COM', '29CM' 등
    domain = Column(String(120), nullable=False)  # 'ssg.com'
    logo_color = Column(String(20))  # '#E53935'
    logo_letter = Column(String(4))  # 'S' (썸네일 letter)
    favicon_url = Column(String(500))  # 자동 추출 favicon URL
    needs_login = Column(Boolean, nullable=False, default=False)
    has_adapter = Column(Boolean, nullable=False, default=False)  # 어댑터 작성 후 True
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, default=100)  # 기본 5개는 1~5, 추가분은 100+
    created_by = Column(String(120))  # 추가한 사용자 email
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class OptionBenefitOverride(Base):
    """옵션별 혜택 override — 특정 옵션 / 사이트 조합에서 템플릿 대체.

    is_template_inherited=True 면 템플릿 항목 그대로 (값 변경만), False 면 옵션 단독 신규 항목.
    """
    __tablename__ = "option_benefit_overrides"
    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_sku = Column(String(64), nullable=False, index=True)
    source_id = Column(Integer, nullable=False)
    template_id = Column(Integer)  # SourceBenefitTemplate.id (NULL = 옵션 단독 신규)
    benefit_name = Column(String(120), nullable=False)
    benefit_type = Column(String(10), nullable=False, default='rate')
    value = Column(Float, nullable=False, default=0.0)
    # 2026-06-05: 표시 카테고리 — '정액'|'정률'|'결제'|'캐시백'|'기타' (NULL=휴리스틱 자동분류)
    category = Column(String(16))
    # 2026-06-08: 혜택 태그 (최종 매입가 계산 엔진 M2a)
    apply_mode = Column(String(16))   # preapplied|deduct|accrue|payment|cashback (NULL=미분류→category 휴리스틱)
    pay_method = Column(String(16))   # affiliate_card|naver_pay|other_pay (payment 혜택만, NULL=미지정)
    channel = Column(String(16))      # naver_via|normal (NULL=normal)
    enabled = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        Index("ix_obo_sku_source", "canonical_sku", "source_id"),
    )


# ════════════════════════════════════════════════════════════
#  단계형 옵션 — 단계 설계 (Phase 2, ai-workflow cycle 20260521)
# ════════════════════════════════════════════════════════════

class BundleOptionStep(Base):
    """모음전 단계형 옵션 — 단계 설계.

    1 모음전(Model) = 1~3개 단계. 각 단계 = 이름(자유) + 값 목록(JSON).
    옵션ID(canonical_sku)는 단계 값들의 조합으로 생성
    (lemouton.sourcing.option_combo.generate_combinations).

    예: 모음전 'AF' → 단계1 '색상'(["블랙","화이트"]) · 단계2 '사이즈'(["250","260"])
        → 옵션 4개: AF-블랙-250 / AF-블랙-260 / AF-화이트-250 / AF-화이트-260

    axis_name 은 자유 — 색상·사이즈·모델뿐 아니라 재질·패턴 등 임의.
    신규 테이블이라 create_all 이 자동 생성 (Alembic 불요).
    """
    __tablename__ = "bundle_option_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_code = Column(String(64), ForeignKey("models.model_code"),
                        nullable=False, index=True)
    step_no = Column(Integer, nullable=False)            # 1 | 2 | 3
    axis_name = Column(String(64), nullable=False)       # '색상' '사이즈' '모델' '재질' ...
    values_json = Column(Text, nullable=False, default='[]')   # ["블랙","화이트", ...]
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("model_code", "step_no", name="uq_bundle_option_steps"),
        Index("ix_bundle_option_steps_model", "model_code"),
    )


# ════════════════════════════════════════════════════════════
#  Phase 4 (2026-05-28) — 모음전 옵션 ↔ 재고관리 옵션 매핑
# ════════════════════════════════════════════════════════════

class OptionInventoryLink(Base):
    """모음전 매트릭스 옵션 ↔ 재고관리 옵션 N:N 매핑.

    [2026-05-28] Phase 4 (B3-3 + E2 누적 색·도트):
      - 모음전 옵션 (model_code != '단독_%') 은 매트릭스 셀
      - 재고관리 옵션 (model_code = '단독_%' 또는 별도 재고 SKU) 은 실재고
      - 한 모음전 셀에 N개 재고 SKU 매핑 가능 (예: 사이즈 묶음 판매)
      - 한 재고 SKU 가 여러 모음전에 등장 가능 (예: 빨강 운동화 = 봄·여름 모음전)

    UNIQUE(bundle_sku, inventory_sku) — 중복 매핑 차단.
    옵션 삭제 시 CASCADE.
    """
    __tablename__ = "option_inventory_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bundle_option_sku = Column(
        String(128),
        ForeignKey("options.canonical_sku", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inventory_option_sku = Column(
        String(128),
        ForeignKey("options.canonical_sku", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint(
            "bundle_option_sku", "inventory_option_sku",
            name="uq_option_inventory_link",
        ),
        Index(
            "ix_oil_inventory_bundle",
            "inventory_option_sku", "bundle_option_sku",
        ),
    )


# ════════════════════════════════════════════════════════════
#  다중 워커 크롤 시스템 (2026-06-06) — 서버는 트리거(잡 등록)만 하고,
#  실제 크롤은 팀 로컬 PC 워커가 실행한다. 설계: docs/crawl-worker-system.md
#  배경: 라이브 검증 결과 서버 직접 크롤로 무신사(로그인)·롯데온(playwright) 실패.
# ════════════════════════════════════════════════════════════

class CrawlWorker(Base):
    """등록된 팀 크롤 PC(워커).

    식별자 = name(별명, 중복 불가). 우선순위는 낮을수록 먼저(priority ASC).
    online 판정 = last_heartbeat_at 이 HEARTBEAT_ONLINE_SEC(기본 90초) 이내.
    logins_json = 이 PC 가 크롤 가능한(로그인 보유) 소싱처 키 목록 ["musinsa", ...].
    ip_address = 선택. 등록 시 그 IP 에서 '전체 크롤' 누르면 자동으로 이 PC 를
                 '내 PC' 로 인식(미등록이면 수동 선택).
    """
    __tablename__ = "crawl_workers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False, unique=True)   # 별명 = 식별자
    owner = Column(String(120))                               # 소유 팀원
    enabled = Column(Boolean, default=True, nullable=False)   # 활성/비활성 토글
    priority = Column(Integer, default=100, nullable=False)   # 낮을수록 먼저
    logins_json = Column(Text, default="[]")                  # 보유 로그인 목록
    ip_address = Column(String(64))                           # 선택 — 내 PC 자동인식
    last_heartbeat_at = Column(DateTime)                      # ON/OFF 판정
    app_version = Column(String(32))
    note = Column(String(255))
    registered_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_crawl_workers_priority", "priority"),
    )


class CrawlJob(Base):
    """크롤 잡 큐. 서버(스케줄러/버튼)가 등록(pending), 워커가 원자적 선점·실행.

    status:  pending → claimed → running → done | failed | expired | canceled
    routing: 'queue'(우선순위 경쟁) | 'pinned'(assigned_worker 전용 — 수동 '내 PC')
    required_login: 이 잡 크롤에 로그인이 꼭 필요한 소싱처(예 'musinsa'). 그 로그인
        보유 워커만 선점. NULL = 아무 워커나.
    lease_expires_at: 선점 후 이 시각까지 하트비트 갱신 없으면 잡 회수(pending) —
        워커 PC 가 크롤 중 꺼져도 다른 PC 가 이어받게 함(좀비 'running' 방지).
    """
    __tablename__ = "crawl_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_code = Column(String(64), index=True)               # NULL = 전체 번들
    verify_url = Column(String(512))   # phase="verify" 단건 검증 잡의 대상 URL (NULL=일반 크롤)
    phase = Column(String(16), default="crawl", nullable=False)
    status = Column(String(16), default="pending", nullable=False)
    routing = Column(String(16), default="queue", nullable=False)
    required_login = Column(String(32))                       # 'musinsa' 등 / NULL
    priority = Column(Integer, default=100, nullable=False)   # 잡 우선순위(작을수록 먼저)
    assigned_worker = Column(String(120))                     # pinned 대상 별명
    worker_name = Column(String(120), index=True)             # 실제 선점한 워커
    attempts = Column(Integer, default=0, nullable=False)
    triggered_by = Column(String(32), default="manual", nullable=False)
    claimed_at = Column(DateTime)
    lease_expires_at = Column(DateTime)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    result_json = Column(Text)                                # 소싱처별 결과 요약
    error = Column(Text)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_crawl_jobs_status", "status"),
        Index("ix_crawl_jobs_lease", "lease_expires_at"),
        Index("ix_crawl_jobs_created", "created_at"),
        Index("ix_crawl_jobs_dispatch", "status", "priority", "created_at"),
    )
