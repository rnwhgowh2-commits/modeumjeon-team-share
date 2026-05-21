"""
SQLAlchemy 부트스트랩.
후속 모듈은 `Base`를 import해서 모델을 정의하면 자동으로 테이블 생성 대상에 포함된다.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import Config


class Base(DeclarativeBase):
    pass


engine = create_engine(Config.DB_URL, future=True)
# expire_on_commit=False: commit 후 객체 컬럼 expire 방지 — session.close() 후에도 컬럼 access 가능
# (DetachedInstanceError + InFailedSqlTransaction 회피)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True, expire_on_commit=False)


def init_db() -> None:
    """후속 모듈이 등록한 모든 모델 테이블을 생성한다 (멱등)."""
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    """create_all 이 신규 컬럼은 추가하지 않으므로 ALTER TABLE 로 보강.

    PostgreSQL / SQLite 모두 지원하기 위해 SQLAlchemy inspect() 사용 (PRAGMA 대신).
    """
    from sqlalchemy import text, inspect
    # PARITY_720 K-1 — 검색 LIKE 인덱스 (Option canonical_sku/boxhero_sku 이미 PK/UNIQUE 인덱스 존재)
    # SearchLog query 컬럼은 모델에서 index=True 이므로 자동.
    indexes = [
        ('ix_inv_tx_partner', 'inventory_txs', 'partner_label'),
        ('ix_po_partner', 'purchase_orders', 'partner_label'),
        ('ix_so_partner', 'sales_orders', 'partner_label'),
        ('ix_po_status', 'purchase_orders', 'status'),
        ('ix_so_status', 'sales_orders', 'status'),
        ('ix_ro_status', 'return_orders', 'status'),
    ]
    migrations = [
        ("models", "last_crawled_at", "DATETIME"),
        ("models", "last_uploaded_at", "DATETIME"),
        # v6 Phase 3.5 (2026-05-07): 모음전별 자동화 ON/OFF 토글
        ("models", "auto_enabled", "BOOLEAN DEFAULT 1 NOT NULL"),

        # ★ STEP 7 Task 0.2 (2026-05-07): 박스히어로 재고관리 13 컬럼 (R2 옵션 매트릭스)
        # Option 7개 — 옵션 단위 재고·평균매입가·사입 마진
        ("options", "boxhero_stock_total", "INTEGER DEFAULT 0"),
        ("options", "boxhero_avg_purchase_price", "INTEGER DEFAULT 0"),
        ("options", "boxhero_avg_updated_at", "DATETIME"),
        ("options", "option_boxhero_margin_mode", "VARCHAR(8)"),
        ("options", "option_boxhero_margin_value", "INTEGER"),
        ("options", "option_external_margin_mode", "VARCHAR(8)"),
        ("options", "option_external_margin_value", "INTEGER"),
        # Model 2개 — 모델 단위 박스히어로 마진 오버라이드
        ("models", "boxhero_margin_mode_override", "VARCHAR(8)"),
        ("models", "boxhero_margin_value_override", "INTEGER"),
        # PriceTemplate 4개 — 공통 사입 마진 (외부/자체 분리)
        ("price_templates", "boxhero_margin_mode_self", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "boxhero_margin_value_self", "INTEGER DEFAULT 2500"),
        ("price_templates", "boxhero_margin_mode_external", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "boxhero_margin_value_external", "INTEGER DEFAULT 2000"),
        # 2026-05-08: 사입재고 활성화 토글 (사용자 명시 요구 — 옵션마다 자체/외부 가격 선택)
        ("options", "use_purchase_inventory", "BOOLEAN DEFAULT 0 NOT NULL"),
        # 2026-05-08 r2: M4/P3/C9 — 사입 우선순위 + 수기 판매가
        ("options", "purchase_priority", "VARCHAR(16) DEFAULT 'auto' NOT NULL"),
        ("options", "purchase_manual_price", "INTEGER"),
        # 2026-05-08: 제품 이미지 (박스히어로 1:1)
        ("options", "image_url", "VARCHAR(500)"),
        # 2026-05-18: 박스히어로 EAN-13 바코드 (라벨 인쇄용)
        ("options", "barcode", "VARCHAR(64)"),
        # 2026-05-19: 품번 (우리 양식 5번째 컬럼) — Model 마스터에 저장
        ("models", "article_no", "VARCHAR(64)"),
        # 2026-05-21: 가격 템플릿 마켓별 반품비·교환비 (모달 가로탭 재구성)
        ("price_templates", "ss_return_fee", "INTEGER DEFAULT 0"),
        ("price_templates", "ss_exchange_fee", "INTEGER DEFAULT 0"),
        ("price_templates", "coupang_return_fee", "INTEGER DEFAULT 0"),
        ("price_templates", "coupang_exchange_fee", "INTEGER DEFAULT 0"),
        # 2026-05-08: PARITY_720 Tier 1 — PO/SO/RO 자동번호·날짜·즉시처리·커스텀필드·첨부
        ("purchase_orders", "po_number", "VARCHAR(32)"),
        ("purchase_orders", "custom_fields_json", "TEXT DEFAULT '{}'"),
        ("purchase_orders", "order_date", "DATETIME"),
        ("purchase_orders", "due_date", "DATETIME"),
        ("purchase_orders", "immediate_inbound", "BOOLEAN DEFAULT 0"),
        ("purchase_orders", "attachment_json", "TEXT DEFAULT '[]'"),
        ("sales_orders", "so_number", "VARCHAR(32)"),
        ("sales_orders", "custom_fields_json", "TEXT DEFAULT '{}'"),
        ("sales_orders", "order_date", "DATETIME"),
        ("sales_orders", "due_date", "DATETIME"),
        ("sales_orders", "immediate_outbound", "BOOLEAN DEFAULT 0"),
        ("sales_orders", "attachment_json", "TEXT DEFAULT '[]'"),
        ("return_orders", "ro_number", "VARCHAR(32)"),
        ("return_orders", "custom_fields_json", "TEXT DEFAULT '{}'"),
        ("return_orders", "return_date", "DATETIME"),
        ("return_orders", "refund_amount", "INTEGER DEFAULT 0"),
        ("return_orders", "attachment_json", "TEXT DEFAULT '[]'"),
        # 2026-05-21: Phase 2 단계형 옵션 — 옵션별 N축 단계 값 (JSON list)
        ("options", "axis_values_json", "TEXT"),
        # 2026-05-21: Phase 3 — 오프라인 전용 옵션 (소싱처 URL 없이 사입만)
        ("options", "offline_only", "BOOLEAN DEFAULT 0 NOT NULL"),
    ]
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, dtype in migrations:
            try:
                if table not in existing_tables:
                    continue
                # SQLAlchemy inspect — SQLite/PostgreSQL 양쪽 호환
                names = {c["name"] for c in inspector.get_columns(table)}
                if column not in names:
                    # PostgreSQL 변환: DATETIME→TIMESTAMP, BOOLEAN 컬럼만 1/0→true/false.
                    # 1/0 치환은 BOOLEAN 에만 적용 — INTEGER DEFAULT 0 이
                    # DEFAULT false 로 오염돼 ALTER 가 실패하던 버그 수정.
                    pg_dtype = dtype
                    if conn.dialect.name == "postgresql":
                        pg_dtype = dtype.replace("DATETIME", "TIMESTAMP")
                        if pg_dtype.strip().upper().startswith("BOOLEAN"):
                            pg_dtype = (pg_dtype.replace("DEFAULT 1", "DEFAULT true")
                                                .replace("DEFAULT 0", "DEFAULT false"))
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {pg_dtype}"))
            except Exception:
                pass
        # PARITY_720 K-1 — 검색 인덱스 멱등 생성 (양쪽 dialect 동일 문법)
        for idx_name, table, column in indexes:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})"))
            except Exception:
                pass
