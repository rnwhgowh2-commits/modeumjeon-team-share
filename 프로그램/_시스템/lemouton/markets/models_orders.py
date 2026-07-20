"""주문·클레임 적재 테이블.

Alembic 을 쓰지 않는다 — `shared/db.py:init_db()` 의 `Base.metadata.create_all` 이
이 모듈을 import 하기만 하면 테이블을 만든다(멱등). 나중 컬럼 추가는 `_apply_lightweight_migrations`
패턴을 따라야 한다(create_all 은 기존 테이블에 컬럼을 붙이지 않는다).

행 전체는 `row` JSON 에 보관한다. 화면·엑셀이 쓰는 열 목록(`order_export.ALL_COLUMNS`)이
계속 늘어나 왔기 때문에, 열마다 컬럼을 파면 열이 늘 때마다 마이그레이션이 필요해진다.
조회·집계에 실제로 쓰는 값만 별도 컬럼으로 뽑아 인덱스를 건다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Index, String

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class MarketOrderLine(Base):
    """주문 상품라인 1건. PK = line_uid(마켓이 주는 불변 식별자, `line_uid.py` 참조).

    ★ 주문번호 단독을 키로 쓰지 않는다 — 쿠팡·롯데온·11번가는 주문번호가 주문 단위라
    다품목 주문의 라인들이 서로를 덮어쓴다(주문 소실).
    """
    __tablename__ = "market_order_lines"

    line_uid = Column(String(200), primary_key=True)
    market = Column(String(32), nullable=False, default="")     # smartstore·coupang…
    order_no = Column(String(128), default="")                  # 오픈마켓주문번호(표시·조인용)
    # 'YYYY-MM-DD HH:MM:SS' 정규화 문자열 → 문자열 비교가 곧 시간 비교.
    #  공란이 정상인 행이 있다(클레임 등) — 기간 필터에서 지우면 안 된다.
    order_date = Column(String(32), default="")
    status = Column(String(32), default="")                     # 주문상태(한글)
    account = Column(String(64), default="")                    # 쇼핑몰별칭(계정)
    row = Column(JSON, nullable=False)                          # 화면·엑셀용 전체 행
    first_seen_at = Column(DateTime, default=_utcnow)
    last_seen_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


Index("ix_mol_market_date", MarketOrderLine.market, MarketOrderLine.order_date)
Index("ix_mol_order_no", MarketOrderLine.order_no)


class MarketClaimEvent(Base):
    """클레임 이벤트 1건. 주문 라인과 **별도 테이블**인 이유:

    같은 라인이 반품요청 → 반품완료로 이동할 때 주문 테이블에 덮어쓰면 앞 이벤트가
    사라진다. 이력이 남아야 「언제 무슨 클레임이 있었나」를 답할 수 있다.
    """
    __tablename__ = "market_claim_events"

    event_uid = Column(String(220), primary_key=True)
    line_uid = Column(String(200), default="")       # 주문 라인과의 연결(없을 수 있음)
    market = Column(String(32), nullable=False, default="")
    order_no = Column(String(128), default="")
    changed_at = Column(String(32), default="")      # 마켓별 원본 포맷(정규화 안 됨)
    status = Column(String(32), default="")          # 취소요청·반품완료 등(한글)
    status_raw = Column(String(64), default="")      # 마켓 원본 상태코드
    row = Column(JSON, nullable=False)
    first_seen_at = Column(DateTime, default=_utcnow)
    last_seen_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


Index("ix_mce_market_order", MarketClaimEvent.market, MarketClaimEvent.order_no)
Index("ix_mce_line", MarketClaimEvent.line_uid)


class OrderIngestRun(Base):
    """백필 진행 상태 — **DB 에 둔다**.

    앱이 멀티워커라 모듈 전역 변수로 두면 백필을 시작한 워커와 상태를 묻는 워커가 달라
    진행률이 0/0 으로 보인다(2026-07-20 라이브에서 실제로 겪음). 상태는 공유돼야 한다.
    """
    __tablename__ = "order_ingest_runs"

    id = Column(String(8), primary_key=True, default="current")   # 단일 행
    running = Column(String(8), default="0")        # 지금 틱이 돌고 있나
    requested = Column(String(8), default="0")      # 백필 요청됨 — 스케줄러가 가져간다
    cursor = Column(String(8), default="0")         # 어디까지 했나(중단 시 이어받는 지점)
    markets = Column(String(200), default="")
    days = Column(String(8), default="")
    done = Column(String(8), default="0")
    total = Column(String(8), default="0")
    market = Column(String(32), default="")         # 지금 돌고 있는 마켓
    error = Column(String(500), default="")
    result = Column(JSON, default=list)
    started_at = Column(DateTime, default=_utcnow)
    finished_at = Column(DateTime)
