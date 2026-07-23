"""샵마인(통합주문관리) 내보내기 적재 — 공란 채움의 외부 실데이터 소스.

사장님이 샵마인에서 내려받은 엑셀을 그대로 적재한다(2026-07-22 지시). 마켓 취소
API 가 안 주는 구매자·주소·실결제를, 샵마인이 취소 **전에** 받아둔 값으로 채운다
(우리 적재분과 같은 원리 — 외부지만 실데이터). `sm_uid`(샵마인 주문고유코드) 로
업서트라 같은 파일을 다시 올려도 안전(멱등).

Alembic 없음 — app.py 가 이 모듈을 import 하면 `Base.metadata.create_all` 이 생성.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Index, Integer, String

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


class LotteonSoOrder(Base):
    """롯데온 **셀러오피스 주문관리 크롤** 1라인 — OpenAPI 가 안 주는 것의 유일한 원천.

    OpenAPI 전수 소진 실측(2026-07-22~23): 취소완료 주문의 상품 라인·구매자를
    어떤 공식 API 도 안 준다(클레임 42필드 무·209 단건 0건·주문혜택 빈배열).
    또 철회 취소(철회→정상 수취완료 복귀)는 140 진행단계에도 신호가 없다.
    셀러오피스 화면(soapi)이 샵마인과 같은 원천 — 확장(moum-crawler)이 로그인
    세션에서 수집해 /api/orders-ingest/lotteon-so-upsert 로 push 한다.
    PK = (od_no, od_seq). 값은 정규화 문자열(빈값 "" — 0 대체 금지).
    """
    __tablename__ = "lotteon_so_orders"

    od_no = Column(String(30), primary_key=True)
    od_seq = Column(String(10), primary_key=True, default="1")
    status = Column(String(120), default="")          # 셀러오피스 상태 원문(취소완료(…) 등)
    ordered_at = Column(String(32), default="")
    product_name = Column(String(500), default="")
    option1 = Column(String(255), default="")
    qty = Column(String(16), default="")
    unit_price = Column(String(32), default="")
    paid_amount = Column(String(32), default="")
    buyer = Column(String(64), default="")
    recipient = Column(String(64), default="")
    phone = Column(String(32), default="")
    buyer_phone = Column(String(32), default="")
    zipcode = Column(String(16), default="")
    address = Column(String(500), default="")
    tr_no = Column(String(20), default="")            # 계정(거래처번호)
    raw = Column(JSON)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class ShopmineReconRun(Base):
    """샵마인 대조탭 실행 1회의 결과 저장 — 「지난번 대비」 수렴 추적용.

    summary = 요약 수치(존재·필드 카운트·계정 매핑), result = 상세 목록
    (누락·불일치·판정불가, 각 상한 캡 — 캡 초과분은 *_total 로 정직 표기).
    """
    __tablename__ = "shopmine_recon_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ran_at = Column(DateTime, default=_utcnow)
    filename = Column(String(255), default="")
    period_from = Column(String(10), default="")
    period_to = Column(String(10), default="")
    summary = Column(JSON)
    result = Column(JSON)
