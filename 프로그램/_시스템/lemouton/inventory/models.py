"""[I] 재고관리 도메인 — DB 모델 (13 테이블).

박스히어로 1:1 복제 + 모음전 차별점 (옵션 매트릭스 R2 + 매출 snapshot).
- 양방향 sync 폐기 (ADR-005) — 박스히어로 1회 import 후 단독 운영
- 거래처 텍스트만 보존 (ADR-003)
- 매출 시점 매입가 snapshot (ADR-002)

LIGHT_SPEC.md §3 / interfaces.md §1 참조.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Boolean, ForeignKey, Float, Text,
    DateTime, Index,
)
from sqlalchemy.orm import relationship

from shared.db import Base


def _now():
    return datetime.now(timezone.utc)


# ============ 0. v17 — 재고관리 제품 (모음전 옵션 ↔ 재고관리 1:1) ============
class InventoryProduct(Base):
    """재고제품 마스터 — 물리적 제품 1행 = 재고의 단일 진실 원천.

    [제품 공유 v1] 모음전 옵션은 OptionProductLink 로 이 테이블을 참조한다.
    한 재고제품을 여러 모음전 옵션이 공유 → 재고가 모든 모음전에 동시 반영.
    InventoryTx 의 option_canonical_sku 가 이 테이블의 canonical_sku 와 매핑됨.
    (구) v17: [+재고관리 추가] 로만 생성 → (신) 모든 옵션에 대해 시딩.
    """
    __tablename__ = "inventory_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_sku = Column(String(128), nullable=False, unique=True, index=True)

    # 자동 매핑 (모음전에서) — 표시용
    option_name = Column(String(128))      # 예: 그레이-230
    model_code = Column(String(64))        # 예: 르무통 메이트
    color_code = Column(String(32))
    size_code = Column(String(32))
    brand = Column(String(64))

    # 사용자 입력
    category = Column(String(64))          # 카테고리 (필수)
    sub_category = Column(String(64))      # 분류 (선택)
    barcode = Column(String(64))           # 바코드 (자동 생성 가능)
    supplier = Column(String(128))         # 매입처
    purchase_date = Column(String(16))     # 매입 일자 (YYYY-MM-DD)
    location_id = Column(Integer, ForeignKey("inventory_locations.id"))

    # 가격 (자동 매핑 가능)
    purchase_price = Column(Integer)
    sale_price = Column(Integer)

    # 재고
    initial_stock = Column(Integer, default=0)
    safety_stock = Column(Integer, default=0)

    # 기타
    memo = Column(Text)

    # 저장 상태 — draft (작성 중) / completed (확정)
    status = Column(String(16), default='draft', index=True)

    created_at = Column(DateTime, default=_now, index=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    completed_at = Column(DateTime)


# ====== 0.5 [제품 공유 v1] 모음전 옵션 ↔ 재고제품 연결 ======
class OptionProductLink(Base):
    """모음전 옵션(options.canonical_sku) ↔ 재고제품(inventory_products.canonical_sku) 연결.

    N 옵션 : 1 재고제품 — 한 제품을 여러 모음전이 공유.
    ALTER TABLE 없이 신규 테이블로만 도입 (라이브 DB 안전).
    초기 마이그레이션: 옵션 1개당 자기 자신을 가리키는 링크 1행 (1:1).
    """
    __tablename__ = "option_product_links"

    option_canonical_sku = Column(String(128), primary_key=True)
    product_canonical_sku = Column(String(128), nullable=False, index=True)
    created_at = Column(DateTime, default=_now)


# ============ 1. 위치 (Q1 결정 = A + CRUD) ============
class InventoryLocation(Base):
    """위치 (그로스 / 기본 위치 / 판매불가 등). 사용자 CRUD 가능."""
    __tablename__ = "inventory_locations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, unique=True)
    sort_order = Column(Integer, default=0)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    deleted_at = Column(DateTime)


# ============ 2. 거래 (Tx — 입고/출고/조정/이동) ============
class InventoryTx(Base):
    """거래 — 입고/출고/조정/이동 4종 통합. 매출 snapshot 컬럼 포함 (ADR-002)."""
    __tablename__ = "inventory_txs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tx_type = Column(String(8), nullable=False, index=True)  # 'in'|'out'|'adjust'|'move'
    location_id = Column(Integer, ForeignKey("inventory_locations.id"))
    location_to_id = Column(Integer, ForeignKey("inventory_locations.id"))  # move 전용
    partner_label = Column(Text)  # 거래처 텍스트 (ADR-003)
    option_canonical_sku = Column(String(128), index=True)  # 모음전 옵션 매핑
    qty = Column(Integer, nullable=False, default=0)

    # ★ 매출 snapshot (ADR-002 — 출고 시점 박제)
    unit_purchase_price_at_tx = Column(Integer)  # 출고 시점 평균 매입가
    unit_sale_price = Column(Integer)            # 실제 판매가

    memo = Column(Text)
    photos_json = Column(Text)        # 사진/이미지 첨부 URL 배열
    hashtags = Column(Text)           # #태그 추출 결과 (#무료증정,#분실)

    created_by = Column(String(128))
    created_at = Column(DateTime, default=_now, index=True)

    # 출처 — 'local'(모음전 자체) / 'import'(박스히어로) / 'restored'(복구)
    source = Column(String(16), default='local')

    # 임시저장 → 완료 흐름
    status = Column(String(16), default='completed')  # 'pending'|'completed'|'cancelled'

    __table_args__ = (
        Index("ix_inv_tx_option_date", "option_canonical_sku", "created_at"),
        Index("ix_inv_tx_type_date", "tx_type", "created_at"),
    )


# ============ 3. 임시 저장 (Pending) ============
class InventoryPending(Base):
    """입고서/출고서/조정/이동 임시 저장 — 모든 멤버 공유."""
    __tablename__ = "inventory_pending"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tx_type = Column(String(8), nullable=False)
    payload_json = Column(Text, nullable=False)  # 폼 데이터 직렬화
    created_by = Column(String(128))
    created_at = Column(DateTime, default=_now)


# ============ 4-6. 재고 조사 (Stock Take) ============
class InventoryCount(Base):
    """재고 조사 마스터 — 위치별 시트 + 마감 시 조정 Tx 자동 생성."""
    __tablename__ = "inventory_counts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    target_locations_json = Column(Text)
    target_items_json = Column(Text)
    status = Column(String(16), default='in_progress')  # 'in_progress'|'pending_review'|'closed'
    created_at = Column(DateTime, default=_now)
    closed_at = Column(DateTime)

    sheets = relationship("InventoryCountSheet", back_populates="count",
                          cascade="all, delete-orphan")


class InventoryCountSheet(Base):
    """재고 조사 시트 (담당자별)."""
    __tablename__ = "inventory_count_sheets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    count_id = Column(Integer, ForeignKey("inventory_counts.id"), nullable=False)
    assignee_id = Column(String(128))
    status = Column(String(16), default='not_started')  # 'not_started'|'in_progress'|'done'
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    count = relationship("InventoryCount", back_populates="sheets")
    items = relationship("InventoryCountSheetItem", back_populates="sheet",
                         cascade="all, delete-orphan")


class InventoryCountSheetItem(Base):
    """시트의 제품별 입력 수량."""
    __tablename__ = "inventory_count_sheet_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sheet_id = Column(Integer, ForeignKey("inventory_count_sheets.id"), nullable=False)
    option_canonical_sku = Column(String(128), nullable=False)
    counted_qty = Column(Integer, default=0)

    sheet = relationship("InventoryCountSheet", back_populates="items")


# ============ 7-8. 속성 (Attribute) ============
class ItemAttribute(Base):
    """사용자 정의 속성 (텍스트·숫자·날짜·바코드·파일)."""
    __tablename__ = "item_attributes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, unique=True)
    type = Column(String(16), nullable=False)  # 'text'|'number'|'date'|'barcode'|'file'
    sort_order = Column(Integer, default=0)
    deleted_at = Column(DateTime)


class ItemAttributeValue(Base):
    """제품의 속성 값 — 옵션별 N 개 가능."""
    __tablename__ = "item_attribute_values"

    id = Column(Integer, primary_key=True, autoincrement=True)
    option_canonical_sku = Column(String(128), nullable=False, index=True)
    attribute_id = Column(Integer, ForeignKey("item_attributes.id"), nullable=False)
    value_text = Column(Text)
    value_number = Column(Float)
    value_date = Column(DateTime)
    value_file_url = Column(String(500))

    __table_args__ = (
        Index("ix_attr_val_option", "option_canonical_sku", "attribute_id"),
    )


# ============ 9-11. 구매·판매·반품 (Sprint 3) ============
class PurchaseOrder(Base):
    """발주서 (구매) — 4단계 상태 (임시·대기·부분·완료).

    박스히어로 1:1 보강 (PARITY_720 Tier 1):
    - po_number: 자동 생성 PO-000001 (사용자 비워두면 자동)
    - order_date: 발주일 (현재 기본, 수정 가능)
    - due_date: 입고 예정일
    - immediate_inbound: 즉시 입고 처리 토글
    - custom_fields_json: 사용자 정의 메타
    """
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    po_number = Column(String(32), unique=True, index=True)  # PO-000001
    partner_label = Column(Text)
    items_json = Column(Text)         # [{sku, qty, unit_price}, ...]
    status = Column(String(16), default='draft')  # 'draft'|'pending'|'partial'|'completed'
    tax_json = Column(Text)           # [{name, rate, type:'incl'|'excl'}, ...]
    discount_json = Column(Text)      # [{name, value, type:'amount'|'rate'}, ...]
    memo = Column(Text)
    custom_fields_json = Column(Text, default='{}')  # 사용자 정의 메타
    order_date = Column(DateTime, default=_now)  # 발주일
    due_date = Column(DateTime)  # 입고 예정일
    immediate_inbound = Column(Boolean, default=False)  # 즉시 입고 처리
    attachment_json = Column(Text, default='[]')  # [{name, path, size}, ...]
    created_by = Column(String(128))
    created_at = Column(DateTime, default=_now)
    completed_at = Column(DateTime)


class SalesOrder(Base):
    """판매서. PARITY_720 Tier 1 보강 (so_number·order_date·due_date·immediate_outbound·custom_fields)."""
    __tablename__ = "sales_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    so_number = Column(String(32), unique=True, index=True)  # SO-000001
    partner_label = Column(Text)
    items_json = Column(Text)
    status = Column(String(16), default='draft')
    tax_json = Column(Text)
    discount_json = Column(Text)
    memo = Column(Text)
    custom_fields_json = Column(Text, default='{}')
    order_date = Column(DateTime, default=_now)
    due_date = Column(DateTime)  # 출고 예정일
    immediate_outbound = Column(Boolean, default=False)
    attachment_json = Column(Text, default='[]')
    created_by = Column(String(128))
    created_at = Column(DateTime, default=_now)
    completed_at = Column(DateTime)


class ReturnOrder(Base):
    """반품 (판매 반품). PARITY_720 Tier 1 보강."""
    __tablename__ = "return_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ro_number = Column(String(32), unique=True, index=True)  # RO-000001
    sales_order_id = Column(Integer, ForeignKey("sales_orders.id"))
    items_json = Column(Text)
    status = Column(String(16), default='pending')
    memo = Column(Text)
    custom_fields_json = Column(Text, default='{}')
    return_date = Column(DateTime, default=_now)
    refund_amount = Column(Integer, default=0)
    attachment_json = Column(Text, default='[]')
    created_by = Column(String(128))
    created_at = Column(DateTime, default=_now)
    completed_at = Column(DateTime)


class NotificationLog(Base):
    """인앱 알림 (헤더 벨 아이콘 표시용). PARITY_720 Tier 1 (I-6, I-11)."""
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(32), nullable=False)  # 'low_stock'|'po_partial'|'po_completed'|'penalty'|'sync'|'system'
    severity = Column(String(8), default='info')  # 'info'|'warning'|'error'|'success'
    title = Column(String(255), nullable=False)
    body = Column(Text)
    link_url = Column(String(500))
    is_read = Column(Boolean, default=False, nullable=False)
    target_user = Column(String(128))  # null = 전체
    created_at = Column(DateTime, default=_now)
    read_at = Column(DateTime)


# NOTE: AuditLog 는 lemouton/audit/models.py 에 이미 정의됨 — 중복 방지로 본 모듈에서 제거
# PARITY_720 E-21 / Q-7 활용 시 from lemouton.audit.models import AuditLog 사용


# ============ 12. 재고 공유 링크 ============
class InventoryShareLink(Base):
    """외부 재고 공유 링크 (토큰 기반, 안전 공개)."""
    __tablename__ = "inventory_share_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255))
    filter_json = Column(Text)
    token = Column(String(128), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime)
    created_by = Column(String(128))
    created_at = Column(DateTime, default=_now)
    revoked_at = Column(DateTime)


# ============ 13. 안전 재고 (Low Stock Alert) ============
class InventorySafetyStock(Base):
    """옵션·위치별 안전 재고 임계값."""
    __tablename__ = "inventory_safety_stock"

    id = Column(Integer, primary_key=True, autoincrement=True)
    option_canonical_sku = Column(String(128), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("inventory_locations.id"))  # NULL = 전체 위치
    threshold = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_safety_option_loc", "option_canonical_sku", "location_id"),
    )


# ============ 14. 검색 로그 (PARITY_720 K-11) ============
class SearchLog(Base):
    """검색 분석 — no-result 추적."""
    __tablename__ = "search_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(String(255), nullable=False, index=True)
    scope = Column(String(32))  # 'sku'|'partner'|'global'
    result_count = Column(Integer, default=0)
    no_result = Column(Boolean, default=False, index=True)
    user_agent = Column(String(255))
    created_at = Column(DateTime, default=_now, index=True)


# ============ 15. Webhook 엔드포인트 (PARITY_720 G-3) ============
class WebhookEndpoint(Base):
    """외부 시스템에 이벤트 송신 — 거래 생성 등."""
    __tablename__ = "webhook_endpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    url = Column(String(500), nullable=False)
    events = Column(Text, default='[]')  # JSON ["po.created","so.created","ro.created"]
    secret = Column(String(128))
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)
    last_fired_at = Column(DateTime)
    last_status_code = Column(Integer)


# ============ 16. Alert 규칙 (PARITY_720 N-9) ============
class AlertRule(Base):
    """알림 규칙 — 응답시간/에러율/안전재고 트리거 정의."""
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    metric = Column(String(32), nullable=False)  # 'low_stock'|'error_rate'|'response_time'|'po_overdue'
    threshold = Column(Float, nullable=False, default=0)
    operator = Column(String(4), default='>')  # '>'|'<'|'=='
    notify_category = Column(String(32), default='system')
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)
