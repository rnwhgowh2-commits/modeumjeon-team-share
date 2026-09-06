"""옛 canonical_sku (한글) → 새 SKU-XXX 마이그레이션.

순서:
1. 충돌 SKU-XXX 비활성 옵션 삭제 (FK 참조 0건 확인 후)
2. 옛 sku 192건 canonical_sku → boxhero_sku 로 변경
3. FK 참조 (option_source_url_links, inventory_txs 등) 같이 변경

DB 자체 영구 변경 — popover·자동완성 등 모든 곳에서 SKU-XXX 표시.
"""
import sys
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        # 1. 충돌 분석 — 옛 sku 의 boxhero_sku 가 다른 옵션의 canonical_sku 와 같은 경우
        conflicts = s.execute(text("""
            SELECT o1.canonical_sku AS old_csku, o1.boxhero_sku AS bs,
                   o2.canonical_sku AS conflict_csku, o2.is_active AS conflict_active
            FROM options o1
            JOIN options o2 ON o1.boxhero_sku = o2.canonical_sku
            WHERE o1.canonical_sku NOT LIKE 'SKU-%'
              AND o2.canonical_sku LIKE 'SKU-%'
        """)).fetchall()
        print(f'충돌 옵션: {len(conflicts)}')
        for c in conflicts:
            print(f'  {c[0]} → {c[1]} (이미 존재 active={c[3]})')

        # 충돌 SKU-XXX 옵션 삭제 (FK 참조 확인)
        for c in conflicts:
            csku = c[2]
            # FK 참조 확인
            for tbl, col in [
                ('option_source_url_links', 'option_canonical_sku'),
                ('option_product_links', 'product_canonical_sku'),
                ('inventory_txs', 'option_canonical_sku'),
                ('option_source_links', 'canonical_sku'),
                ('option_source_urls', 'canonical_sku'),
                ('option_price_config', 'canonical_sku'),
                ('etc_source_urls', 'canonical_sku'),
                ('option_account_registrations', 'canonical_sku'),
                ('option_benefit_overrides', 'canonical_sku'),
            ]:
                sp = s.begin_nested()
                try:
                    r = s.execute(text(f'DELETE FROM {tbl} WHERE {col} = :s'), {'s': csku})
                    sp.commit()
                    if r.rowcount > 0:
                        print(f'    FK 정리 {tbl}: {r.rowcount}건')
                except Exception:
                    sp.rollback()
            s.execute(text('DELETE FROM options WHERE canonical_sku = :s'), {'s': csku})
            print(f'    충돌 옵션 삭제: {csku}')
        s.commit()

        # 2. 옛 sku canonical_sku → SKU-XXX 변경
        olds = s.execute(text("""
            SELECT canonical_sku, boxhero_sku FROM options
            WHERE canonical_sku NOT LIKE 'SKU-%'
              AND boxhero_sku IS NOT NULL AND boxhero_sku != ''
        """)).fetchall()
        print(f'\n옛 sku 변경 대상: {len(olds)}건')

        # FK 참조 먼저 변경 (cascade 아님)
        fk_refs = [
            ('option_source_url_links', 'option_canonical_sku'),
            ('option_product_links', 'product_canonical_sku'),
            ('inventory_txs', 'option_canonical_sku'),
            ('option_source_links', 'canonical_sku'),
            ('option_source_urls', 'canonical_sku'),
            ('option_price_config', 'canonical_sku'),
            ('etc_source_urls', 'canonical_sku'),
            ('option_account_registrations', 'canonical_sku'),
            ('option_benefit_overrides', 'canonical_sku'),
        ]

        # 일괄 SQL — 트랜잭션 안에서 FK 먼저, 그 다음 PK
        # SQL: UPDATE table SET col = options.boxhero_sku FROM options WHERE table.col = options.canonical_sku AND options.canonical_sku NOT LIKE 'SKU-%'
        for tbl, col in fk_refs:
            sp = s.begin_nested()
            try:
                r = s.execute(text(f"""
                    UPDATE {tbl} t SET {col} = o.boxhero_sku
                    FROM options o
                    WHERE t.{col} = o.canonical_sku
                      AND o.canonical_sku NOT LIKE 'SKU-%'
                      AND o.boxhero_sku IS NOT NULL AND o.boxhero_sku != ''
                """))
                sp.commit()
                if r.rowcount > 0:
                    print(f'  FK 변경 {tbl}: {r.rowcount}건')
            except Exception as e:
                sp.rollback()
                print(f'  {tbl}: skip ({e.__class__.__name__})')

        # 옵션 자체 변경 (PK 변경)
        r = s.execute(text("""
            UPDATE options SET canonical_sku = boxhero_sku
            WHERE canonical_sku NOT LIKE 'SKU-%'
              AND boxhero_sku IS NOT NULL AND boxhero_sku != ''
        """))
        s.commit()
        print(f'\noptions.canonical_sku 변경: {r.rowcount}건')

        # 검증
        remaining = s.execute(text("""
            SELECT COUNT(*) FROM options WHERE canonical_sku NOT LIKE 'SKU-%'
        """)).scalar()
        print(f'\n=== 검증 ===')
        print(f'옛 sku 잔여: {remaining}건 (0 이어야 정상)')

        total = s.execute(text('SELECT COUNT(*) FROM options')).scalar()
        active = s.execute(text('SELECT COUNT(*) FROM options WHERE is_active=true')).scalar()
        print(f'전체 옵션: {total} (활성 {active})')
    finally:
        s.close()


if __name__ == '__main__':
    main()
