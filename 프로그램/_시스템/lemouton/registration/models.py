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
