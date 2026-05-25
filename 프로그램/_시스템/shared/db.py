"""
SQLAlchemy 부트스트랩.
후속 모듈은 `Base`를 import해서 모델을 정의하면 자동으로 테이블 생성 대상에 포함된다.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import Config


class Base(DeclarativeBase):
    pass


# pool_pre_ping=True: Supabase pgbouncer 가 idle connection 을 끊는 경우
# (보통 5~10분 idle) 첫 쿼리가 실패하던 문제 방지. checkout 시 SELECT 1 로
# 검증. 검증 비용 ~5ms (Tokyo-Tokyo RTT) 이지만 stale connection 으로 인한
# 첫 요청 500 에러 / 재시도 비용보다 훨씬 작음.
engine = create_engine(Config.DB_URL, future=True, pool_pre_ping=True)
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
        # 2026-05-25: 가격 책정 모드 — 소싱/사입 분리 + 'fixed'(지정가) 모드 추가
        ("price_templates", "ss_mode_sourcing", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "ss_rate_sourcing", "FLOAT DEFAULT 0.0945"),
        ("price_templates", "ss_amount_sourcing", "INTEGER DEFAULT 0"),
        ("price_templates", "ss_mode_purchase", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "ss_rate_purchase", "FLOAT DEFAULT 0.0945"),
        ("price_templates", "ss_amount_purchase", "INTEGER DEFAULT 0"),
        ("price_templates", "coupang_mode_sourcing", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "coupang_rate_sourcing", "FLOAT DEFAULT 0.1242"),
        ("price_templates", "coupang_amount_sourcing", "INTEGER DEFAULT 0"),
        ("price_templates", "coupang_mode_purchase", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "coupang_rate_purchase", "FLOAT DEFAULT 0.1242"),
        ("price_templates", "coupang_amount_purchase", "INTEGER DEFAULT 0"),
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
        # 2026-05-24: BundleSourceUrl 라벨 (URL 구분용 — "통합 모음전" / "단품 - 그레이")
        ("bundle_source_urls", "label", "VARCHAR(120)"),
        # 2026-05-25: 판매가 정책 (색상 통일 / 옵션별 cheapest) — A2+D3 시안 적용
        ("price_templates", "pricing_policy", "VARCHAR(16) DEFAULT 'cheapest'"),
        # 2026-05-25: 매입가 산정 우선순위 (V5 시안 — 사입 카드 0원 차단)
        ("price_templates", "price_source_priority", "VARCHAR(16) DEFAULT 'template'"),
        # 2026-05-25: 옵션별 지정가 (C1 시안 — 3번째 가격 카드)
        ("options", "fixed_ss_price", "INTEGER"),
        ("options", "fixed_cp_price", "INTEGER"),
        # 2026-05-25 A1: 소싱·사입 카드 각각 지정가 활성화 토글 + 마켓별 값 (카드 단위 active 는 DEPRECATED)
        ("options", "src_fixed_active", "BOOLEAN DEFAULT 0 NOT NULL"),
        ("options", "src_fixed_ss_price", "INTEGER"),
        ("options", "src_fixed_cp_price", "INTEGER"),
        ("options", "pur_fixed_active", "BOOLEAN DEFAULT 0 NOT NULL"),
        ("options", "pur_fixed_ss_price", "INTEGER"),
        ("options", "pur_fixed_cp_price", "INTEGER"),
        # 2026-05-25 M: 마켓별 지정가 active (소싱·사입 × 스마트·쿠팡 = 4개)
        ("options", "src_fixed_ss_active", "BOOLEAN DEFAULT 0 NOT NULL"),
        ("options", "src_fixed_cp_active", "BOOLEAN DEFAULT 0 NOT NULL"),
        ("options", "pur_fixed_ss_active", "BOOLEAN DEFAULT 0 NOT NULL"),
        ("options", "pur_fixed_cp_active", "BOOLEAN DEFAULT 0 NOT NULL"),
        # v34.13 (2026-05-25): brand 박스 안 텍스트 사용자 커스터마이징
        ("brand_color_overrides", "letter", "VARCHAR(16)"),
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

        # [Phase 3] 옵션 다중 URL — 옛 (canonical_sku, source_id) UniqueConstraint 제거.
        #   한 소싱처에 URL 여러 개 허용. PostgreSQL 만 (SQLite fresh DB 는 모델에 제약 없음).
        if conn.dialect.name == "postgresql":
            for cons in ("uq_option_source_urls_v3", "uq_option_source"):
                try:
                    conn.execute(text(
                        f"ALTER TABLE option_source_urls DROP CONSTRAINT IF EXISTS {cons}"))
                except Exception:
                    pass

    # [2026-05-24] MarketRegistry 시드 — 기본 2개 마켓 자동 등록 (스마트스토어, 쿠팡)
    # is_builtin=True → 삭제 불가. 사용자가 추가하는 마켓은 is_builtin=False.
    try:
        from lemouton.sourcing.models import MarketRegistry
        from sqlalchemy.orm import sessionmaker
        SessionMaker = sessionmaker(bind=engine)
        s = SessionMaker()
        try:
            if s.query(MarketRegistry).count() == 0:
                s.add_all([
                    MarketRegistry(market_key='smartstore', label='스마트스토어',
                                   logo_color='#22c55e', logo_letter='스마',
                                   sort_order=1, is_builtin=True),
                    MarketRegistry(market_key='coupang', label='쿠팡',
                                   logo_color='#3B82F6', logo_letter='쿠팡',
                                   sort_order=2, is_builtin=True),
                ])
                s.commit()
        finally:
            s.close()
    except Exception:
        pass  # 테이블 미생성 등 — 다음 startup 에 재시도
