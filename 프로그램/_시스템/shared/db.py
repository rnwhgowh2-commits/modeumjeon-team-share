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
#
# pool_size + max_overflow: Supabase session pooler 가 max 15 client 라
# 그 이하로 묶어 풀 고갈 회피. 풀 추가 생성 비용 < 고갈 시 5초+ 대기 비용.
# pool_recycle: idle connection 5분 후 폐기 — pgbouncer idle timeout 회피.
# SQLite 폴백 시에는 pool 옵션이 무시되므로 동일 코드로 안전.
_is_sqlite = Config.DB_URL.startswith('sqlite')
_engine_kwargs = dict(future=True, pool_pre_ping=True)
if not _is_sqlite:
    _engine_kwargs.update(
        # [2026-06-06] 라이브(서버)+로컬(크롤) 동시 실행 대응 — 앱당 최대 7로 축소.
        #   기존 13/앱 은 단일 앱 가정. 두 인스턴스면 26>15(Supabase 한도) → 풀 고갈.
        #   7×2=14<15 로 라이브·로컬 공존 가능.
        pool_size=3,        # 항상 유지하는 idle conn 수
        max_overflow=4,     # 피크 시 추가 — 총 7/앱 (라이브+로컬 = 14 < 15)
        pool_recycle=60,    # [perf 2026-05-29] 60초: 유휴 커넥션이 half-open 되기 전에
                            #   선제 폐기 → 유휴 후 첫 요청은 항상 새 커넥션(~0.3s, 동일 리전)
                            #   사용. keepalive(42s→10s)로도 남던 잔여 멈춤을 제거.
        pool_timeout=10,    # 풀 고갈 시 대기 한계 (디폴트 30s → 10s 로 빠른 실패)
        # [perf 2026-05-29] TCP keepalive — 유휴 후 "첫 요청 수십 초 멈춤" 근본 해결.
        #   증상: 앱이 잠깐 쉰 뒤 첫 클릭(예: 옵션조합 모달) 시 ~40초 멈춤, 직후엔 0.4초.
        #   원인: Fly↔Supabase pooler 사이 NAT 가 유휴 TCP 를 조용히 끊음(half-open).
        #         pool_pre_ping 의 SELECT 1 이 죽은 소켓을 붙잡고 TCP 재전송 타임아웃까지 대기.
        #   해결: keepalives 로 30초마다 probe → NAT 매핑 유지(끊김 자체 예방) +
        #         connect_timeout 으로 신규 연결도 10초 내 실패하도록 상한.
        connect_args={
            'connect_timeout': 10,
            'keepalives': 1,
            'keepalives_idle': 30,
            'keepalives_interval': 10,
            'keepalives_count': 5,
        },
    )
engine = create_engine(Config.DB_URL, **_engine_kwargs)
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
        # [2026-05-27 D1] 사용자가 매트릭스에서 OFF 한 옵션 (URL 매핑 있어 데이터 보존). True=활성, False=비활성.
        ("options", "is_active", "BOOLEAN DEFAULT 1 NOT NULL"),
        # 2026-06-05: 혜택 표시 카테고리 (정액/정률/결제/캐시백/기타) — 새 혜택 추가 모달에서 사용자 지정
        ("source_benefit_templates", "category", "VARCHAR(16)"),
        ("option_benefit_overrides", "category", "VARCHAR(16)"),
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
