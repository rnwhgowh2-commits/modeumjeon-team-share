"""실매입가 저장소 — 주문 라인 1줄에 사람이 적은 「진짜 사온 값」.

설계서: `docs/superpowers/specs/2026-08-06-실매입가-주문통합-design.md` §3.

## 왜 별도 표인가

주문 적재분(`market_order_lines`)은 주기적으로 **재수집되고 그때 `row` JSON 이 통째
교체된다**. 사람이 적은 값을 그 안에 끼워 넣으면 다음 수집에서 조용히 증발한다
(「조용한 실패」 부류). 그래서 **기계가 쓰는 표(적재)와 사람이 쓰는 표(입력)를 물리적으로
분리**한다 — `order_store.save` 는 이 표를 아예 보지 않으므로 서로 못 덮어쓴다.

## 열쇠는 line_uid 다

주문번호 단독을 키로 쓰지 않는다 — 쿠팡·롯데온·11번가는 주문번호가 주문 단위라
다품목 주문의 라인들이 서로를 덮어쓴다(`models_orders.MarketOrderLine` 주석과 같은 이유).

Alembic 을 쓰지 않는다 — `shared/db.py:init_db()` 의 `Base.metadata.create_all` 이
이 모듈을 import 하기만 하면 테이블을 만든다(멱등). `app.py` 가 import 해야 등록된다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, String

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class OrderLinePurchase(Base):
    """주문 라인 1줄의 실매입가. 값이 없으면 **행 자체를 안 만든다**(0 으로 채우지 않는다)."""

    __tablename__ = "order_line_purchases"

    line_uid = Column(String(200), primary_key=True)
    # NULL 금지 — 「모른다」는 행 없음으로 표현한다. 0 도 저장하지 않는다
    # (더망고 엑셀의 미입력 센티널 999999999.99 가 0 으로 변환돼 들어오기 때문).
    purchase_price = Column(Integer, nullable=False)
    source = Column(String(16), nullable=False, default="manual")   # manual | mango
    mango_ref = Column(String(255))     # 엑셀 출처 추적(파일명 + 행번호). 수기면 NULL
    memo = Column(String(255))
    input_by = Column(String(120))
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


Index("ix_olp_source", OrderLinePurchase.source)
