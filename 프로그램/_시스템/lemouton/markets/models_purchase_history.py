"""실매입가 **변경 이력** — 누가 언제 얼마에서 얼마로 바꿨나.

설계서 `docs/superpowers/specs/2026-08-06-실매입가-주문통합-design.md` §9
(「이번 범위 밖 → 다음」에 적혀 있던 것을 2026-08-12 에 구현).

## 왜 필요한가

`order_line_purchases` 는 **지금 값 하나만** 들고 있다. 그래서 값이 바뀌면 이전 값이
흔적 없이 사라진다. 매입가는 마진(= 돈)의 근거라, 「어제 본 마진과 오늘 본 마진이
다른데 왜 그런지 알 수 없다」가 실제로 생긴다. 특히 **더망고 엑셀 재업로드가 사장님이
손으로 적은 값을 덮어쓰는** 경우가 조용히 지나가면 안 된다.

## 규율

· **덧붙이기 전용(append-only)** — 이 표는 고치거나 지우지 않는다. 지우면 이력이 아니다.
· **바뀐 때만 적는다** — 같은 값을 다시 저장해도 행을 만들지 않는다(잡음 방지).
· **지움도 이력이다** — `new_price=None` 이 「입력 안 함으로 되돌림」이다.
· 🔴 **이력 적기가 실패해도 저장은 되돌리지 않는다** — 돈 값을 못 적는 것보다
  이력이 한 줄 비는 편이 낫다. 대신 로그에 남긴다(조용히 넘어가지 않는다).

Alembic 을 쓰지 않는다 — `shared/db.py:init_db()` 의 `Base.metadata.create_all` 이
이 모듈을 import 하기만 하면 테이블을 만든다(멱등). `app.py` 가 import 해야 등록된다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, String

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class OrderLinePurchaseHistory(Base):
    """실매입가가 바뀐 순간 1건. **덧붙이기만** 한다."""

    __tablename__ = "order_line_purchase_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    line_uid = Column(String(200), nullable=False)
    # 바뀌기 전 값. 처음 넣는 것이면 None(= 없다가 생김).
    old_price = Column(Integer)
    # 바뀐 뒤 값. None 이면 지움(= 「입력 안 함」으로 되돌림).
    new_price = Column(Integer)
    old_source = Column(String(16))
    new_source = Column(String(16))
    # 무엇이 이 변경을 일으켰나 — manual(수기) | mango(더망고 엑셀) | margin(마진 계산기 업로드)
    reason = Column(String(32))
    # 엑셀이면 파일명 + 행번호. 수기면 None.
    ref = Column(String(255))
    changed_by = Column(String(120))
    changed_at = Column(DateTime, default=_utcnow, nullable=False)


Index("ix_olph_uid_at", OrderLinePurchaseHistory.line_uid,
      OrderLinePurchaseHistory.changed_at)
