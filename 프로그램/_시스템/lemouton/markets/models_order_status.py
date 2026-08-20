"""「주문 관리」 상태 저장소 — 사장님이 직접 만든 항목을 주문 줄에 붙인다.

사장님 확정(2026-08-06)
────────────────────────────────
· 항목(이름·색·순서)은 **사장님이 만든다**. 우리가 기본 항목을 미리 심지 않는다
  — 처음엔 **빈 목록**이고, 화면이 「+ 첫 항목 만들기」를 안내한다.
· 색은 **우리 프로그램 색 7가지**에서만 고른다(자유 색 금지 — 의미색이 전 화면과 어긋난다).
· 목록은 **팀 전체가 공유**한다(프로젝트 규칙: per-user 분리 없음).
· 「기본 항목」 하나를 지정할 수 있다 — 아직 아무것도 안 고른 줄에 **표시만** 된다.
  🔴 기본값으로 행을 미리 만들지 않는다(아래 참조).

## 왜 별도 표인가 (models_purchase.py · models_supply.py 와 같은 이유)

주문 적재분(`market_order_lines`)은 주기적으로 재수집되며 그때 `row` JSON 이 통째
교체된다. 사람이 정한 값을 그 안에 끼워 넣으면 다음 수집에서 조용히 증발한다.
`order_store.save` 는 이 표를 아예 보지 않으므로 서로 못 덮어쓴다.

## 열쇠는 line_uid 다

주문번호 단독은 금지 — 쿠팡·롯데온·11번가는 주문번호가 **주문 단위**라 다품목 주문의
라인들이 서로를 덮어쓴다(`models_orders.MarketOrderLine` 주석과 같은 이유).

## 「기본 항목」을 행으로 만들지 않는 이유 (사장님 확정 2026-08-06)

주문 줄마다 기본값 행을 미리 깔면 ① 주문 수만큼 행이 생기고 ② 나중에 기본 항목을
바꿨을 때 **과거 주문까지 바뀌는지 아닌지**가 데이터만 봐서는 알 수 없게 된다.
그래서 기본 항목은 **조회 시점에 얹어 보여줄 뿐**이고(`is_fallback: true`),
사장님이 그 줄에서 무엇이든 고른 순간에야 진짜 행이 생긴다.

Alembic 을 쓰지 않는다 — `shared/db.py:init_db()` 의 `Base.metadata.create_all` 이
이 모듈을 import 하기만 하면 테이블을 만든다(멱등). `app.py` 가 import 해야 등록된다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Index, Integer,
                        String)

from shared.db import Base

#: 고를 수 있는 색 — 우리 프로그램 의미색 7가지뿐. 자유 색(hex 직접 입력) 금지.
COLOR_GRAY = "gray"
COLOR_BLUE = "blue"
COLOR_TEAL = "teal"       # 화면 라벨 「하늘」 — tokens.css `--ap-sky`
COLOR_GREEN = "green"
COLOR_ORANGE = "orange"
COLOR_RED = "red"
COLOR_PURPLE = "purple"

STATUS_COLORS = (COLOR_GRAY, COLOR_BLUE, COLOR_TEAL, COLOR_GREEN,
                 COLOR_ORANGE, COLOR_RED, COLOR_PURPLE)

#: 화면 라벨(항목 관리 창의 색 동그라미 도움말)
COLOR_LABELS = {
    COLOR_GRAY: "회색", COLOR_BLUE: "파랑", COLOR_TEAL: "하늘",
    COLOR_GREEN: "초록", COLOR_ORANGE: "주황", COLOR_RED: "빨강",
    COLOR_PURPLE: "보라",
}

#: 이름 길이 상한 — 표 첫 열 알약에 들어가는 글자다.
NAME_MAX = 80


def _utcnow():
    return datetime.now(timezone.utc)


class OrderStatusOption(Base):
    """사장님이 만든 「주문 관리」 상태 항목 하나.

    · `name` 은 중복 금지 — 같은 이름이 둘이면 드롭다운에서 어느 쪽인지 구분이 안 된다.
    · `sort_no` 는 드롭다운·알약 표시 순서(작을수록 위). 끌어서 바꾼다.
    · `is_default` 는 **전체에서 하나만 True**. 보장은 `order_status.set_default`
      (기존 것을 먼저 내리고 새 것을 올린다 — 한 트랜잭션).
    """

    __tablename__ = "order_status_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(NAME_MAX), nullable=False, unique=True)
    color = Column(String(16), nullable=False, default=COLOR_GRAY)
    sort_no = Column(Integer, nullable=False, default=0)
    # 새 주문에 「표시」될 항목. 🔴 저장이 아니라 표시다 — 행을 만들지 않는다.
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class OrderLineStatus(Base):
    """주문 라인 1줄에 붙은 상태. **비우면 행을 지운다**(= 「지정 안 함」).

    `models_purchase.OrderLinePurchase` 가 「모른다 = 행 없음」으로 두는 것과 같은 규율.
    """

    __tablename__ = "order_line_status"

    line_uid = Column(String(200), primary_key=True)
    option_id = Column(Integer, ForeignKey("order_status_options.id"),
                       nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    updated_by = Column(String(120))


Index("ix_ols_status_option", OrderLineStatus.option_id)
Index("ix_oso_sort", OrderStatusOption.sort_no)
