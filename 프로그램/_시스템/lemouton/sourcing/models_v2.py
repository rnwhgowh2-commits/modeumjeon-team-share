"""V2 스키마 — 소싱 ↔ 모음전 분리 + 멀티 계정.

설계 (사용자 결정):
  · 소싱 (계정 무관, 1회만 크롤링) → ``sourcing_profiles`` × ``sourcing_options``
  · 업로드 (계정별, 같은 소싱을 N번 등록) → ``bundle_sets`` × ``bundle_products`` × ``bundle_options``
  · 인증 분리:
       - ``upload_accounts``: 마켓 셀러 계정 (스마트스토어/쿠팡)
       - ``sourcing_accounts``: 소싱처 회원 로그인 (무신사/SSF)
  · 옵션 라벨 동적 정의 (``option_labels`` JSON): 신발은 색상/사이즈, 의류는 카테고리/색상/사이즈
  · 스크린샷 가격 캡처 (``screenshot_paths`` JSON): 가격 형성 검증

기존 ``models.py`` 의 ``Model`` / ``Option`` 은 ``v1`` 으로 유지 (마이그레이션 후 deprecated).
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Boolean, ForeignKey, Float, Text,
    DateTime, JSON, Index, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from shared.db import Base


# ════════════════════════════════════════════════════════════
#  SOURCING LAYER (계정 무관)
# ════════════════════════════════════════════════════════════

class SourcingProfile(Base):
    """소싱 프로파일 — 1행 = 1 르무통 모델 (계정 무관, 크롤은 1번만)."""
    __tablename__ = "sourcing_profiles"

    profile_code = Column(String(64), primary_key=True)        # "메이트"
    brand = Column(String(100), default="르무통", nullable=False)
    model_name_raw = Column(String(255), nullable=False)
    model_name_display = Column(String(255))
    category = Column(String(100))                             # "신발" | "의류" | "가방"

    # 동적 옵션 라벨: {"1": "색상", "2": "사이즈"} 또는 {"1": "카테고리", "2": "색상", "3": "사이즈"}
    option_labels = Column(JSON, default=lambda: {"1": "색상", "2": "사이즈"})

    # 5 소싱처 URL
    url_lemouton = Column(Text)
    url_musinsa = Column(Text)
    url_ssf = Column(Text)
    url_lotteon = Column(Text)
    url_ss_lemouton = Column(Text)

    note = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    options = relationship("SourcingOption", back_populates="profile", cascade="all, delete-orphan")


class SourcingOption(Base):
    """소싱 옵션 — 1행 = 1 캐노니컬 SKU (계정 무관)."""
    __tablename__ = "sourcing_options"

    canonical_sku = Column(String(128), primary_key=True)
    profile_code = Column(String(64), ForeignKey("sourcing_profiles.profile_code"), nullable=False)

    # 동적 옵션 (라벨은 SourcingProfile.option_labels 가 결정)
    option1 = Column(String(64), nullable=False, default="")    # 예: 색상값
    option2 = Column(String(64), nullable=False, default="")    # 예: 사이즈값
    option3 = Column(String(64), nullable=False, default="")    # 예: 추가 옵션
    option1_display = Column(String(128))                       # UI 노출용
    option2_display = Column(String(128))
    option3_display = Column(String(128))

    # 소싱처별 옵션 ID (NULL 가능)
    option_id_lemouton = Column(String(128))
    option_id_musinsa = Column(String(128))
    option_id_ssf = Column(String(128))
    option_id_lotteon = Column(String(128))
    option_id_ss_lemouton = Column(String(128))

    boxhero_sku = Column(String(64))
    lemouton_only = Column(Boolean, default=False, nullable=False)

    # 가격 형성 검증용 — {"musinsa": "data/screenshots/sku_musinsa_20260427.png", ...}
    screenshot_paths = Column(JSON, default=dict)

    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    profile = relationship("SourcingProfile", back_populates="options")

    __table_args__ = (
        Index("ix_sourcing_options_profile_opt", "profile_code", "option1", "option2"),
        Index("ix_sourcing_options_boxhero", "boxhero_sku"),
    )


class SourcingAccount(Base):
    """소싱처 회원 로그인 계정 — Playwright storage_state 다중 관리.

    예:
      source="무신사", account_key="default" → data/auth/무신사_default.json
      source="무신사", account_key="seller_b" → data/auth/무신사_seller_b.json
    """
    __tablename__ = "sourcing_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(32), nullable=False)                # "무신사" | "SSF샵" | "르무통"
    account_key = Column(String(64), nullable=False)           # "default" | "seller_b"
    display_name = Column(String(128))                         # "무신사 셀러A 회원"
    session_path = Column(Text)                                # 절대경로 (파일 존재 여부와 별개)
    last_login_at = Column(DateTime)
    expires_at = Column(DateTime)
    is_active = Column(Boolean, default=True, nullable=False)
    is_default_for_crawl = Column(Boolean, default=False, nullable=False)  # ★ 소싱처별 1개만 True
    note = Column(Text)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("source", "account_key", name="uq_sourcing_accounts_source_key"),
    )


class SourcingCredential(Base):
    """소싱처 회원 로그인 ID/PW — DB 영구 저장.

    [2026-06-05] 기존 파일(``data/sourcing_credentials.json``)은 서버 배포 때마다
    ``rm -rf ~/app`` + tar ``--exclude=data`` 로 통째 삭제돼 계정이 사라졌다.
    → DB(Supabase)로 이전해 배포와 무관하게 영구 보존. (파일 store 와 동일 인터페이스)

    구조: (source, account_key) → {login_id, login_pw, login_method}
    ※ login_pw 는 현재 평문(기존 파일과 동일 수준). 추후 env 키 기반 암호화 권장.
    """
    __tablename__ = "sourcing_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(32), nullable=False)            # "musinsa" | "ssf" | ...
    account_key = Column(String(64), nullable=False)       # "default" | "영빈" | ...
    login_id = Column(Text, nullable=False)
    login_pw = Column(Text, nullable=False)
    login_method = Column(String(16), default="direct", nullable=False)  # direct | manual | naver | kakao

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("source", "account_key", name="uq_sourcing_credentials_source_key"),
    )


# ════════════════════════════════════════════════════════════
#  UPLOAD LAYER (계정별)
# ════════════════════════════════════════════════════════════

class UploadAccount(Base):
    """업로드 계정 — 마켓 셀러 (스마트스토어/쿠팡).

    시크릿은 ``.env`` 의 ``{env_prefix}_*`` 패턴으로 로드 — DB 에는 절대 저장 X.
    """
    __tablename__ = "upload_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_key = Column(String(64), unique=True, nullable=False)   # "르무통_본계_smartstore"
    display_name = Column(String(128), nullable=False)              # "르무통 본계 스마트스토어"
    market = Column(String(20), nullable=False)                     # "smartstore" | "coupang"
    env_prefix = Column(String(64), nullable=False)                 # "SMARTSTORE_MAIN"
    is_active = Column(Boolean, default=True, nullable=False)
    note = Column(Text)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    bundle_sets = relationship("BundleSet", back_populates="upload_account",
                               cascade="all, delete-orphan")


class BundleSet(Base):
    """모음전 (페이지) — 1행 = 1 마켓 등록 단위.

    하나의 BundleSet 은 1 업로드 계정에 등록되며, N개의 BundleProduct 를 포함할 수 있다
    (단일 상품 모음전이면 N=1, 다상품 모음전이면 N>1).
    """
    __tablename__ = "bundle_sets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    upload_account_id = Column(Integer, ForeignKey("upload_accounts.id"), nullable=False)
    name = Column(String(255), nullable=False)                       # "메이트 단독" | "여름 운동화 모음전"
    market_product_id = Column(String(64))                           # 등록 결과 (네이버/쿠팡 상품번호)
    product_name_override = Column(String(255))                      # 마켓 노출 상품명

    margin_rate = Column(Float, default=0.15)                        # 목표 마진율
    platform_fee = Column(Float, default=0.055)                      # 마켓 수수료율
    auto_interval_min = Column(Integer, default=30)                  # 자동 갱신 주기 (분)

    # 기존 Model 의 오버라이드 컬럼 (모음전 단위로 이동)
    boxhero_purchase_price_override = Column(Integer)
    market_price_override = Column(Integer)
    coupang_winner_premium_override = Column(Integer)
    guardrail_lower_override = Column(Integer)
    guardrail_upper_override = Column(Integer)
    external_margin_mode_override = Column(String(16))
    external_margin_value_override = Column(Float)
    use_margin_formula = Column(Boolean, default=False)

    # 템플릿 매핑
    price_template_id = Column(Integer, ForeignKey("price_templates.id"))
    color_template_id = Column(Integer, ForeignKey("color_templates.id"))
    size_template_id = Column(Integer, ForeignKey("size_templates.id"))

    is_active = Column(Boolean, default=True, nullable=False)
    note = Column(Text)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    upload_account = relationship("UploadAccount", back_populates="bundle_sets")
    products = relationship("BundleProduct", back_populates="bundle_set",
                            cascade="all, delete-orphan")


class BundleProduct(Base):
    """모음전 내 개별 상품 — 1행 = (BundleSet 내 1 SourcingProfile 사용)."""
    __tablename__ = "bundle_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bundle_set_id = Column(Integer, ForeignKey("bundle_sets.id"), nullable=False)
    profile_code = Column(String(64), ForeignKey("sourcing_profiles.profile_code"), nullable=False)

    product_group_name = Column(String(255), nullable=False)         # "메이트"
    product_name_override = Column(String(255))                      # 마켓 노출용 (없으면 profile 기본)
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    bundle_set = relationship("BundleSet", back_populates="products")
    profile = relationship("SourcingProfile")
    options = relationship("BundleOption", back_populates="bundle_product",
                           cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("bundle_set_id", "profile_code",
                         name="uq_bundle_products_set_profile"),
    )


class BundleOption(Base):
    """모음전 내 옵션 — 1행 = (BundleProduct 의 1 SourcingOption 에 대한 계정별 오버라이드)."""
    __tablename__ = "bundle_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bundle_product_id = Column(Integer, ForeignKey("bundle_products.id"), nullable=False)
    canonical_sku = Column(String(128), ForeignKey("sourcing_options.canonical_sku"), nullable=False)

    market_option_id = Column(String(128))                  # 마켓 등록 후 결과
    option_price_override = Column(Integer)
    use_margin_formula_option = Column(Boolean, default=False)
    market_visible = Column(Boolean, default=True, nullable=False)

    # 옵션 단위 템플릿 오버라이드
    price_template_id_override = Column(Integer, ForeignKey("price_templates.id"))
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    bundle_product = relationship("BundleProduct", back_populates="options")
    sourcing_option = relationship("SourcingOption")

    __table_args__ = (
        UniqueConstraint("bundle_product_id", "canonical_sku",
                         name="uq_bundle_options_product_sku"),
    )
