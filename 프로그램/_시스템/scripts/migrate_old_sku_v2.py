"""옛 canonical_sku → SKU-XXX 마이그레이션 v2 (row-by-row INSERT/UPDATE/DELETE).

각 옛 옵션마다:
1. 같은 데이터로 새 row INSERT (canonical_sku = boxhero_sku)
2. FK 참조 UPDATE (옛 → 새)
3. 옛 row DELETE
"""
import sys
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        olds = s.execute(text("""
            SELECT canonical_sku, boxhero_sku FROM options
            WHERE canonical_sku NOT LIKE 'SKU-%'
              AND boxhero_sku IS NOT NULL AND boxhero_sku != ''
        """)).fetchall()
        print(f'대상: {len(olds)}건')

        fk_tables = [
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

        success = 0
        failed = []
        for old_csku, new_csku in olds:
            sp = s.begin_nested()
            try:
                # 1. 새 row INSERT (옛 row 복제 + canonical_sku 만 변경)
                row = s.execute(text(
                    'SELECT * FROM options WHERE canonical_sku = :s'
                ), {'s': old_csku}).fetchone()
                if not row:
                    sp.rollback()
                    continue
                data = dict(row._mapping)
                data['canonical_sku'] = new_csku
                cols = ', '.join(data.keys())
                placeholders = ', '.join(f':{k}' for k in data.keys())
                s.execute(text(
                    f'INSERT INTO options ({cols}) VALUES ({placeholders}) '
                    f'ON CONFLICT (canonical_sku) DO NOTHING'
                ), data)

                # 2. FK 참조 UPDATE (옛 → 새)
                for tbl, col in fk_tables:
                    try:
                        s.execute(text(
                            f'UPDATE {tbl} SET {col} = :new WHERE {col} = :old'
                        ), {'new': new_csku, 'old': old_csku})
                    except Exception:
                        pass

                # 3. 옛 row DELETE
                s.execute(text(
                    'DELETE FROM options WHERE canonical_sku = :s'
                ), {'s': old_csku})

                sp.commit()
                success += 1
            except Exception as e:
                sp.rollback()
                failed.append((old_csku, new_csku, str(e)[:80]))

        s.commit()
        print(f'\n✓ 성공: {success}')
        print(f'실패: {len(failed)}')
        for f in failed[:5]:
            print(f'  {f[0]} → {f[1]}: {f[2]}')

        # 검증
        remain = s.execute(text("SELECT COUNT(*) FROM options WHERE canonical_sku NOT LIKE 'SKU-%'")).scalar()
        total = s.execute(text('SELECT COUNT(*) FROM options')).scalar()
        active = s.execute(text('SELECT COUNT(*) FROM options WHERE is_active=true')).scalar()
        print(f'\n=== 검증 ===')
        print(f'옛 sku 잔여: {remain} (0 이어야 정상)')
        print(f'전체: {total} (활성 {active})')
    finally:
        s.close()


if __name__ == '__main__':
    main()
