"""공급방식 저장소 — 주문 라인 1줄을 「무재고」로 보냈나 「사입」으로 보냈나.

사장님 확정(2026-08-06)
────────────────────────────────
· **무재고(dropship)** = 소싱처에서 사서 보낸다. 내 창고 재고를 건드리지 않는다. **기본값**.
· **사입(stock)**     = 내 창고 재고로 보낸다. 재고를 깎아야 한다.
· 표시는 주문 내역·송장 작업 두 화면에서 **같은 값을 공유**한다(같은 템플릿·같은 원천).
· **재고 차감은 이 표시만으로 하지 않는다** — 포장하며 바코드를 찍는 순간에 한다
  (실물 대조와 차감을 한 동작으로). 여기 값은 「무엇으로 나갈 건가」라는 의사표시다.

## 왜 옵션이 아니라 주문 라인 단위인가

같은 상품이라도 어떤 주문은 창고에서, 어떤 주문은 소싱처에서 나간다. 옵션에 미리
못 박아 두면 예외가 생길 때마다 반드시 틀린다. 실제로 이 저장소의 기존 자동 판정
(`pricing/cost_basis.resolve_cost_basis` — 원가 싼 쪽)은 **어느 마진 정책으로 계산하나**를
정할 뿐 **어디서 배송하나**를 모른다. 그래서 사람이 주문 건마다 정하는 값이 따로 필요하다.

## 왜 별도 표인가 (models_purchase.py 와 같은 이유)

주문 적재분(`market_order_lines`)은 주기적으로 재수집되며 그때 `row` JSON 이 통째
교체된다. 사람이 적은 값을 그 안에 끼워 넣으면 다음 수집에서 조용히 증발한다.
`order_store.save` 는 이 표를 아예 보지 않으므로 서로 못 덮어쓴다.

## 열쇠는 line_uid 다

주문번호 단독은 금지 — 쿠팡·롯데온·11번가는 주문번호가 **주문 단위**라 다품목 주문의
라인들이 서로를 덮어쓴다(`models_orders.MarketOrderLine` 주석과 같은 이유).

Alembic 을 쓰지 않는다 — `shared/db.py:init_db()` 의 `Base.metadata.create_all` 이
이 모듈을 import 하기만 하면 테이블을 만든다(멱등). `app.py` 가 import 해야 등록된다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, String

from shared.db import Base

#: 공급방식 값 — 저장은 영문 코드, 화면 표시는 한글(무재고/사입)
SUPPLY_DROPSHIP = "dropship"   # 무재고 — 소싱처에서 사서 보냄 (기본)
SUPPLY_STOCK = "stock"         # 사입 — 내 창고 재고로 보냄

SUPPLY_MODES = (SUPPLY_DROPSHIP, SUPPLY_STOCK)

#: 화면 라벨 (사장님 용어 — 「위탁」이 아니라 「무재고」)
SUPPLY_LABELS = {SUPPLY_DROPSHIP: "무재고", SUPPLY_STOCK: "사입"}

#: 아무 표시도 없을 때의 값. **행이 없으면 무재고다** — 기본값을 행으로 만들지 않는다.
DEFAULT_SUPPLY_MODE = SUPPLY_DROPSHIP


def _utcnow():
    return datetime.now(timezone.utc)


class OrderLineSupply(Base):
    """주문 라인 1줄의 공급방식.

    행이 없으면 기본값(무재고)이다 — 기본값을 굳이 행으로 만들지 않는다
    (`models_purchase.OrderLinePurchase` 가 「모른다=행 없음」으로 두는 것과 같은 규율).
    사입으로 지정했다가 무재고로 되돌리면 행을 지운다.
    """

    __tablename__ = "order_line_supplies"

    line_uid = Column(String(200), primary_key=True)
    supply_mode = Column(String(16), nullable=False)   # dropship | stock
    input_by = Column(String(120))
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


Index("ix_ols_mode", OrderLineSupply.supply_mode)
