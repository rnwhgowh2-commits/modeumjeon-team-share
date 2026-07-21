# -*- coding: utf-8 -*-
"""대량등록 — 마켓 공통 상품 그릇.

Alembic 없음 — shared/db.py:init_db() 의 Base.metadata.create_all 이 생성한다.
create_all 은 기존 테이블에 컬럼을 추가하지 않으므로, Phase 2~3 에서 쓸 컬럼까지
처음부터 선언한다. 나중에 늘리려면 shared/db.py 의 migrations 리스트를 써야 한다.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Boolean, Text, DateTime, ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ProductDraft(Base):
    """마켓 공통 상품 1건. 크롤이 채우든(Phase 3) 사람이 채우든(Phase 1A) 같은 그릇."""
    __tablename__ = "product_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 등록경로 — 주문·CS 「등록경로」 필터의 근거. 'bulk'(대량등록) | 'bundle'(모음전)
    origin = Column(String(16), default='bulk', nullable=False)
    # 채운 주체 — 'manual'(수기) | 'crawl'(소싱처 크롤, Phase 3)
    source = Column(String(16), default='manual', nullable=False)
    # 모음전 상품에서 온 경우 연결 (없으면 NULL)
    model_code = Column(String(64))

    name = Column(String(255), nullable=False)
    brand = Column(String(120))
    sale_price = Column(Integer, nullable=False)      # 원. 1A 는 사람이 입력. 1B 에서 마진엔진이 채움
    normal_price = Column(Integer)                    # 정가(할인 전). 미입력 시 마켓 기본
    stock_quantity = Column(Integer, default=0)       # 옵션 없는 상품용 평면 재고

    # 상품고시정보 — 'WEAR'|'SHOES'|'BAG'|'FASHION_ITEMS'
    notice_type = Column(String(32), default='WEAR', nullable=False)
    notice_json = Column(Text, default='{}')          # {필드명: 값} — notice.py 가 해석

    images_json = Column(Text, default='[]')          # ["https://...", ...] 원본(업로드 전)
    cdn_images_json = Column(Text, default='[]')      # 스스 업로드 후 CDN URL
    detail_html = Column(Text, default='')

    options_json = Column(Text, default='[]')         # [{color,size,stock,extra_price,sku}]

    origin_area_code = Column(String(32), default='0200037')  # 국내산 기본
    importer = Column(String(120), default='')
    delivery_fee = Column(Integer, default=3000)      # 0 = 무료배송
    return_fee = Column(Integer, default=5000)

    # 스스 detailAttribute 필수 — 라이브 검증된 create_product.py:85-89 payload 에 있음
    minor_purchasable = Column(Boolean, default=True, nullable=False)
    after_service_phone = Column(String(32), default='')
    # 스스 afterServiceGuideContent — 실제 반품·교환 안내문은 255자를 넘는다.
    # String(255) 면 Postgres(개발·라이브)에서 StringDataRightTruncation 로 저장 실패.
    # (SQLite 는 VARCHAR 길이를 무시해 테스트로는 절대 안 잡힘) → Text 필수.
    after_service_guide = Column(Text, default='')

    # ── 매입가·마진 입력 (Phase 1B M2-저장) ──────────────────────────────────
    #   화면 「6 매입가·마진」 6칸의 저장소. 크롤로 못 가져오는 **운영 사실**이라
    #   사람이 고른 값을 그대로 보관한다. 계산은 저장하지 않는다 — 소싱처 혜택이
    #   바뀌면 옛 금액이 되므로, 금액은 매번 엔진(compute_final_price)이 다시 낸다.
    #
    #   ★ 전부 nullable, 기본값 없음. '안 고름'과 '없음'은 다른 뜻이다:
    #       NULL  = 그 칸을 아예 입력받지 않았다 (예: 옛 드래프트)
    #       ''    = 화면에서 「소싱처 기본값」으로 남겨뒀다 (= 아무것도 덮지 않음)
    #       'none'= 「없음」을 명시적으로 골랐다 (= 그 축의 혜택을 전부 끈다)
    #     여기에 default 를 걸면 셋이 한 값으로 뭉개져, 나중에 사장님이 의도적으로
    #     비운 것인지 프로그램이 채운 것인지 영영 알 수 없게 된다.
    pricing_source_id = Column(Integer)          # SourceRegistry.id (혜택 템플릿의 주인)
    surface_price = Column(Integer)              # 소싱처 표면 노출가(원). 0 과 NULL 은 다르다
    # 폭 근거 — 최장값 'naver_via'(9자). 후보가 코드 상수(INFLOW_CHOICES)라 늘 짧다.
    pricing_inflow = Column(String(16))          # ''|'naver_via'|'cashback'|'none'
    # 폭 근거 — PurchaseCard.key 와 **같은 String(64)**. 카드표에 저장될 수 있는 키는
    #   여기에도 반드시 들어가야 한다(더 좁으면 라이브 PostgreSQL 에서만 잘린다).
    #   실사용 키는 pay_method VARCHAR(16) 제약 때문에 16자 이하다
    #   (tests/margin/test_purchase_card.py::test_seed_keys_fit_pay_method_column).
    pricing_card_key = Column(String(64))        # PurchaseCard.key | 'none' | ''
    pricing_naver_pay = Column(String(16))       # ''|'on'|'off'
    # 폭 근거 — SourceBenefitTemplate.benefit_name 과 **같은 String(120)**.
    #   값이 그 컬럼에서 그대로 온다(캐시백 항목명 택1). 좁히면 긴 항목명이 잘린다.
    pricing_cashback_name = Column(String(120))  # benefit_name | 'none' | ''

    # 상품별 업데이트 ON/OFF (Phase 2 상품관리 탭). 컬럼은 지금 만든다.
    update_product = Column(Boolean, default=True, nullable=False)
    update_price = Column(Boolean, default=True, nullable=False)
    update_stock = Column(Boolean, default=True, nullable=False)

    # 'draft' | 'registering' | 'done' | 'failed'
    status = Column(String(16), default='draft', nullable=False)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(DateTime)

    markets = relationship("ProductDraftMarket", back_populates="draft",
                           cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_product_drafts_origin_status", "origin", "status"),
        Index("ix_product_drafts_model_code", "model_code"),
    )


class ProductDraftMarket(Base):
    """드래프트 × 마켓 — 마켓별 카테고리·판매가·등록결과."""
    __tablename__ = "product_draft_markets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(Integer, ForeignKey("product_drafts.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    market = Column(String(32), nullable=False)       # 'smartstore' | 'coupang' | ...
    # [2026-07-17] 마켓당 다계정(롯데온 7계정 등) — 같은 드래프트를 계정 A·B 에 각각 등록하면
    # 마켓 상품번호가 계정마다 다르다. account_key 없이 (draft_id, market) 만 유니크면 B 등록이
    # A 의 market_product_id 를 덮어써 Phase 2 업데이트가 엉뚱한 스토어로 나간다(금전 손실).
    # nullable=False + 'default' 센티넬 — NULL 이면 유니크 제약이 무력화(NULL≠NULL)되므로.
    # (sets/models.py SetChannel 관례 동일). Phase 1A 는 단일계정 → 전부 'default'.
    account_key = Column(String(64), nullable=False, default="default")

    category_code = Column(String(64))                # 스스 leafCategoryId / 쿠팡 displayCategoryCode
    # 마켓별 판매가. Phase 1B 마진엔진이 채운다 — 1A 에서는 미배선(draft.sale_price 사용)
    sale_price = Column(Integer)

    # 'pending' | 'ok' | 'failed' | 'blocked'('blocked' = LIVE_REGISTER_ARMED 게이트 차단)
    status = Column(String(16), default='pending', nullable=False)
    market_product_id = Column(String(64))            # 스스 originProductNo / 쿠팡 sellerProductId
    error_code = Column(String(64))
    error_message = Column(Text)
    raw_json = Column(Text)                           # 마켓 원응답 (디버깅·감사)
    registered_at = Column(DateTime)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    draft = relationship("ProductDraft", back_populates="markets")

    __table_args__ = (
        UniqueConstraint("draft_id", "market", "account_key",
                         name="uq_product_draft_markets_draft_market_account"),
    )


class MarketCategory(Base):
    """판매처 마켓 카테고리 사전 — 6마켓 전수 수집 스냅샷 (스펙 2026-07-22 §A).

    재수집 시 사라진 코드는 지우지 않고 removed_at 마킹(맵핑 재확정 강등의 근거).
    """
    __tablename__ = 'market_categories'

    id = Column(Integer, primary_key=True)
    market = Column(String(20), nullable=False, index=True)   # smartstore|coupang|auction|gmarket|eleven11|lotteon
    code = Column(String(40), nullable=False)                 # 마켓 카테고리 코드 (ESM 은 site-cat 코드)
    name = Column(String(200), nullable=False)
    full_path = Column(String(500), nullable=False)           # '패션잡화>운동화>여성운동화' (구분자 '>')
    parent_code = Column(String(40))                          # 루트는 None
    depth = Column(Integer, nullable=False, default=1)
    is_leaf = Column(Boolean, nullable=False, default=False)
    extra_code = Column(String(40))                           # ESM: 짝 ESM표준(sd) 코드. 그 외 None
    raw_json = Column(Text)                                   # 마켓 응답 원문 조각 (버리지 않는다)
    harvested_at = Column(DateTime, nullable=False)           # 마지막으로 존재 확인된 수집 시각
    removed_at = Column(DateTime)                             # 재수집에서 사라진 시각 (None=현존)

    __table_args__ = (
        UniqueConstraint('market', 'code', name='uq_market_categories_market_code'),
    )


class MarketCategoryHarvestRun(Base):
    """마켓별 카테고리 전수 수집(harvest) 실행 상태 — 프로세스가 아닌 DB 가 진실 원천.

    [2026-07-22] 라이브 배포는 gunicorn `--workers 3`(OS 프로세스 3개)이다. 이전 구현은
    이 상태를 모듈 레벨 dict + threading.Lock 으로 들고 있었는데, 그건 프로세스 로컬이라
    ①같은 마켓 중복실행 방지(409)가 워커 간에 안 먹히고 ②GET status 폴링이 harvest 를
    돌린 워커가 아닌 다른 워커에 떨어지면 running=False·낡은 결과로 보인다(결과 증발처럼
    보이는 버그 재현 가능). 그래서 이 실행 상태를 테이블로 옮긴다 — 어느 워커가 요청을
    받아도 같은 행을 보고 같은 답을 준다.

    advisory lock(webapp/routes/api.py:pg_advisory_xact_lock 참조)은 쓰지 않는다 — 그건
    트랜잭션 수명(커밋/롤백까지)만 유효한데, harvest 는 수 분짜리 백그라운드 스레드라
    트랜잭션을 그렇게 오래 열어 둘 수 없다. 대신 행 자체를 "누가 실행 중"의 표식으로 쓰고
    `with_for_update()` 로 클레임을 원자적으로 만든다.

    스테일 회수: `running=True` 인데 `started_at` 이 30분을 넘겼으면 죽은 실행으로 보고
    새 POST 가 회수한다(워커 재시작으로 데몬 스레드가 함께 죽으면 running=True 로 영영
    남는 케이스 대비 — 데몬 스레드는 종료 시 자기 상태를 못 정리한다).
    """
    __tablename__ = 'category_harvest_runs'

    market = Column(String(20), primary_key=True)
    running = Column(Boolean, nullable=False, default=False)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    summary_json = Column(Text)
    error = Column(Text)
