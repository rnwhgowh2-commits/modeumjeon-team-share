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


def _drop_stale_process_rules() -> None:
    """[2026-07-19 대량등록 ②가공] process_rules 에 market 축을 넣기 위한 일회성 처리.

    UNIQUE 가 (policy_id, item_key) → (policy_id, market, item_key) 로 바뀌어야 하는데,
    이 파일의 마이그레이션 경로는 **ADD COLUMN / CREATE INDEX 뿐**이고 ADD CONSTRAINT 가
    없다. 컬럼만 더하면 옛 UNIQUE 가 마켓별 행을 막는다.

    ★ **비어 있을 때만** 통째로 지운다 — 바로 뒤 create_all 이 새 스키마로 다시 만든다.
      같은 날 만든 신규 표라 라이브도 0행인 것을 확인하고 하는 처리다
      (2026-07-19 확인: 라이브 정책 0 · 규칙 0).
      행이 하나라도 있으면 **아무것도 하지 않는다** — 데이터를 지우느니 옛 스키마로 둔다.
    """
    from sqlalchemy import inspect, text
    try:
        insp = inspect(engine)
        if 'process_rules' not in set(insp.get_table_names()):
            return
        if 'market' in {c['name'] for c in insp.get_columns('process_rules')}:
            return                      # 이미 새 스키마
        with engine.begin() as c:
            n = c.execute(text("SELECT COUNT(*) FROM process_rules")).scalar() or 0
            if n:
                print(f"[migration] process_rules {n}행이 있어 market 축 이관을 건너뜁니다 "
                      f"— 수동 확인 필요")
                return
            c.execute(text("DROP TABLE process_rules"))
            print("[migration] process_rules 재생성 (market 축 추가, 0행이라 안전)")
    except Exception as e:      # noqa: BLE001
        print(f"[migration] process_rules 점검 건너뜀: {e}")


def _repoint_account_upload_policies(eng=None) -> bool:
    """[2026-07-20] 업로드 속도 정책의 주인을 market_accounts → upload_accounts 로.

    ■ 왜
      판매처 관리 화면은 ``upload_accounts`` 에만 쓰는데 속도 정책은
      ``market_accounts`` 를 봤다. 후자는 일회성 마이그레이션 스크립트만 채워서
      **계정을 30개 등록해도 속도 정책은 0개**였다 (라이브 확인).

    ■ 왜 통째로 지우나
      ``account_id`` 가 market_accounts.id 를 가리키는 FK 라 그대로 두면
      PostgreSQL 이 새 계정 저장을 거부한다. 이 파일의 마이그레이션 경로에는
      ADD/DROP CONSTRAINT 가 없다.
      게다가 **남은 옛 행이 더 위험하다** — market_accounts.id 3번의 속도가
      upload_accounts.id 3번(전혀 다른 계정)에 조용히 붙는다.

      ★ 지워도 되는 이유: 이 표를 고치는 화면(`/api/upload/account-speed`)이
        market_accounts 를 읽었고 그게 0개라 **아무것도 보여주지 못했다**.
        즉 사장님이 손으로 정한 값이 애초에 있을 수 없다. 남은 건 자동 시드된
        기본값(6초에 1개)뿐이고, 지우면 다음 조회 때 같은 값으로 다시 시드된다.

    Returns:
        실제로 갈아엎었으면 True (멱등 — 두 번째부터는 False).
    """
    from sqlalchemy import inspect, text
    eng = eng if eng is not None else engine
    try:
        insp = inspect(eng)
        if 'account_upload_policies' not in set(insp.get_table_names()):
            return False
        fks = insp.get_foreign_keys('account_upload_policies')
        if not any(fk.get('referred_table') == 'market_accounts' for fk in fks):
            return False                # 이미 새 스키마
        with eng.begin() as c:
            n = c.execute(text("SELECT COUNT(*) FROM account_upload_policies")).scalar() or 0
            c.execute(text("DROP TABLE account_upload_policies"))
        print(f"[migration] account_upload_policies 재생성 "
              f"(주인 market_accounts → upload_accounts, 옛 기본값 {n}행 폐기)")
        return True
    except Exception as e:      # noqa: BLE001
        print(f"[migration] account_upload_policies 점검 건너뜀: {e}")
        return False


