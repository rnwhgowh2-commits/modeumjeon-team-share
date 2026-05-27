"""박스히어로 엑셀 → DB 재고 동기화 (위치별).

박스히어로 행:
- 수량(기본 위치) → 우리 '기본 위치' location
- 수량(그로스)   → 우리 '그로스' location
- 수량(판매불가)  → 무시 (우리에 없음)

기존 source='import' 트랜잭션 모두 삭제 후 새로 등록 (멱등).
"""
import sys
from datetime import datetime
from pathlib import Path
import openpyxl
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BX_PATH = Path(r'C:\Users\seung\Downloads\Items_Export_99LAB_2026-05-27T22-48-42.xlsx')


def main():
    bx_wb = openpyxl.load_workbook(BX_PATH, data_only=True)
    bx_ws = bx_wb['BoxHero']
    bx_hdr = [c.value for c in bx_ws[1]]
    bx_rows = [dict(zip(bx_hdr, r)) for r in bx_ws.iter_rows(min_row=2, values_only=True)]
    print(f'박스히어로 행: {len(bx_rows)}')

    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        # 위치 ID 매핑
        locs = s.execute(text(
            "SELECT id, name FROM inventory_locations WHERE deleted_at IS NULL"
        )).fetchall()
        loc_id_by_name = {r[1]: r[0] for r in locs}
        print(f'위치: {dict(loc_id_by_name)}')
        main_loc = loc_id_by_name.get('기본 위치')
        gros_loc = loc_id_by_name.get('그로스')
        if not main_loc:
            print('❌ "기본 위치" location 없음')
            return
        if not gros_loc:
            print('⚠️  "그로스" location 없음 — 기본 위치로 합산')

        # 박스히어로 SKU → 우리 옵션 canonical_sku
        bx_skus = [r['SKU'] for r in bx_rows if r.get('SKU')]
        opt_map = {}
        for r in s.execute(text(
            "SELECT boxhero_sku, canonical_sku FROM options WHERE boxhero_sku = ANY(:s)"
        ), {'s': bx_skus}).fetchall():
            opt_map[r[0]] = r[1]
        print(f'박스히어로 SKU ↔ 옵션 매칭: {len(opt_map)}')

        # 기존 import 트랜잭션 삭제 (멱등)
        deleted = s.execute(text("""
            DELETE FROM inventory_txs WHERE source = 'import'
        """))
        print(f'기존 import 트랜잭션 삭제: {deleted.rowcount}건')

        # 새 트랜잭션 등록
        ts = datetime.now()
        inserted = 0
        skipped = []
        for bx in bx_rows:
            sku = bx.get('SKU')
            if not sku:
                continue
            csku = opt_map.get(sku)
            if not csku:
                skipped.append(sku)
                continue
            qty_main = int(bx.get('수량(기본 위치)') or 0)
            qty_gros = int(bx.get('수량(그로스)') or 0)
            price = int(bx.get('구매가') or 0)

            if qty_main > 0:
                s.execute(text("""
                    INSERT INTO inventory_txs (option_canonical_sku, location_id, qty, tx_type, source, unit_purchase_price_at_tx, created_at, status)
                    VALUES (:csku, :loc, :qty, 'in', 'import', :price, :ts, 'completed')
                """), {'csku': csku, 'loc': main_loc, 'qty': qty_main, 'price': price, 'ts': ts})
                inserted += 1
            if qty_gros > 0:
                target_loc = gros_loc or main_loc
                s.execute(text("""
                    INSERT INTO inventory_txs (option_canonical_sku, location_id, qty, tx_type, source, unit_purchase_price_at_tx, created_at, status)
                    VALUES (:csku, :loc, :qty, 'in', 'import', :price, :ts, 'completed')
                """), {'csku': csku, 'loc': target_loc, 'qty': qty_gros, 'price': price, 'ts': ts})
                inserted += 1

            # snapshot 컬럼도 갱신
            s.execute(text("""
                UPDATE options SET boxhero_stock_total = :total,
                                   boxhero_avg_purchase_price = :price,
                                   boxhero_avg_updated_at = :ts
                WHERE canonical_sku = :csku
            """), {'total': qty_main + qty_gros, 'price': price, 'ts': ts, 'csku': csku})

        s.commit()

        print(f'\\n✓ 트랜잭션 등록: {inserted}건')
        print(f'  매칭 안된 SKU: {len(skipped)} ({skipped[:3]}...)')

        # 검증
        from shared.inventory_stock import get_stock_batch
        all_skus = [r[0] for r in s.execute(text("SELECT canonical_sku FROM options")).fetchall()]
        stock = get_stock_batch(s, all_skus)
        our_total = sum(stock.values())
        bx_total = sum((r.get('수량') or 0) for r in bx_rows)
        print(f'\\n=== 검증 ===')
        print(f'박스히어로 합계: {bx_total}')
        print(f'우리 DB 합계: {our_total}')
        print(f'차이: {our_total - bx_total}')
    finally:
        s.close()


if __name__ == '__main__':
    main()
