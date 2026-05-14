"""
SQLite → Supabase PostgreSQL 1회성 마이그레이션.

사용법:
  python migrations/sqlite_to_supabase.py --dry-run    # 검증만, 실제 이동 X (URL 필요)
  python migrations/sqlite_to_supabase.py --ping       # 연결만 테스트
  python migrations/sqlite_to_supabase.py              # 실제 마이그레이션
  python migrations/sqlite_to_supabase.py --verify     # row-count 검증만

전략:
  1. 신규 시스템의 SQLAlchemy 모델 import → Base.metadata 구성
  2. Target Supabase 에 init_db() — create_all + ALTER TABLE 멱등 적용 (dialect-agnostic)
  3. Source SQLite 의 모든 테이블 reflect → 동적으로 읽기
  4. Target 에 INSERT (boolean/datetime 변환은 SQLAlchemy 가 자동 처리)
  5. PostgreSQL sequence 재설정 (auto-increment 이어가게)
  6. row count 검증
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# UTF-8 출력
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ─── 경로 셋업 ───
THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
NEW_SYSTEM = PROJECT_ROOT / "_시스템"
OLD_DB = Path(r"C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템\data\lemouton.db")

# 신규 시스템 sys.path 추가 (모델 import 위해)
sys.path.insert(0, str(NEW_SYSTEM))

# .env 로드 — DATABASE_URL 등
from dotenv import load_dotenv
load_dotenv(NEW_SYSTEM / ".env", override=True)


# ─── 시스템 테이블 (스킵 대상) ───
SKIP_TABLES = {
    "sqlite_sequence",  # SQLite 내부 — PostgreSQL 없음
    "alembic_version",  # Alembic 메타 (도입 시)
}


def banner(s: str) -> None:
    print()
    print("─" * 60)
    print(s)
    print("─" * 60)


def get_target_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        # SQLAlchemy 2.0 은 postgresql:// 만 받음 (postgres:// 거부)
        url = "postgresql://" + url[len("postgres://"):]
    return url


def cmd_ping(target_url: str) -> int:
    """단순 연결 + SELECT 1 테스트."""
    from sqlalchemy import create_engine, text

    banner("Supabase 연결 ping")
    print(f"  URL: {target_url.split('@')[0]}@***")
    try:
        eng = create_engine(target_url, future=True)
        with eng.connect() as conn:
            r = conn.execute(text("SELECT version()")).scalar()
        print(f"✅ 연결 성공")
        print(f"   PG version: {r}")
        return 0
    except Exception as e:
        print(f"❌ 연결 실패: {e}", file=sys.stderr)
        return 1


def import_models() -> None:
    """프로젝트의 모든 SQLAlchemy 모델 import → Base.metadata 채움.

    app.py 에서 import 하는 6개 + 그 외 4개 (sources/sourcing_v2/multitenancy/audit)
    까지 모두 등록해야 마이그레이션 시 전체 테이블 생성 가능.
    """
    # app.py 기본 6개
    import lemouton.sourcing.models  # noqa
    import lemouton.sourcing.models_pricing  # noqa
    import lemouton.pricing.settings  # noqa
    import lemouton.uploader.models  # noqa
    import lemouton.templates.models  # noqa
    import lemouton.inventory.models  # noqa
    # 추가 — 실제 SQLite 에 존재하는 테이블들의 모델
    try:
        import lemouton.sources.models  # noqa  — bundle_*, source_* 테이블
    except Exception as e:
        print(f"  [WARN] lemouton.sources.models import: {e}", file=sys.stderr)
    try:
        import lemouton.sourcing.models_v2  # noqa
    except Exception as e:
        print(f"  [WARN] lemouton.sourcing.models_v2 import: {e}", file=sys.stderr)
    try:
        import lemouton.multitenancy.models  # noqa
    except Exception as e:
        print(f"  [WARN] lemouton.multitenancy.models import: {e}", file=sys.stderr)
    try:
        import lemouton.audit.models  # noqa  — audit_log
    except Exception as e:
        print(f"  [WARN] lemouton.audit.models import: {e}", file=sys.stderr)


def cmd_dry_run(target_url: str) -> int:
    """실제 적용 없이: 연결·스키마 생성 시뮬레이션·source 인벤토리만."""
    from sqlalchemy import create_engine, MetaData, text

    banner("Dry-run — 검증만")

    # 1. Source 인벤토리
    src_url = f"sqlite:///{OLD_DB.as_posix()}"
    src_engine = create_engine(src_url, future=True)
    src_meta = MetaData()
    src_meta.reflect(bind=src_engine)

    src_tables = sorted(src_meta.tables.keys())
    src_tables_useful = [t for t in src_tables if t not in SKIP_TABLES]
    print(f"\n📥 Source SQLite ({OLD_DB.name})")
    print(f"   테이블 수: {len(src_tables_useful)} (스킵: {len(src_tables) - len(src_tables_useful)})")

    total = 0
    with src_engine.connect() as conn:
        for t in src_tables_useful:
            n = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0
            total += n
            if n > 0:
                print(f"     {t:40s} {n:>6d} rows")
    print(f"   ─── 총 {total} rows ───")

    # 2. Target 스키마 생성 시뮬레이션
    print(f"\n📤 Target Supabase 시뮬레이션")
    import_models()
    from shared.db import Base

    target_tables = sorted(Base.metadata.tables.keys())
    print(f"   모델 정의 테이블 수: {len(target_tables)}")

    # 3. 매칭 검사
    src_set = set(src_tables_useful)
    tgt_set = set(target_tables)
    only_src = src_set - tgt_set
    only_tgt = tgt_set - src_set
    common = src_set & tgt_set

    print(f"\n🔍 매칭 분석")
    print(f"   공통 ({len(common)}개): 마이그레이션 대상")
    if only_src:
        print(f"   Source 에만 ({len(only_src)}개): {sorted(only_src)[:5]}{'...' if len(only_src) > 5 else ''}")
        print(f"   → 모델에 정의 없음. 스킵됨.")
    if only_tgt:
        print(f"   Target 에만 ({len(only_tgt)}개): {sorted(only_tgt)[:5]}{'...' if len(only_tgt) > 5 else ''}")
        print(f"   → 신규 모델만 있음 (빈 채로 생성됨)")

    print(f"\n💡 실행하려면 --dry-run 빼고 다시 실행")
    return 0


def cmd_migrate(target_url: str) -> int:
    """실제 마이그레이션 실행."""
    from sqlalchemy import create_engine, MetaData, text

    banner("SQLite → Supabase 마이그레이션 실행")

    # ─── 1. 연결 ───
    src_url = f"sqlite:///{OLD_DB.as_posix()}"
    src_engine = create_engine(src_url, future=True)
    dst_engine = create_engine(target_url, future=True)

    # ─── 2. 신규 시스템의 init_db 로 Target 스키마 생성 ───
    # init_db 는 config.Config.DB_URL 을 보고 engine 생성하므로 환경변수 OK
    print("\n[1/5] Target 스키마 생성 (init_db)")
    import_models()
    from shared.db import Base, init_db
    init_db()  # create_all + ALTER TABLE 멱등
    print("     ✅ Target 스키마 생성 완료")

    # ─── 3. Source 인벤토리 ───
    print("\n[2/5] Source 테이블 reflect")
    src_meta = MetaData()
    src_meta.reflect(bind=src_engine)
    print(f"     ✅ {len(src_meta.tables)} 테이블 reflect 완료")

    # ─── 4. Target 의 모든 테이블 TRUNCATE (재실행 가능하게) ───
    print("\n[3/5] Target 테이블 TRUNCATE (재실행 가능)")
    tgt_meta = MetaData()
    tgt_meta.reflect(bind=dst_engine)
    with dst_engine.begin() as conn:
        # FK 무시하고 통째로 TRUNCATE (CASCADE)
        for t in tgt_meta.sorted_tables[::-1]:  # 역순 (자식 먼저)
            try:
                conn.execute(text(f'TRUNCATE TABLE "{t.name}" CASCADE'))
            except Exception as e:
                print(f"     [WARN] TRUNCATE {t.name}: {e}")
    print(f"     ✅ {len(tgt_meta.tables)} 테이블 TRUNCATE 완료")

    # ─── 5. Source → Target 데이터 복사 ───
    print("\n[4/5] 데이터 복사 (source → target)")
    counts = {"copied": 0, "skipped": 0, "errors": 0}
    table_counts: list[tuple[str, int]] = []

    # FK 의존 순서 — Target metadata.sorted_tables 사용 (부모 먼저)
    for t in tgt_meta.sorted_tables:
        tname = t.name
        if tname in SKIP_TABLES:
            counts["skipped"] += 1
            continue
        if tname not in src_meta.tables:
            counts["skipped"] += 1
            continue

        src_t = src_meta.tables[tname]
        try:
            with src_engine.connect() as src_conn:
                rows = src_conn.execute(src_t.select()).mappings().fetchall()

            if not rows:
                table_counts.append((tname, 0))
                continue

            # Target 컬럼만 추려서 INSERT (혹시 source 가 더 많은 컬럼 있을 경우 대비)
            tgt_cols = {c.name for c in t.columns}
            cleaned = [{k: v for k, v in r.items() if k in tgt_cols} for r in rows]

            # 1차: bulk insert 시도
            try:
                with dst_engine.begin() as dst_conn:
                    dst_conn.execute(t.insert(), cleaned)
                counts["copied"] += len(rows)
                table_counts.append((tname, len(rows)))
            except Exception as bulk_err:
                # FK 위반 등 → row-by-row 재시도 (실패 row 만 스킵)
                msg = str(bulk_err)[:80]
                print(f"     [WARN] {tname}: bulk insert 실패 ({msg}...), row-by-row 폴백")
                copied_n = 0
                skipped_n = 0
                for row in cleaned:
                    try:
                        with dst_engine.begin() as dst_conn:
                            dst_conn.execute(t.insert(), [row])
                        copied_n += 1
                    except Exception as row_err:
                        skipped_n += 1
                        # 깨진 row 만 콘솔에 출력
                        key_col = list(t.primary_key.columns)[0].name if list(t.primary_key.columns) else "?"
                        key_val = row.get(key_col, "?")
                        re_msg = str(row_err)[:60]
                        print(f"        [SKIP] {tname} {key_col}={key_val!r}: {re_msg}")
                counts["copied"] += copied_n
                counts["errors"] += skipped_n
                table_counts.append((tname, copied_n))
                if skipped_n:
                    print(f"     {tname}: {copied_n} 복사, {skipped_n} 스킵 (고아 데이터)")
        except Exception as e:
            counts["errors"] += 1
            print(f"     [ERROR] {tname}: {e}")

    # ─── 6. PostgreSQL sequence 재설정 ───
    print("\n[5/5] PostgreSQL sequence 동기화")
    seq_updated = 0
    with dst_engine.begin() as conn:
        # 각 테이블의 SERIAL 컬럼에 대해 sequence 재설정
        seqs = conn.execute(text("""
            SELECT
              pg_get_serial_sequence(c.table_schema || '.' || c.table_name, c.column_name) AS seq,
              c.table_name, c.column_name
            FROM information_schema.columns c
            WHERE c.table_schema = 'public'
              AND c.column_default LIKE 'nextval%'
        """)).fetchall()
        for seq, table, col in seqs:
            if not seq:
                continue
            try:
                max_id = conn.execute(text(f'SELECT COALESCE(MAX("{col}"), 0) FROM "{table}"')).scalar() or 0
                conn.execute(text(f"SELECT setval('{seq}', :v, true)"), {"v": max(max_id, 1)})
                seq_updated += 1
            except Exception as e:
                print(f"     [WARN] sequence {seq}: {e}")
    print(f"     ✅ {seq_updated} sequence 재설정 완료")

    # ─── 7. 결과 출력 ───
    banner("마이그레이션 결과")
    print(f"  복사 row: {counts['copied']}")
    print(f"  스킵 테이블: {counts['skipped']}")
    print(f"  에러: {counts['errors']}")
    print(f"\n  주요 테이블 row 수:")
    for tname, n in sorted(table_counts, key=lambda x: -x[1])[:15]:
        if n > 0:
            print(f"     {tname:40s} {n:>6d} rows")

    return 0 if counts["errors"] == 0 else 3


def cmd_verify(target_url: str) -> int:
    """Source 와 Target row-count 비교."""
    from sqlalchemy import create_engine, MetaData, text

    banner("row-count 검증 (Source vs Target)")

    src_url = f"sqlite:///{OLD_DB.as_posix()}"
    src_engine = create_engine(src_url, future=True)
    dst_engine = create_engine(target_url, future=True)

    src_meta = MetaData()
    src_meta.reflect(bind=src_engine)
    tgt_meta = MetaData()
    tgt_meta.reflect(bind=dst_engine)

    common = set(src_meta.tables) & set(tgt_meta.tables) - SKIP_TABLES

    mismatch = 0
    with src_engine.connect() as sc, dst_engine.connect() as dc:
        for tname in sorted(common):
            s = sc.execute(text(f'SELECT COUNT(*) FROM "{tname}"')).scalar() or 0
            t = dc.execute(text(f'SELECT COUNT(*) FROM "{tname}"')).scalar() or 0
            status = "✅" if s == t else "❌"
            if s != t:
                mismatch += 1
            if s > 0 or t > 0 or s != t:
                print(f"  {status} {tname:40s} source={s:>6d}  target={t:>6d}")

    print(f"\n총 {len(common)} 공통 테이블 중 불일치: {mismatch}")
    return 0 if mismatch == 0 else 4


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite → Supabase 마이그레이션")
    parser.add_argument("--ping", action="store_true", help="Supabase 연결만 테스트")
    parser.add_argument("--dry-run", action="store_true", help="검증만, 실제 적용 X")
    parser.add_argument("--verify", action="store_true", help="row-count 검증만")
    args = parser.parse_args()

    target_url = get_target_url()

    if not OLD_DB.exists():
        print(f"❌ Source SQLite 없음: {OLD_DB}", file=sys.stderr)
        return 1

    # dry-run 은 URL 없이도 source 인벤토리만으로 가능
    if args.dry_run:
        return cmd_dry_run(target_url or "")

    if not target_url:
        print("❌ DATABASE_URL 환경변수 없음.", file=sys.stderr)
        print(f"   .env 파일: {NEW_SYSTEM / '.env'}", file=sys.stderr)
        print(f"   DATABASE_URL=postgresql://... 줄 활성화 필요", file=sys.stderr)
        return 1

    if args.ping:
        return cmd_ping(target_url)
    if args.verify:
        return cmd_verify(target_url)

    # 기본: 전체 마이그레이션
    rc = cmd_migrate(target_url)
    if rc == 0:
        print("\n검증 실행 중...")
        return cmd_verify(target_url)
    return rc


if __name__ == "__main__":
    sys.exit(main())
