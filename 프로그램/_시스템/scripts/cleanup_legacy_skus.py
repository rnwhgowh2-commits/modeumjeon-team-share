"""[2026-05-27] 옛 sku 일괄 정리 — 매핑 이관 + 옛 sku 삭제.

문제:
- 같은 axis_values 의 옵션이 두 sku 형식으로 중복:
  · 옛: `르무통_메이트-블랙-220` (build_sku 결과)
  · 새: `SKU-XXXXXXX` (auto-generated)
- 매핑은 새 sku 에만 걸려있는 경우가 많아 prune 의 매핑 검사 실패 → 사용자 OFF 영구 저장 X

방식:
1. 각 모음전의 axis_values 별 그룹화 (옛 + 새 sku 쌍)
2. 새 sku 가 canonical — 옛 sku 의 모든 FK 참조를 새 sku 로 update
3. 옛 sku 삭제 (이미 비어있으니 cascade 영향 없음)
4. 새 sku 만 있는 경우는 그대로

실행:
  python scripts/cleanup_legacy_skus.py --dry-run   # 영향 범위만 보고
  python scripts/cleanup_legacy_skus.py             # 실제 실행
"""
from __future__ import annotations

import sys
import argparse
from collections import defaultdict
from pathlib import Path

# project root 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from shared.db import SessionLocal, engine


# 옛 sku 가 참조되는 테이블 + 컬럼 (FK)
FK_TABLES = [
    ("option_source_url_links", "option_canonical_sku"),
    ("option_source_links", "canonical_sku"),
    ("option_account_registrations", "canonical_sku"),
    ("etc_source_urls", "canonical_sku"),
    ("option_pricings", "canonical_sku"),
    ("option_pricing_history", "canonical_sku"),
]


def is_old_format(sku: str) -> bool:
    """옛 형식 = `{model_code}-{색}-{사이즈}` 같이 SKU- 로 시작 안 함."""
    return sku and not sku.startswith("SKU-")


def is_new_format(sku: str) -> bool:
    return sku and sku.startswith("SKU-")


def collect_dup_pairs(session):
    """모든 모음전의 (color_code, size_code) 중복 옵션 찾기.

    매칭 기준: (model_code, color_code, size_code) — 새 sku 의 axis_values_json 가
    NULL 인 경우가 많아 color/size 직접 비교가 안전.

    반환: {model_code: {(color, size): {'old': [sku, ...], 'new': [sku, ...]}}}
    """
    rows = session.execute(text("""
        SELECT model_code, canonical_sku, color_code, size_code
        FROM options
    """)).fetchall()

    bundles = defaultdict(lambda: defaultdict(lambda: {'old': [], 'new': []}))
    for r in rows:
        key = (r.color_code or '', r.size_code or '')
        kind = 'new' if is_new_format(r.canonical_sku) else 'old'
        bundles[r.model_code][key][kind].append(r.canonical_sku)
    return bundles


def count_fk_references(session, sku: str) -> dict:
    """옛 sku 가 각 FK 테이블에서 몇 번 참조되는지."""
    counts = {}
    for table, col in FK_TABLES:
        try:
            n = session.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {col} = :sku"),
                                {"sku": sku}).scalar() or 0
        except Exception as e:
            n = f'ERR ({type(e).__name__})'
        counts[table] = n
    return counts


