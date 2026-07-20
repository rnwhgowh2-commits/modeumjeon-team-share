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

    # ── 라이브 검증(실주문 조회 왕복 확인) ──
    # 판매처관리에서 「🧪 라이브 검증」으로 실제 주문을 불러오고, 사장님이 마켓 화면과
    # 대조해 「맞음」을 누른 시각. 이 값이 있어야 그 계정이 '검증됨'이다.
    # 마켓 공개 여부는 order_export.supported_markets() 가 이 컬럼으로 판단한다
    # (그 마켓 활성 계정이 1개 이상 + 전부 검증됨 → 공개). 미검증 마켓 숫자는 화면에 안 나온다.
    live_verified_at = Column(DateTime)
    live_verified_count = Column(Integer)      # 검증 당시 조회된 주문 건수(0 도 유효한 기록)

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


# ════════════════════════════════════════════════════════════
#  INVOICE LEDGER — 송장 원장 (마켓이 나중에 번호를 빼먹어도 잃지 않게)
# ════════════════════════════════════════════════════════════

class InvoiceLedger(Base):
    """한 번 본 송장번호를 영구 보관.

    배경: 11번가는 주문이 '구매확정'으로 넘어가면 어떤 목록 API로도 송장번호(invcNo)를
    돌려주지 않는다(배송중·배송완료 목록엔 있으나 상태 전이 후 빠짐, 2026-07-10 실측).
    → 배송중·배송완료 때 본 송장번호를 여기 저장해두면, 구매확정으로 넘어가 API가
    번호를 빼먹어도 우리 저장분에서 채워 '확인 불가'를 면한다. 모든 마켓 공통 안전장치.
    """
    __tablename__ = "invoice_ledger"

    market = Column(String(32), primary_key=True)        # 판매처(쿠팡·11번가 등) — 화면 표기 그대로
    order_no = Column(String(128), primary_key=True)     # 오픈마켓주문번호
    invoice_no = Column(String(64), nullable=False)      # 송장번호(운송장번호)
    courier = Column(String(64))                         # 택배사(있으면)
    captured_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))


# ════════════════════════════════════════════════════════════
#  AUTO-CONFIRM SETTING — 「결제완료 → 배송준비중」 자동전환 ON/OFF (마켓·계정별)
# ════════════════════════════════════════════════════════════

class AutoConfirmSetting(Base):
    """마켓·계정 단위 자동전환 스위치(팀 공유 · 단일 진실 원천 = 계정 leaf).

    · 한 행 = (판매처, 쇼핑몰별칭) 계정 하나의 켜짐/꺼짐.
    · '전체'·'마켓별' 스위치는 저장하지 않고 leaf 들의 all-on/some/none 으로 파생한다
      (중복·모순 방지 — 마켓 스위치와 계정 스위치가 서로 다른 값을 갖는 사고를 원천 차단).
    · 기본값 = 꺼짐(행 없음). 실제 마켓 상태 변경은 별도 LIVE 스위치가 또 잠근다.
    · last_run_at/last_run_count = 마지막으로 이 계정에서 몇 건을 넘겼는지(화면 이력).
    """
    __tablename__ = "auto_confirm_settings"

    market = Column(String(32), primary_key=True)          # 판매처 슬러그(coupang·lotteon…)
    account_alias = Column(String(128), primary_key=True)  # 쇼핑몰별칭(계정 표시명). 마켓단일계정도 별칭.
    enabled = Column(Boolean, default=False, nullable=False)
    last_run_at = Column(DateTime)                         # 마지막 전환 실행 시각(KST 저장 안 함 — UTC)
    last_run_count = Column(Integer, default=0, nullable=False)  # 그때 넘긴 건수
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class AutoConfirmConfig(Base):
    """자동 실행(스케줄러) 전역 설정 — 단일 row(id=1). '켜두면 알아서' 마스터.

    · enabled = 자동 실행 ON/OFF. ★ON 이면 스케줄러가 실전환을 무인 실행한다(사용자가
      화면 스위치로 켬 = 실전환 arming). 되읽기 검증·계정별 대상·안전한 앞단계(발주확인)가 안전망.
    · interval_minutes = 몇 분마다(사용자 직접 입력, 1~180).
    · last_run_at = 스케줄러가 마지막으로 한 바퀴 돈 시각(다음 실행 계산 기준).
    """
    __tablename__ = "auto_confirm_config"

    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, default=False, nullable=False)
    interval_minutes = Column(Integer, default=5, nullable=False)
    last_run_at = Column(DateTime)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class AutoConfirmLog(Base):
    """전환 이력 — 언제·어느 마켓·계정에서 몇 건을 배송준비중으로 넘겼나(화면 타임라인용)."""
    __tablename__ = "auto_confirm_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ran_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    market = Column(String(32), nullable=False)
    account_alias = Column(String(128), nullable=False)
    count = Column(Integer, default=0, nullable=False)
    result = Column(String(16), nullable=False)   # sent|partial|failed|unsupported


class LotteonSettlement(Base):
    """롯데온 판매자센터 정산예정금액조회(크롤) 결과 — 주문 라인별 정산예정금액·판매경로.
    소스=soapi selectBgtSettleManagementList (pymtTgtAmt·slChNo). 로컬 크롬 크롤러가 수집→서버 push.
    미정산 주문에도 pymtTgtAmt 정확 → 마진계산기가 이 값을 정산예정금액으로 직접 사용(오차0).
    """
    __tablename__ = "lotteon_settlements"
    od_no = Column(String(30), primary_key=True)          # 오픈마켓주문번호
    od_seq = Column(String(10), primary_key=True, default="1")  # 주문순번(단품 라인)
    pymt_tgt_amt = Column(Integer, nullable=False)        # 지급대상금액(정산예정금액) 라인값
    sl_chnl = Column(String(20))                          # 판매경로 "제휴"/"롯데ON"
    tr_no = Column(String(20))                            # 계정(거래처번호)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    source = Column(String(12), default="manual", nullable=False)   # manual|auto
