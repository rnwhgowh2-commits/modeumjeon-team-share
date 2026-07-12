"""배송검사 도메인 모델.

MangoOrder     — 더망고 주문내역 엑셀 1행 = 1주문 (mango_uid 기준 upsert).
MangoStatusMap — L(더망고주문상태) 원본값 → 의미·기본 배송방식·배송흐름 검사대상 매핑(편집 가능).
"""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON

from shared.db import Base


def _now():
    return datetime.now(timezone.utc)


class MangoOrder(Base):
    __tablename__ = "mango_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mango_uid = Column(String(32), unique=True, nullable=False, index=True)  # P 더망고주문고유번호
    market_order_no = Column(String(64), index=True)   # C 마켓주문번호
    market_name = Column(String(32))                    # B 마켓명
    ordered_at = Column(String(32))                     # A 마켓주문일자 (원문 문자열)
    recipient = Column(String(64))                      # D 수령인명
    product_name = Column(Text)                         # E 마켓상품명
    option1 = Column(String(255))                       # F 옵션1
    phone = Column(String(32))                          # O 휴대폰번호
    invoice_no = Column(String(64))                     # K 국내송장번호 (없으면 None)
    courier = Column(String(32))                        # J 국내송장번호 택배사
    mango_status = Column(String(64), index=True)       # L 더망고주문상태 (구분자 원본값)
    market_status = Column(String(64))                  # M 마켓주문상태
    memo = Column(Text)                                 # N 간단메모

    delivery_method = Column(String(8), default="미지정", nullable=False)       # 까대기/직배/미지정
    delivery_method_source = Column(String(8), default="자동", nullable=False)  # 자동/일괄/수기

    invoice_history = Column(JSON, default=list)        # [{"invoice": "...", "at": iso}]
    is_duplicate_invoice = Column(Boolean, default=False, nullable=False)

    first_uploaded_at = Column(DateTime, default=_now)
    last_uploaded_at = Column(DateTime, default=_now, onupdate=_now)
    raw = Column(JSON)                                  # 원본 행 dict (감사용)

    # v2 마켓 API 연동 캐시 (오픈마켓주문번호로 실주문 조회 결과)
    market_api_status = Column(String(32))     # 마켓 통일 주문상태(배송준비중/배송중/배송완료…)
    market_api_invoice = Column(String(64))    # 마켓에 등록된 송장번호
    market_shipped_at = Column(String(32))     # 마켓 발송처리일시(제공 마켓만)
    market_checked_at = Column(DateTime)       # 마지막 조회 시각
    market_check_error = Column(String(200))   # 조회 실패/미매칭 사유(있으면 '확인 불가')


class MangoStatusMap(Base):
    __tablename__ = "mango_status_map"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status_value = Column(String(64), unique=True, nullable=False)   # 예: "해외현지배송중"
    meaning = Column(String(16), default="기타")                     # 배송전/해외배송중/국내배송중/배송완료/취소반품교환/기타
    default_method = Column(String(8), default="미지정")             # 까대기/직배/미지정
    is_flow_check_target = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=100)
    editable = Column(Boolean, default=True, nullable=False)