def init_db() -> None:
    """후속 모듈이 등록한 모든 모델 테이블을 생성한다 (멱등)."""
    _drop_stale_process_rules()     # ★ create_all 보다 먼저 — 지운 뒤 새로 만들어야 한다
    _repoint_account_upload_policies()      # ★ 같은 이유로 create_all 앞
    Base.metadata.create_all(engine)
    from lemouton.sets.schema_patch import ensure_market_columns
    ensure_market_columns(engine)
    _apply_lightweight_migrations()
    # [2026-06-30 단일명부] 빌트인 6개 seed + 기존 가이드 이관 (멱등, 컬럼 보강 이후)
    try:
        from lemouton.sourcing.source_registry import seed_builtins
        seed_builtins()
        from lemouton.sourcing.roster import migrate_guides_from_registry
        migrate_guides_from_registry()
    except Exception:
        pass
    # [2026-07-18 대량등록 Phase 1B M1-2] 결제카드 마스터 시드 (멱등, key 단위
    # insert-if-missing → 사용자가 화면에서 고친 적립율을 재부팅이 원복하지 않는다).
    try:
        from lemouton.margin.purchase_card_store import seed_purchase_cards
        _s = SessionLocal()
        try:
            seed_purchase_cards(_s)
        finally:
            _s.close()
    except Exception:
        pass  # 테이블 미생성 등 — 다음 startup 에 재시도
    # [2026-07-19 대량등록 Phase 1B M1-5] 소싱처별 OK캐시백 적립율 시드 (멱등,
    # (source_id, benefit_name) insert-if-missing + 캐시백 행 존재 시 통째 skip
    # → 라이브의 기존 캐시백 행과 이중 차감 충돌을 원천 차단).
    # 카드 청구할인 시드는 확인된 값이 없어 오늘은 no-op 이다.
    # [2026-07-19] 마켓 API 한도 시드 — 공식문서에서 확인된 3건만(쿠팡·옥션·G마켓).
    #   멱등 insert-if-missing → 사장님이 화면에서 고친 값을 재부팅이 되돌리지 않는다.
    try:
        from lemouton.uploader.market_rate_seed import seed_market_rates
        _s3 = SessionLocal()
        try:
            if seed_market_rates(_s3):
                _s3.commit()
        finally:
            _s3.close()
    except Exception:
        pass  # 테이블 미생성 등 — 다음 startup 에 재시도

    try:
        from lemouton.sourcing.source_benefit_seed import seed_source_benefits
        _s2 = SessionLocal()
        try:
            seed_source_benefits(_s2)
        finally:
            _s2.close()
    except Exception:
        pass  # 테이블 미생성 등 — 다음 startup 에 재시도


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
        # [2026-07-20] 스스·쿠팡 외 마켓 수수료율 (미설정=NULL — 임의 기본값 금지)
        # [2026-07-20] 스스·쿠팡 외 4개 마켓 가격 정책 (수수료 + 3가지 책정 × 소싱/사입)
        ("price_templates", "lotteon_pricing_policy", "VARCHAR(16) DEFAULT 'cheapest'"),
        ("price_templates", "lotteon_unify_rule", "VARCHAR(16) DEFAULT 'max'"),
        ("price_templates", "eleven11_pricing_policy", "VARCHAR(16) DEFAULT 'cheapest'"),
        ("price_templates", "eleven11_unify_rule", "VARCHAR(16) DEFAULT 'max'"),
        ("price_templates", "auction_pricing_policy", "VARCHAR(16) DEFAULT 'cheapest'"),
        ("price_templates", "auction_unify_rule", "VARCHAR(16) DEFAULT 'max'"),
        ("price_templates", "gmarket_pricing_policy", "VARCHAR(16) DEFAULT 'cheapest'"),
        ("price_templates", "gmarket_unify_rule", "VARCHAR(16) DEFAULT 'max'"),
        # 롯데온
        ("price_templates", "lotteon_fee_rate", "FLOAT DEFAULT 0.13"),
        ("price_templates", "lotteon_normal_price", "INTEGER DEFAULT 149000"),
        ("price_templates", "lotteon_boxhero_sale_price", "INTEGER DEFAULT 0"),
        ("price_templates", "lotteon_external_sale_price", "INTEGER DEFAULT 0"),
        ("price_templates", "lotteon_mode_sourcing", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "lotteon_rate_sourcing", "FLOAT DEFAULT 0.1242"),
        ("price_templates", "lotteon_amount_sourcing", "INTEGER DEFAULT 0"),
        ("price_templates", "lotteon_mode_purchase", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "lotteon_rate_purchase", "FLOAT DEFAULT 0.1242"),
        ("price_templates", "lotteon_amount_purchase", "INTEGER DEFAULT 0"),
        ("price_templates", "lotteon_delivery_fee", "INTEGER DEFAULT 0"),
        ("price_templates", "lotteon_return_fee", "INTEGER DEFAULT 0"),
        ("price_templates", "lotteon_exchange_fee", "INTEGER DEFAULT 0"),
        # 11번가
        ("price_templates", "eleven11_fee_rate", "FLOAT DEFAULT 0.13"),
        ("price_templates", "eleven11_normal_price", "INTEGER DEFAULT 149000"),
        ("price_templates", "eleven11_boxhero_sale_price", "INTEGER DEFAULT 0"),
        ("price_templates", "eleven11_external_sale_price", "INTEGER DEFAULT 0"),
        ("price_templates", "eleven11_mode_sourcing", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "eleven11_rate_sourcing", "FLOAT DEFAULT 0.1242"),
        ("price_templates", "eleven11_amount_sourcing", "INTEGER DEFAULT 0"),
        ("price_templates", "eleven11_mode_purchase", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "eleven11_rate_purchase", "FLOAT DEFAULT 0.1242"),
        ("price_templates", "eleven11_amount_purchase", "INTEGER DEFAULT 0"),
        ("price_templates", "eleven11_delivery_fee", "INTEGER DEFAULT 0"),
        ("price_templates", "eleven11_return_fee", "INTEGER DEFAULT 0"),
        ("price_templates", "eleven11_exchange_fee", "INTEGER DEFAULT 0"),
        # 옥션
        ("price_templates", "auction_fee_rate", "FLOAT DEFAULT 0.13"),
        ("price_templates", "auction_normal_price", "INTEGER DEFAULT 149000"),
        ("price_templates", "auction_boxhero_sale_price", "INTEGER DEFAULT 0"),
        ("price_templates", "auction_external_sale_price", "INTEGER DEFAULT 0"),
        ("price_templates", "auction_mode_sourcing", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "auction_rate_sourcing", "FLOAT DEFAULT 0.1242"),
        ("price_templates", "auction_amount_sourcing", "INTEGER DEFAULT 0"),
        ("price_templates", "auction_mode_purchase", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "auction_rate_purchase", "FLOAT DEFAULT 0.1242"),
        ("price_templates", "auction_amount_purchase", "INTEGER DEFAULT 0"),
        ("price_templates", "auction_delivery_fee", "INTEGER DEFAULT 0"),
        ("price_templates", "auction_return_fee", "INTEGER DEFAULT 0"),
        ("price_templates", "auction_exchange_fee", "INTEGER DEFAULT 0"),
        # G마켓
        ("price_templates", "gmarket_fee_rate", "FLOAT DEFAULT 0.13"),
        ("price_templates", "gmarket_normal_price", "INTEGER DEFAULT 149000"),
        ("price_templates", "gmarket_boxhero_sale_price", "INTEGER DEFAULT 0"),
        ("price_templates", "gmarket_external_sale_price", "INTEGER DEFAULT 0"),
        ("price_templates", "gmarket_mode_sourcing", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "gmarket_rate_sourcing", "FLOAT DEFAULT 0.1242"),
        ("price_templates", "gmarket_amount_sourcing", "INTEGER DEFAULT 0"),
        ("price_templates", "gmarket_mode_purchase", "VARCHAR(8) DEFAULT 'rate'"),
        ("price_templates", "gmarket_rate_purchase", "FLOAT DEFAULT 0.1242"),
        ("price_templates", "gmarket_amount_purchase", "INTEGER DEFAULT 0"),
        ("price_templates", "gmarket_delivery_fee", "INTEGER DEFAULT 0"),
        ("price_templates", "gmarket_return_fee", "INTEGER DEFAULT 0"),
        ("price_templates", "gmarket_exchange_fee", "INTEGER DEFAULT 0"),
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
        # 2026-06-21: URL 타입 — 단품/색상모음전/모델모음전
        ("bundle_source_urls", "url_type", "VARCHAR(16) DEFAULT '단품' NOT NULL"),
        # 2026-05-25: 판매가 정책 (색상 통일 / 옵션별 cheapest) — A2+D3 시안 적용
        ("price_templates", "pricing_policy", "VARCHAR(16) DEFAULT 'cheapest'"),
        # 2026-07-15: 마켓별 색상 통일 (스스/쿠팡 각각) + 통일 규칙(max/src_cheapest)
        ("price_templates", "ss_pricing_policy", "VARCHAR(16) DEFAULT 'cheapest'"),
        ("price_templates", "ss_unify_rule", "VARCHAR(16) DEFAULT 'max'"),
        ("price_templates", "coupang_pricing_policy", "VARCHAR(16) DEFAULT 'cheapest'"),
        ("price_templates", "coupang_unify_rule", "VARCHAR(16) DEFAULT 'max'"),
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
        # [2026-06-13 / 복원 2026-06-28] 크롤 차단 게이트 — 유효 소싱가 없는 옵션 판매차단.
        #   2026-06-22 stale 머지(94466889)에서 컬럼 유실 → 복원. (S14 가짜 '재고있음'·게이트 inert 원인)
        ("options", "crawl_blocked", "BOOLEAN DEFAULT 0 NOT NULL"),
        # 2026-06-05: 혜택 표시 카테고리 (정액/정률/결제/캐시백/기타) — 새 혜택 추가 모달에서 사용자 지정
        ("source_benefit_templates", "category", "VARCHAR(16)"),
        ("option_benefit_overrides", "category", "VARCHAR(16)"),
        # 2026-06-06: 소싱처 크롤링 가이드 JSON (crawl_guide) + 크롤 작업 검증 URL
        ("source_registry", "crawl_guide", "TEXT"),
        ("crawl_jobs", "verify_url", "VARCHAR(512)"),
        # 2026-06-30: 소싱처 단일 명부 통합 — SourcingSource 가 전 소싱처(빌트인+커스텀) 명부
        ("sourcing_sources", "is_builtin", "BOOLEAN DEFAULT 0 NOT NULL"),
        ("sourcing_sources", "crawl_guide", "TEXT"),
        # 2026-06-08: 혜택 태그 (최종 매입가 계산 엔진)
        ("source_benefit_templates", "apply_mode", "VARCHAR(16)"),
        ("source_benefit_templates", "pay_method", "VARCHAR(16)"),
        ("source_benefit_templates", "channel", "VARCHAR(16)"),
        ("option_benefit_overrides", "apply_mode", "VARCHAR(16)"),
        ("option_benefit_overrides", "pay_method", "VARCHAR(16)"),
        ("option_benefit_overrides", "channel", "VARCHAR(16)"),
        # 2026-07-19: 캐시백 기준금액 계수 (대량등록 Phase 1B).
        #   캐시백 사이트는 결제 전액이 아니라 **부가세 뺀 공급가**에 적립한다
        #   → 0.9 = 공급가 기준 / 1.0 = 전액 기준(SSG·신세계쇼핑·CJ).
        #   DEFAULT 1.0 이라 기존 행은 계수 없음(동작 불변) — 캐시백 행에만 0.9 를 세팅한다.
        ("source_benefit_templates", "base_ratio", "FLOAT DEFAULT 1.0"),
        ("option_benefit_overrides", "base_ratio", "FLOAT DEFAULT 1.0"),
        # 2026-07-01: 자동화 설정 (크롤 자동 주기 + 판매처 자동 전송)
        ("global_settings", "crawl_auto_enabled", "BOOLEAN DEFAULT 0 NOT NULL"),
        ("global_settings", "crawl_interval_minutes", "INTEGER DEFAULT 0 NOT NULL"),
        ("global_settings", "autosend_mode", "VARCHAR(8) DEFAULT 'preview' NOT NULL"),
        ("global_settings", "autosend_on_purchase", "BOOLEAN DEFAULT 1 NOT NULL"),
        ("global_settings", "autosend_on_stock", "BOOLEAN DEFAULT 1 NOT NULL"),
        ("global_settings", "autosend_stock_threshold", "INTEGER DEFAULT 4 NOT NULL"),
        ("global_settings", "autosend_on_price", "BOOLEAN DEFAULT 1 NOT NULL"),
        # 2026-07-01: 구성별 자동 전송 예외 (follow|on|off) — (구) 하위호환
        ("product_sets", "auto_stock_mode", "VARCHAR(8) DEFAULT 'follow' NOT NULL"),
        ("product_sets", "auto_price_mode", "VARCHAR(8) DEFAULT 'follow' NOT NULL"),
        # 2026-07-01: 구성별 자동 모드(on|off|manual) + 수동설정 주기(시:분)
        ("product_sets", "auto_mode", "VARCHAR(8) DEFAULT 'on' NOT NULL"),
        ("product_sets", "manual_crawl_hours", "INTEGER DEFAULT 1 NOT NULL"),
        ("product_sets", "manual_crawl_minutes", "INTEGER DEFAULT 0 NOT NULL"),
        ("product_sets", "manual_upload_hours", "INTEGER DEFAULT 3 NOT NULL"),
        ("product_sets", "manual_upload_minutes", "INTEGER DEFAULT 0 NOT NULL"),
        # 2026-07-04: 자동화 연속 배수 큐 — 계수·무변동 연속
        ("source_products", "crawl_weight", "INTEGER DEFAULT 1 NOT NULL"),
        ("source_products", "no_change_streak", "INTEGER DEFAULT 0 NOT NULL"),
        ("source_products", "crawl_lap_count", "INTEGER DEFAULT 0 NOT NULL"),
        # 2026-07-19: 크롤 주기 등급 — 뜸하게 긁는 쪽 손잡이.
        #   계수(Integer)로는 「3일에 1회」를 못 담는다: int(1/3)==0 이고 계수 0 은
        #   '크롤 제외'라 상품이 영영 안 긁힌다. 그래서 방향을 갈라 별도 배수를 둔다.
        #   ★DEFAULT 1.0 = 예전과 완전히 같은 동작 (기존 행은 아무것도 안 바뀐다).
        ("source_products", "crawl_slowdown", "FLOAT DEFAULT 1.0 NOT NULL"),
        ("crawl_weight_rules", "slowdown", "FLOAT DEFAULT 1.0 NOT NULL"),
        # 2026-07-19: 업로드 속도 「X초에 Y개」 (사장님 확정).
        #   옛 seconds_per_item(1개당 N초)은 한 계정이 초당 1개가 최대라
        #   「1초에 10개」도 「10초에 30개」(순간 몰림)도 못 담았다.
        #   ★ 옛 칸은 지우지 않는다 — NULL 이면 옛 칸에서 「N초에 1개」로 읽는다.
        ("account_upload_policies", "window_seconds", "INTEGER"),
        ("account_upload_policies", "max_count", "INTEGER"),
        # 2026-07-05: 옵션별 브랜드 (한 모음전에 여러 브랜드 섞임) — NULL=미지정(Model.brand 상속)
        ("options", "brand", "VARCHAR(100)"),
        # 2026-07-05: 롯데온 자동전송 formatter 용 — 마스터의 롯데온 상품/옵션 ID.
        #             NULL=미매핑 → build_lotteon_payload 가 None → 자동전송 0(안전).
        ("models", "lotteon_product_id", "VARCHAR(64)"),
        ("options", "lotteon_option_id", "VARCHAR(128)"),
        # 2026-07-09: 옥션·G마켓(ESM 2.0) 자동전송 formatter 용 — 마스터 goodsNo·옵션 manageCode.
        #             NULL=미매핑 → build_{auction,gmarket}_payload 가 None → 자동전송 0(안전).
        ("models", "auction_product_id", "VARCHAR(64)"),
        ("models", "gmarket_product_id", "VARCHAR(64)"),
        ("options", "auction_option_id", "VARCHAR(128)"),
        ("options", "gmarket_option_id", "VARCHAR(128)"),
        # 2026-07-05: (폐기) market_upload_policies — P4 마켓 per_minute 정책 제거,
        #             계정 단위(account_upload_policies)로 흡수. 기존 DB의 잔여 테이블은
        #             참조 안 함(무해). 업로드 속도 정본 = 계정.
        # 2026-07-04: account_upload_policies 신규 테이블 → create_all 생성
        # 2026-07-05: crawl_weight_rules 신규 테이블 → create_all 생성
        # 2026-07-10: invoice_ledger 신규 테이블(송장 원장) → create_all 생성(FK 없음)
        # 2026-07-12: 배송검사 v2 — 마켓 API 조회 캐시(mango_orders)
        ("mango_orders", "market_api_status", "VARCHAR(32)"),
        ("mango_orders", "market_api_status_raw", "VARCHAR(64)"),
        ("mango_orders", "market_api_invoice", "VARCHAR(64)"),
        ("mango_orders", "market_shipped_at", "VARCHAR(32)"),
        ("mango_orders", "market_checked_at", "DATETIME"),
        ("mango_orders", "market_check_error", "VARCHAR(200)"),
        # 2026-07-16: CS 대응완료 수기 삭제 플래그 (claim_handling 은 #2 로 이미 배포됨 → ALTER 보강)
        ("claim_handling", "dismissed_at", "DATETIME"),
        # 2026-07-18: 대량등록 Phase 1A — product_draft_markets.account_key.
        #   Task 8 이 마켓당 다계정 대비로 account_key 를 모델에 추가했는데(마켓 상품번호가
        #   계정마다 다름), create_all 은 기존 테이블에 컬럼을 안 붙인다. Task 2~8 개발 중
        #   먼저 생성된 DB(로컬 SQLite 등)는 이 컬럼이 없어 /bulk 등록·목록이 500 이 난다.
        #   fresh DB·미배포 Supabase 는 create_all 이 이미 포함하므로 여기선 no-op(멱등).
        ("product_draft_markets", "account_key", "VARCHAR(64) DEFAULT 'default' NOT NULL"),
        # 2026-07-19: 대량등록 Phase 1B M3-1 — 역마진 가드 최소 마진금액(원).
        #   global_settings 는 이미 라이브에 존재하는 테이블이라 create_all 이 컬럼을
        #   붙이지 못한다 → 여기 ADD COLUMN 이 유일한 경로. 기본 0 = 오늘과 동일 동작.
        # 2026-07-19: price_snapshots 는 신규 테이블 → create_all 이 생성(인덱스 포함).
        ("global_settings", "min_margin_amount", "INTEGER DEFAULT 0 NOT NULL"),
        # 2026-07-19: 대량등록 Phase 1B M2 — 수기 화면 「6 매입가·마진」 6칸 저장.
        #   product_drafts 는 Phase 1A 로 이미 라이브에 존재하는 테이블이라
        #   create_all 이 컬럼을 붙이지 못한다 → 여기 ADD COLUMN 이 유일한 경로.
        #   ★ DEFAULT 를 일부러 안 건다. NULL(입력 안 받음) / ''(소싱처 기본값) /
        #     'none'(없음 명시) 셋을 구분해야 하는데, DEFAULT 를 걸면 기존 행이
        #     '사용자가 고른 값'으로 둔갑한다(폴백 금지).
        #   폭은 값이 흘러오는 원본 컬럼에 맞춘다 — card_key=PurchaseCard.key(64),
        #   cashback_name=SourceBenefitTemplate.benefit_name(120). 좁히면 개발기
        #   (SQLite, 길이 무시)에서는 통과하고 라이브(PostgreSQL)에서만 깨진다.
        ("product_drafts", "pricing_source_id", "INTEGER"),
        ("product_drafts", "surface_price", "INTEGER"),
        ("product_drafts", "pricing_inflow", "VARCHAR(16)"),
        ("product_drafts", "pricing_card_key", "VARCHAR(64)"),
        ("product_drafts", "pricing_naver_pay", "VARCHAR(16)"),
        ("product_drafts", "pricing_cashback_name", "VARCHAR(120)"),
        # 2026-07-20: 판매처 계정 라이브 검증(실주문 조회 왕복 확인) 기록.
        #   upload_accounts 는 이미 라이브에 존재하는 테이블이라 create_all 이 컬럼을
        #   붙이지 못한다 → 여기 ADD COLUMN 이 유일한 경로.
        #   ★ DEFAULT 를 일부러 안 건다. NULL = '아직 검증 안 함' 이어야 하는데
        #     DEFAULT 를 걸면 기존 계정 전부가 '검증됨'으로 둔갑해 미검증 마켓이
        #     그대로 공개된다(틀린 주문 숫자가 주문내역·마진계산기로 유입).
        ("upload_accounts", "live_verified_at", "DATETIME"),
        ("upload_accounts", "live_verified_count", "INTEGER"),
        # 2026-07-22: 자동전환 이력의 실행 주체(manual|auto). 코드는 source 를 쓰는데
        # 컬럼이 없어 설정 화면이 500 — 기존 행은 manual 로 채움(전부 버튼 실행이던 시기).
        ("auto_confirm_log", "source", "VARCHAR(16) DEFAULT 'manual' NOT NULL"),
        # 2026-07-20: 백필을 웹 워커 → 스케줄러로 옮기며 추가된 컬럼.
        #   order_ingest_runs 는 같은 날 먼저 배포돼 이미 라이브에 있던 테이블이라
        #   create_all 이 컬럼을 붙이지 못했다(status 조회가 500 으로 죽었다).
        #   requested = 백필 요청됨(스케줄러가 가져갈 신호) / cursor = 이어할 지점.
        ("order_ingest_runs", "requested", "VARCHAR(8)"),
        ("order_ingest_runs", "cursor", "VARCHAR(8)"),
        # 2026-07-21: 마켓 한도의 적용 범위. 'shared'(계정 전체로 묶임) / 'account'(계정당 천장).
        #   실측으로 쿠팡·스마트스토어가 계정별임을 확인 → 계정 수만큼 총량이 늘게 하는 칸.
        #   기본 'shared' = 보수적(기존 동작 보존). 확인된 마켓만 seed 가 'account' 로 올린다.
        ("market_upload_policies", "limit_scope", "VARCHAR(16) DEFAULT 'shared'"),
        # 2026-07-23: M2 카테고리 맵핑 — 드래프트의 소싱처 카테고리 경로.
        #   product_drafts 는 이미 라이브에 존재하는 테이블이라 create_all 이 컬럼을
        #   붙이지 못한다 → 여기 ADD COLUMN 이 유일한 경로. 수기 드래프트는 NULL(소싱처 없음).
        ("product_drafts", "source_site", "VARCHAR(40)"),
        ("product_drafts", "source_category_path", "VARCHAR(500)"),
        # 2026-07-23: 카테고리 전수수집 진행률 — category_harvest_runs 는 이미 라이브에
        # 존재하는 테이블이라 create_all 이 컬럼을 붙이지 못한다. progress_at 이 오래
        # 안 움직이면(예: 20분 전) 죽은 실행으로 의심할 근거가 된다.
        ("category_harvest_runs", "progress_count", "INTEGER"),
        ("category_harvest_runs", "progress_at", "DATETIME"),
        # 2026-07-23 사고 #5: 콜 예산 소진으로 "미완" 종료한 실행을 완료로 칠하지 않기 위한 플래그.
        # NULL/False = 완주(옛 행 포함). lemouton/registration/models.py 의 주석이 정본.
        ("category_harvest_runs", "incomplete", "BOOLEAN"),
        # 2026-07-23: 이어받기 자식누락 차단 — market_categories 는 이미 라이브에 존재하는
        # 테이블이라 create_all 이 컬럼을 붙이지 못한다. NULL=모름(옛 데이터) → harvest_coupang
        # known=... 이어받기가 재fetch 로 안전하게 처리한다(lemouton/registration/models.py 주석 참조).
        ("market_categories", "child_count", "INTEGER"),
        # [2026-07-23 M3] 소싱처 상품의 카테고리 경로(빵부스러기) — 크롤이 채운다.
        ("source_products", "category_path", "VARCHAR(500)"),
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

        # ESM 주문조회 5초/1회 스로틀을 gunicorn 워커 3개가 공유하기 위한 테이블.
        #   '다음 허용 시각(epoch)'을 계정 키별로 한 행에 둔다. 인메모리 dict 는
        #   프로세스 간 공유가 안 돼 3000('불러오지 못했어요')의 원인이었다(2026-07-22).
        #   shared/platforms/esm/client.py 가 자기충족 생성도 하지만 부팅 때 미리 만든다.
        try:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS esm_order_throttle ("
                "throttle_key TEXT PRIMARY KEY, "
                "next_slot_epoch DOUBLE PRECISION NOT NULL DEFAULT 0)"))
        except Exception:
            pass

        # 주문조회 결과의 워커 간 공유 캐시(L2). L1(프로세스 메모리)은 워커마다 따로라
        #   같은 주문을 최대 3번 재조회했다. 화면 경로 결과를 90초 TTL 로 DB 에 공유한다.
        #   lemouton/markets/order_export.py 가 자기충족 생성도 하지만 부팅 때 미리 만든다.
        try:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS order_rows_cache ("
                "cache_key TEXT PRIMARY KEY, "
                "cached_at_epoch DOUBLE PRECISION NOT NULL, "
                "payload TEXT NOT NULL)"))
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