def migrate_fk(session, old_sku: str, new_sku: str) -> dict:
    """`old_sku` 의 FK 참조를 `new_sku` 로 update. 이미 동일 매핑 있으면 old 만 삭제.

    각 테이블 별도 SAVEPOINT — 테이블 없거나 컬럼 없으면 무시.
    """
    moved = {}
    for table, col in FK_TABLES:
        sp = session.begin_nested()
        try:
            if table == "option_source_url_links":
                # UNIQUE(option_canonical_sku, bundle_source_url_id) — 중복 회피
                session.execute(text(f"""
                    DELETE FROM {table}
                    WHERE {col} = :old AND bundle_source_url_id IN (
                        SELECT bundle_source_url_id FROM {table} WHERE {col} = :new
                    )
                """), {"old": old_sku, "new": new_sku})
                result = session.execute(text(f"UPDATE {table} SET {col} = :new WHERE {col} = :old"),
                                         {"old": old_sku, "new": new_sku})
            elif table == "option_source_links":
                # 동일 (canonical_sku, source) 중복 회피
                session.execute(text(f"""
                    DELETE FROM {table}
                    WHERE {col} = :old AND source_id IN (
                        SELECT source_id FROM {table} WHERE {col} = :new
                    )
                """), {"old": old_sku, "new": new_sku})
                result = session.execute(text(f"UPDATE {table} SET {col} = :new WHERE {col} = :old"),
                                         {"old": old_sku, "new": new_sku})
            else:
                result = session.execute(text(f"UPDATE {table} SET {col} = :new WHERE {col} = :old"),
                                         {"old": old_sku, "new": new_sku})
            moved[table] = result.rowcount if hasattr(result, 'rowcount') else 0
            sp.commit()
        except Exception as e:
            sp.rollback()
            moved[table] = f'skip ({type(e).__name__})'
    return moved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="실행 안 하고 영향 범위만 보고")
    parser.add_argument("--model", help="특정 모음전만 (모음전 코드)")
    args = parser.parse_args()

    with SessionLocal() as session:
        bundles = collect_dup_pairs(session)
        total_models = len(bundles)
        total_dup_axis = 0
        total_old_skus = 0
        total_new_skus = 0
        models_to_clean = []
        for model_code, axis_map in sorted(bundles.items()):
            if args.model and model_code != args.model:
                continue
            dup_count = sum(1 for v in axis_map.values() if len(v['old']) > 0 and len(v['new']) > 0)
            old_total = sum(len(v['old']) for v in axis_map.values())
            new_total = sum(len(v['new']) for v in axis_map.values())
            total_dup_axis += dup_count
            total_old_skus += old_total
            total_new_skus += new_total
            if old_total > 0:
                models_to_clean.append((model_code, axis_map, old_total, new_total, dup_count))

        print(f"\n=== 진단 ===")
        print(f"전체 모음전: {total_models}")
        print(f"옛 sku 가진 모음전: {len(models_to_clean)}")
        print(f"axis_values 중복(옛+새 둘 다): {total_dup_axis}")
        print(f"옛 sku total: {total_old_skus}")
        print(f"새 sku total: {total_new_skus}")
        print()

        if args.dry_run:
            print(f"=== Dry-run — 처리 예정 모음전 ===")
            for model_code, axis_map, old_total, new_total, dup_count in models_to_clean[:5]:
                print(f"\n[{model_code}] 옛 {old_total} / 새 {new_total} / 중복 axis {dup_count}")
                # 샘플 옛 sku 의 FK 참조
                sample_old = None
                for av_key, v in axis_map.items():
                    if v['old'] and v['new']:
                        sample_old = (av_key, v['old'][0], v['new'][0])
                        break
                if sample_old:
                    av_key, old_sku, new_sku = sample_old
                    print(f"  샘플: {av_key}")
                    print(f"  옛 sku: {old_sku} — FK 참조 {count_fk_references(session, old_sku)}")
                    print(f"  새 sku: {new_sku} — FK 참조 {count_fk_references(session, new_sku)}")
            print(f"\n실제 실행: --dry-run 빼고 다시 실행")
            return

        # ─── 실행 ───
        # 방향: 옛 sku 가 canonical (build_sku 와 일관). 새 sku FK 이관 후 새 sku 삭제.
        print(f"=== 실행 시작 ===")
        total_migrated = 0
        total_deleted = 0
        total_kept_old_only = 0
        total_kept_new_only = 0
        for model_code, axis_map, old_total, new_total, dup_count in models_to_clean:
            for av_key, v in axis_map.items():
                if v['old'] and v['new']:
                    # 둘 다 있음 — 옛이 canonical, 새 FK 이관 + 새 삭제
                    canonical_old = v['old'][0]
                    for new_sku in v['new']:
                        migrate_fk(session, new_sku, canonical_old)
                        session.execute(text("DELETE FROM options WHERE canonical_sku = :s"),
                                        {"s": new_sku})
                        total_migrated += 1
                        total_deleted += 1
                elif v['old']:
                    total_kept_old_only += len(v['old'])
                elif v['new']:
                    # 새만 있고 옛 없음 — 새 그대로 유지 (옛 형식 만들면 외부 시스템 영향 우려)
                    total_kept_new_only += len(v['new'])
            session.commit()
            print(f"  [{model_code}] 완료")

        print(f"\n=== 결과 ===")
        print(f"새 sku → 옛 sku 이관: {total_migrated}")
        print(f"새 sku 삭제: {total_deleted}")
        print(f"옛만 있어 유지: {total_kept_old_only}")
        print(f"새만 있어 유지: {total_kept_new_only}")


if __name__ == "__main__":
    main()
