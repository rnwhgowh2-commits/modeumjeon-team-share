"""샵마인(통합주문관리) 내보내기 적재 — 공란 채움의 외부 실데이터 소스.

사장님이 샵마인에서 내려받은 엑셀을 그대로 적재한다(2026-07-22 지시). 마켓 취소
API 가 안 주는 구매자·주소·실결제를, 샵마인이 취소 **전에** 받아둔 값으로 채운다
(우리 적재분과 같은 원리 — 외부지만 실데이터). `sm_uid`(샵마인 주문고유코드) 로
업서트라 같은 파일을 다시 올려도 안전(멱등).

Alembic 없음 — app.py 가 이 모듈을 import 하면 `Base.metadata.create_all` 이 생성.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Index, String

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ShopmineOrder(Base):
    """샵마인 엑셀 1행(주문 라인 1개). PK = sm_uid(샵마인 주문고유코드)."""
    __tablename__ = "shopmine_orders"

    sm_uid = Column(String(64), primary_key=True)
    market = Column(String(32), nullable=False, default="")   # 우리 마켓 키(lotteon…)
    order_no = Column(String(128), default="")                # 오픈마켓 주문번호
    account_alias = Column(String(64), default="")            # 샵마인 쇼핑몰별칭
    ordered_at = Column(String(32), default="")
    product_name = Column(String(500), default="")
    option1 = Column(String(255), default="")
    qty = Column(String(16), default="")
    unit_price = Column(String(32), default="")
    paid_amount = Column(String(32), default="")
    buyer = Column(String(64), default="")
    recipient = Column(String(64), default="")
    phone = Column(String(32), default="")                    # 수령자전화번호
    buyer_phone = Column(String(32), default="")              # 구매자휴대전화
    zipcode = Column(String(16), default="")
    address = Column(String(500), default="")
    invoice = Column(String(64), default="")
    raw = Column(JSON)
    uploaded_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


Index("ix_smo_market_order", ShopmineOrder.market, ShopmineOrder.order_no)
