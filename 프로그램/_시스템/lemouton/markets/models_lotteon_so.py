"""롯데온 셀러오피스 통합주문조회 크롤 적재 모델.

Alembic 없음 — app.py 가 이 모듈을 import 하면 `Base.metadata.create_all` 이 생성.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, JSON, String

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class LotteonSoOrder(Base):
    """롯데온 **셀러오피스 통합주문조회 크롤** 1라인 — OpenAPI 가 안 주는 것의 유일한 원천.

    OpenAPI 전수 소진 실측(2026-07-22~23): 취소완료 주문의 상품 라인·구매자를
    어떤 공식 API 도 안 준다(클레임 42필드 무·209 단건 0건·주문혜택 빈배열).
    또 철회 취소(철회→정상 수취완료 복귀)는 140 진행단계에도 신호가 없다.
    실측 원천 = `POST soapi.lotteon.com/soapi/v1/order/orderInquiry/getOrderList`
    (2026-07-23 라이브: 164필드·부분취소의 취소 라인·구매자·수령자·주소 전부 포함).
    확장(moum-crawler)이 로그인 세션에서 수집해 /api/orders-ingest/lotteon-so-upsert 로 push.

    ★PK = (od_no, od_seq, **proc_seq**) — 같은 (odNo,odSeq)에 원주문 procSeq=1 과
      취소 procSeq=2 가 **함께** 온다(2026072218515514 실측). procSeq 를 키에서
      빼면 취소가 원주문을 덮어써 부분취소가 통째 사라진다.
    값은 정규화 문자열(빈값 "" — 0 대체 금지).
    """
    __tablename__ = "lotteon_so_order_lines"

    od_no = Column(String(30), primary_key=True)
    od_seq = Column(String(10), primary_key=True, default="1")
    proc_seq = Column(String(10), primary_key=True, default="1")
    status = Column(String(120), default="")          # odPrgsStepCdText(취소완료·배송완료 등)
    status_code = Column(String(10), default="")      # odPrgsStepCd(21=취소완료·14=배송완료)
    od_typ = Column(String(60), default="")           # odTypCdText(취소(주문취소) 등)
    claimed_at = Column(String(32), default="")       # clmCmptDttm(클레임 완료 일시)
    ch_no = Column(String(20), default="")            # chNo(유입 채널 — 제휴 판별)
    discount = Column(String(32), default="")         # dcAmt(할인액)
    ship_fee = Column(String(32), default="")         # aplyDvCst(적용 배송비)
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
