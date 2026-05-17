"""[v2] 마이그레이션 스크립트 — Phase A → B 진입.

Phase A: 신규 10 테이블 추가 + 기존 테이블 deleted_at 컬럼 추가
Phase B: 기존 5 컬럼 데이터 → SourceProduct/Link 자동 변환
Phase C: 코드 베이스 v2 참조 변경 (별도 PR로)
Phase D: 기존 5 컬럼 제거 (별도 릴리즈)

설계 문서: docs/architecture_v2.md §4

사용:
  python scripts/migrate_to_v2.py phase-a              # 신규 테이블 + 컬럼 추가 (멱등)
  python scripts/migrate_to_v2.py phase-b              # 데이터 이전 (Phase A 완료 전제)
  python scripts/migrate_to_v2.py status               # 현재 상태 진단
  python scripts/migrate_to_v2.py phase-a --dry-run    # 실제 실행 없이 SQL만 출력
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect, text
from shared.db import SessionLocal, engine, Base, init_db


# ─────────────────────────────────────────────────────────────────────────────
# 모델 등록 — 기존 v1 + 신규 v2 (FK 해결 위해 모두 메타데이터에 등록)
# ─────────────────────────────────────────────────────────────────────────────
import lemouton.sourcing.models  # noqa: F401  v1: Model, Option
import lemouton.templates.models  # noqa: F401  v1: PriceTemplate, ComboSet, ...
import lemouton.uploader.models  # noqa: F401  v1: MarketRegistration
import lemouton.sources.models  # noqa: F401  v2: SourceProduct, ...
import lemouton.multitenancy.models  # noqa: F401  v2: MarketAccount, ...
import lemouton.audit.models  # noqa: F401  v2: AuditLog


# Phase A: 기존 테이블에 추가할 deleted_at 컬럼 (soft-delete)
SOFT_DELETE_TARGETS = [
    'models',
    'options',
    'combo_sets',
    'price_templates',
    'color_templates',
    'size_templates',
]

# Phase A: PriceTrackHistory v2 정규화 컬럼
EXTRA_COLUMNS = [
    ('price_track_history', 'source_option_id', 'INTEGER REFERENCES source_options(id)'),
]

# 신규 v2 테이블
V2_TABLES = [
    'source_products',
    'source_options',
    'model_source_links',
    'option_source_links',
    'market_accounts',
    'bundle_account_registrations',
    'option_account_registrations',
    'audit_log',
]


# ─────────────────────────────────────────────────────────────────────────────
# Phase A: 신규 테이블 + soft-delete 컬럼
# ─────────────────────────────────────────────────────────────────────────────

def phase_a(dry_run: bool = False) -> dict:
    """신규 10 테이블 생성 + 기존 6 테이블에 deleted_at 컬럼 추가.

    멱등 — 이미 있으면 skip.
    """
    result = {'tables_created': [], 'tables_skipped': [],
              'columns_added': [], 'columns_skipped': []}

    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())

    # Step A.1 — 신규 테이블 생성
    if dry_run:
        for t in V2_TABLES:
            if t in existing_tables:
                result['tables_skipped'].append(t)
            else:
                result['tables_created'].append(t)
                print(f"  [DRY] CREATE TABLE {t} (...)")
    else:
        # init_db() 가 모든 신규 모델 테이블을 멱등 생성
        before = set(insp.get_table_names())
        init_db()
        after = set(inspect(engine).get_table_names())
        for t in V2_TABLES:
            if t in before:
                result['tables_skipped'].append(t)
            elif t in after:
                result['tables_created'].append(t)

    # Step A.2 — 기존 테이블에 deleted_at 컬럼 추가 (SQLite ALTER TABLE)
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    for table_name in SOFT_DELETE_TARGETS:
        if table_name not in existing_tables:
            result['columns_skipped'].append(f"{table_name}.deleted_at (no table)")
            continue
        cols = {c['name'] for c in insp.get_columns(table_name)}
        if 'deleted_at' in cols:
            result['columns_skipped'].append(f"{table_name}.deleted_at")
            continue
        ddl = f"ALTER TABLE {table_name} ADD COLUMN deleted_at DATETIME"
        if dry_run:
            print(f"  [DRY] {ddl}")
        else:
            with engine.begin() as conn:
                conn.execute(text(ddl))
        result['columns_added'].append(f"{table_name}.deleted_at")

    # Step A.3 — 추가 v2 컬럼 (PriceTrackHistory.source_option_id 등)
    for table_name, col_name, col_def in EXTRA_COLUMNS:
        if table_name not in existing_tables:
            result['columns_skipped'].append(f"{table_name}.{col_name} (no table)")
            continue
        cols = {c['name'] for c in insp.get_columns(table_name)}
        if col_name in cols:
            result['columns_skipped'].append(f"{table_name}.{col_name}")
            continue
        ddl = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}"
        if dry_run:
            print(f"  [DRY] {ddl}")
        else:
            with engine.begin() as conn:
                conn.execute(text(ddl))
        result['columns_added'].append(f"{table_name}.{col_name}")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Phase B: 데이터 이전 (Day 8 에 완성 — 골격만)
# ─────────────────────────────────────────────────────────────────────────────

def phase_b(dry_run: bool = False) -> dict:
    """기존 5컬럼 → SourceProduct/Link 자동 변환.

    멱등 — 이미 변환된 것은 skip.
    """
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option
    from lemouton.sources.service import (
        upsert_source_product, upsert_source_option,
        link_model_to_source, link_option_to_source,
    )

    SOURCE_FIELD_MAP = {
        'lemouton': ('url_lemouton', 'option_id_lemouton'),
        'musinsa': ('url_musinsa', 'option_id_musinsa'),
        'ssf': ('url_ssf', 'option_id_ssf'),
        'lotteon': ('url_lotteon', 'option_id_lotteon'),
        'ss_lemouton': ('url_ss_lemouton', 'option_id_ss_lemouton'),
    }

    result = {
        'source_products_created': 0, 'source_products_skipped': 0,
        'model_links_created': 0, 'option_links_created': 0,
        'source_options_created': 0,
        'accounts_created': 0, 'bundle_regs_created': 0,
        'option_regs_created': 0,
    }

    s = SessionLocal()
    try:
        # ── B.1 Model 5컬럼 → SourceProduct + ModelSourceLink
        models = s.query(Model).all()
        for m in models:
            for site, (url_field, _) in SOURCE_FIELD_MAP.items():
                url = getattr(m, url_field, None)
                if not url:
                    continue
                if dry_run:
                    print(f"  [DRY] SourceProduct site={site} url={url[:60]}... + link to {m.model_code}")
                    continue
                # 멱등: 이미 있으면 같은 sp 반환
                from lemouton.sources.models import SourceProduct
                pre_count = s.query(SourceProduct).filter_by(site=site, url=url).count()
                sp = upsert_source_product(s, site=site, url=url)
                if pre_count == 0:
                    result['source_products_created'] += 1
                else:
                    result['source_products_skipped'] += 1
                pre_link = (s.query(__import__('lemouton.sources.models',
                            fromlist=['ModelSourceLink']).ModelSourceLink)
                            .filter_by(model_code=m.model_code,
                                       source_product_id=sp.id).count())
                link_model_to_source(s, model_code=m.model_code,
                                     source_product_id=sp.id)
                if pre_link == 0:
                    result['model_links_created'] += 1

        # ── B.2 Option 5컬럼 → SourceOption + OptionSourceLink
        opts = s.query(Option).all()
        from lemouton.sources.models import SourceProduct
        for o in opts:
            m = s.query(Model).filter_by(model_code=o.model_code).first()
            if m is None:
                continue
            for site, (url_field, opt_id_field) in SOURCE_FIELD_MAP.items():
                url = getattr(m, url_field, None)
                opt_external_id = getattr(o, opt_id_field, None)
                if not url:
                    continue
                sp = (s.query(SourceProduct)
                      .filter_by(site=site, url=url, deleted_at=None)
                      .first())
                if sp is None:
                    continue
                if dry_run:
                    print(f"  [DRY] SourceOption color={o.color_code} size={o.size_code} on {site}")
                    continue
                from lemouton.sources.models import SourceOption
                pre_so = (s.query(SourceOption)
                          .filter_by(source_product_id=sp.id,
                                     color_text=o.color_code,
                                     size_text=o.size_code).count())
                so = upsert_source_option(
                    s, source_product_id=sp.id,
                    color_text=o.color_code, size_text=o.size_code,
                    external_option_id=opt_external_id,
                )
                if pre_so == 0:
                    result['source_options_created'] += 1
                from lemouton.sources.models import OptionSourceLink
                pre_olink = (s.query(OptionSourceLink)
                             .filter_by(canonical_sku=o.canonical_sku,
                                        source_option_id=so.id).count())
                link_option_to_source(s, canonical_sku=o.canonical_sku,
                                      source_option_id=so.id)
                if pre_olink == 0:
                    result['option_links_created'] += 1

        # ── B.3 .env 자격증명 → MarketAccount("default")
        # 자동 생성 — 멱등
        from lemouton.multitenancy.models import MarketAccount
        from lemouton.multitenancy.service import create_account
        ss_id = os.environ.get('SMARTSTORE_CLIENT_ID')
        ss_secret = os.environ.get('SMARTSTORE_CLIENT_SECRET')
        if ss_id and ss_secret:
            existing = (s.query(MarketAccount)
                        .filter_by(market='smartstore', account_name='default')
                        .first())
            if existing is None and not dry_run:
                create_account(s, market='smartstore', account_name='default',
                               credentials={'client_id': ss_id,
                                            'client_secret': ss_secret},
                               note='Phase B 자동 마이그레이션 — .env 에서 가져옴')
                result['accounts_created'] += 1

        cp_key = os.environ.get('COUPANG_ACCESS_KEY')
        cp_secret = os.environ.get('COUPANG_SECRET_KEY')
        cp_vendor = os.environ.get('COUPANG_VENDOR_ID')
        if cp_key and cp_secret:
            existing = (s.query(MarketAccount)
                        .filter_by(market='coupang', account_name='default')
                        .first())
            if existing is None and not dry_run:
                create_account(s, market='coupang', account_name='default',
                               credentials={'access_key': cp_key,
                                            'secret_key': cp_secret,
                                            'vendor_id': cp_vendor or ''},
                               note='Phase B 자동 마이그레이션 — .env 에서 가져옴')
                result['accounts_created'] += 1

        # ── B.4 Model.naver_product_id/coupang_product_id → BundleAccountRegistration
        from lemouton.multitenancy.service import upsert_bundle_registration
        ss_default = (s.query(MarketAccount)
                      .filter_by(market='smartstore', account_name='default').first())
        cp_default = (s.query(MarketAccount)
                      .filter_by(market='coupang', account_name='default').first())
        from lemouton.multitenancy.models import BundleAccountRegistration
        for m in models:
            if m.naver_product_id and ss_default and not dry_run:
                pre = (s.query(BundleAccountRegistration)
                       .filter_by(model_code=m.model_code,
                                  account_id=ss_default.id).count())
                upsert_bundle_registration(
                    s, model_code=m.model_code, account_id=ss_default.id,
                    external_product_id=m.naver_product_id, is_registered=True)
                if pre == 0:
                    result['bundle_regs_created'] += 1
            if m.coupang_product_id and cp_default and not dry_run:
                pre = (s.query(BundleAccountRegistration)
                       .filter_by(model_code=m.model_code,
                                  account_id=cp_default.id).count())
                upsert_bundle_registration(
                    s, model_code=m.model_code, account_id=cp_default.id,
                    external_product_id=m.coupang_product_id, is_registered=True)
                if pre == 0:
                    result['bundle_regs_created'] += 1

        # ── B.5 Option.naver_option_id/coupang_option_id → OptionAccountRegistration
        from lemouton.multitenancy.service import upsert_option_registration
        from lemouton.multitenancy.models import OptionAccountRegistration
        for o in opts:
            if o.naver_option_id and ss_default and not dry_run:
                pre = (s.query(OptionAccountRegistration)
                       .filter_by(canonical_sku=o.canonical_sku,
                                  account_id=ss_default.id).count())
                upsert_option_registration(
                    s, canonical_sku=o.canonical_sku, account_id=ss_default.id,
                    external_option_id=o.naver_option_id, is_visible=True)
                if pre == 0:
                    result['option_regs_created'] += 1
            if o.coupang_option_id and cp_default and not dry_run:
                pre = (s.query(OptionAccountRegistration)
                       .filter_by(canonical_sku=o.canonical_sku,
                                  account_id=cp_default.id).count())
                upsert_option_registration(
                    s, canonical_sku=o.canonical_sku, account_id=cp_default.id,
                    external_option_id=o.coupang_option_id, is_visible=True)
                if pre == 0:
                    result['option_regs_created'] += 1

        if not dry_run:
            s.commit()
    finally:
        s.close()

    print("[Phase B 결과]")
    for k, v in result.items():
        print(f"  {k}: {v}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 상태 진단
# ─────────────────────────────────────────────────────────────────────────────

def status() -> None:
    insp = inspect(engine)
    existing = set(insp.get_table_names())

    print("[v2 Phase A 진행 상황]\n")
    print("신규 테이블:")
    for t in V2_TABLES:
        mark = '[O]' if t in existing else '[X]'
        print(f"  {mark} {t}")

    print("\nSoft-delete 컬럼:")
    for t in SOFT_DELETE_TARGETS:
        if t not in existing:
            print(f"  ─ {t} (테이블 없음)")
            continue
        cols = {c['name'] for c in insp.get_columns(t)}
        mark = '[O]' if 'deleted_at' in cols else '[X]'
        print(f"  {mark} {t}.deleted_at")

    # v2 데이터 카운트
    print("\nv2 데이터 카운트:")
    s = SessionLocal()
    try:
        from lemouton.sources.models import SourceProduct
        from lemouton.multitenancy.models import MarketAccount, BundleAccountRegistration
        from lemouton.audit.models import AuditLog
        try:
            print(f"  SourceProduct           : {s.query(SourceProduct).count()}")
            print(f"  MarketAccount           : {s.query(MarketAccount).count()}")
            print(f"  BundleAccountRegistration: {s.query(BundleAccountRegistration).count()}")
            print(f"  AuditLog                : {s.query(AuditLog).count()}")
        except Exception as e:
            print(f"  (v2 테이블 미생성 — phase-a 먼저 실행) {e}")
    finally:
        s.close()


def main():
    parser = argparse.ArgumentParser(description='르무통 v2 마이그레이션')
    parser.add_argument('command', choices=['phase-a', 'phase-b', 'status'],
                        help='실행할 단계')
    parser.add_argument('--dry-run', action='store_true',
                        help='실제 실행 없이 SQL만 출력')
    args = parser.parse_args()

    if args.command == 'phase-a':
        result = phase_a(dry_run=args.dry_run)
        print("\n[Phase A 결과]")
        print(f"  테이블 신규 생성: {len(result['tables_created'])}")
        for t in result['tables_created']:
            print(f"    + {t}")
        print(f"  테이블 skip (이미 있음): {len(result['tables_skipped'])}")
        for t in result['tables_skipped']:
            print(f"    = {t}")
        print(f"  컬럼 신규 추가: {len(result['columns_added'])}")
        for c in result['columns_added']:
            print(f"    + {c}")
        print(f"  컬럼 skip: {len(result['columns_skipped'])}")
        for c in result['columns_skipped']:
            print(f"    = {c}")

    elif args.command == 'phase-b':
        phase_b(dry_run=args.dry_run)

    elif args.command == 'status':
        status()


if __name__ == '__main__':
    main()
