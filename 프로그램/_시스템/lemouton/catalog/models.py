# -*- coding: utf-8 -*-
"""마켓 상품 캐시 3 테이블.

규모(2026-07-23 실측): 롯데온 140,171 · 11번가 ~91,000 · 쿠팡 29,244 ·
스마트스토어 9,555 · 옥션 4,673 · G마켓 4,987 = 약 28만 행.
Supabase 무료 500MB 중 현재 179MB 사용 → 인덱스 포함 약 170MB 예상.

★ 옵션은 여기 담지 않는다. 상품당 옵션 10개면 150만 행이 되어 한도를 넘는다.
  옵션은 사장님이 「모음전으로 담은」 상품만 2단계에서 저장한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, DateTime, ForeignKey, Index, UniqueConstraint,
)

from shared.db import Base


def _now():
    return datetime.now(timezone.utc)


class MarketProductGroup(Base):
    """내가 관리하는 상품 1건 — 여러 마켓 상품을 하나로 묶는 그릇.

    ★ ProductSet 을 쓰지 않는 이유: ProductSet.model_code 는 소싱처 모델
      (models.model_code)에 대한 nullable=False FK 다. 마켓에서 거꾸로 긁어온
      상품에는 소싱처 모델이 없다(더망고 쓰기 전 올린 것·마켓에서 직접 올린 것) —
      그게 이 기능이 존재하는 이유라 그 제약을 그대로 쓸 수 없다.
    """
    __tablename__ = "market_product_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)          # 대표 이름(사장님이 고침)
    brand = Column(String(120))
    #: 소싱처 모델이 있으면 채운다. 없어도 된다 — FK 를 걸지 않는 이유.
    model_code = Column(String(64))
    #: 나중에 ProductSet 과 이을 자리. 지금은 늘 NULL.
    set_id = Column(Integer)
    note = Column(String(500))
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    deleted_at = Column(DateTime)

    __table_args__ = (
        Index('ix_mpg_model_code', 'model_code'),
    )


class MarketProduct(Base):
    """마켓 × 계정 × 상품번호 = 1행. 머리글만 담는다(옵션 없음)."""
    __tablename__ = "market_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(20), nullable=False)
    account_key = Column(String(64), nullable=False)
    #: 마켓 상품번호. 스스=channelProductNo · 롯데온=spdNo · ESM=goodsNo ·
    #: 쿠팡=sellerProductId · 11번가=prdNo
    market_product_id = Column(String(64), nullable=False)
    #: 사이트별 번호(ESM 전용 — 옥션/지마켓이 갈린다). 없으면 NULL.
    site_product_id = Column(String(64))

    #: ★ 롯데온은 &lt;매장정품&gt; 처럼 HTML 이스케이프로 온다 —
    #:   fetchers 가 풀어서 넣는다. 안 풀면 검색이 안 걸린다.
    name = Column(String(500))
    brand = Column(String(120))

    status = Column(String(16), nullable=False, default='unknown')  # 통일 4상태+unknown
    raw_status = Column(String(32))     # 마켓 원본 코드 — 거짓 통일 방지용 증거
    #: 마켓이 안 주면 NULL. 0 으로 저장하면 '공짜 상품'으로 보인다.
    sale_price = Column(Integer)
    registered_at = Column(DateTime)   # 마켓 등록일(주는 마켓만)

    #: 모음전 상품으로 담았으면 그 묶음 번호. NULL = 아직 안 담음.
    group_id = Column(Integer, ForeignKey("market_product_groups.id"))

    synced_at = Column(DateTime, default=_now)   # 마지막으로 마켓에서 확인한 시각
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    #: 마켓에서 사라진 것도 이력이다 — 행을 지우지 않고 여기 시각을 남긴다.
    deleted_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint('market', 'account_key', 'market_product_id',
                         name='uq_market_products_key'),
        Index('ix_mp_market_account_status', 'market', 'account_key', 'status'),
        Index('ix_mp_group', 'group_id'),
        Index('ix_mp_name', 'name'),
    )


class MarketProductCount(Base):
    """대시보드가 읽는 건수 스냅샷 — 마켓 × 계정 × 상태마다 1행.

    화면은 이 표만 읽는다. 28만 행을 매번 세지 않으므로 대시보드가 즉시 뜬다.
    """
    __tablename__ = "market_product_counts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(20), nullable=False)
    account_key = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False)
    count = Column(Integer, nullable=False, default=0)
    #: 'api'  = 마켓에 직접 물어본 값(스스·롯데온·ESM — 즉답 가능)
    #: 'cache'= 우리 캐시를 센 값(쿠팡·11번가 — 마켓이 총건수를 안 준다)
    source = Column(String(8), nullable=False, default='cache')
    measured_at = Column(DateTime, default=_now)

    __table_args__ = (
        UniqueConstraint('market', 'account_key', 'status',
                         name='uq_market_product_counts_key'),
    )
