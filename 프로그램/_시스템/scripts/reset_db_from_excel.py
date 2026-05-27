"""DB 옵션 전체 클린 + 박스히어로 엑셀 재업로드.

순서:
1. 매핑 백업 (option_source_url_links)
2. 옵션 의존 데이터 전체 삭제 (inventory_txs, option_source_url_links 등)
3. options 전체 삭제
4. 박스히어로 SKU 810 + 스카이블루 8 + 아이보리 14 = 832 옵션 새로 INSERT
5. 매핑 복원
6. 박스히어로 재고 sync

모델 (models) 은 보존. 모음전 구조 (bundle_*) 도 보존.
"""
import sys
import json
import secrets
import string
from datetime import datetime
from pathlib import Path
import openpyxl
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BX_PATH = Path(r'C:\Users\seung\Downloads\Items_Export_99LAB_2026-05-27T22-48-42.xlsx')


def main():
    # 박스히어로 엑셀 읽기
    bx_wb = openpyxl.load_workbook(BX_PATH, data_only=True)
    bx_ws = bx_wb['BoxHero']
    bx_hdr = [c.value for c in bx_ws[1]]
    bx_rows = [dict(zip(bx_hdr, r)) for r in bx_ws.iter_rows(min_row=2, values_only=True)]
    bx_by_sku = {r['SKU']: r for r in bx_rows if r.get('SKU')}
    print(f'박스히어로 엑셀: {len(bx_rows)}행')

    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        # 0. 백업 dir
        backup_dir = Path(r'C:\dev\모음전 프로젝트\프로그램\_시스템\data') / f'backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        backup_dir.mkdir(parents=True, exist_ok=True)

        # 1. 매핑·옵션 백업
        print('\n=== 1. 백업 ===')
        for tbl in ['option_source_url_links', 'option_source_links', 'option_source_urls',
                    'option_price_config', 'option_benefit_overrides',
                    'option_product_links', 'options']:
            try:
                rows = s.execute(text(f'SELECT * FROM {tbl}')).fetchall()
                if rows:
                    data = [dict(r._mapping) for r in rows]
                    out = backup_dir / f'{tbl}.json'
                    out.write_text(json.dumps(data, default=str, ensure_ascii=False, indent=2),
                                   encoding='utf-8')
                    print(f'  {tbl}: {len(data)}건 → {out.name}')
            except Exception as e:
                print(f'  {tbl}: skip ({e.__class__.__name__})')

        # 매핑 백업 (canonical_sku → url_id 등)
        mappings = s.execute(text(
            'SELECT option_canonical_sku, bundle_source_url_id FROM option_source_url_links'
        )).fetchall()
        print(f'  매핑 백업: {len(mappings)}건')

        # 박스히어로엔 없지만 살릴 옵션 — 스카이블루·아이보리 색상 옵션의 (model, color, size) 보존
        keep_custom = s.execute(text('''
            SELECT canonical_sku, model_code, color_code, color_display,
                   size_code, size_display, boxhero_sku, barcode
            FROM options
            WHERE model_code = '르무통_메이트' AND color_code IN ('스카이블루', '아이보리')
        ''')).fetchall()
        print(f'  사용자 추가 색상 옵션 백업: {len(keep_custom)}건')

        # 2. 옵션 의존 데이터 + 옵션 삭제
        print('\n=== 2. DB 옵션·의존 데이터 전체 삭제 ===')
        for tbl in ['inventory_txs', 'option_source_url_links', 'option_source_links',
                    'option_source_urls', 'option_price_config', 'etc_source_urls',
                    'option_account_registrations', 'option_product_links',
                    'option_benefit_overrides']:
            sp = s.begin_nested()
            try:
                r = s.execute(text(f'DELETE FROM {tbl}'))
                sp.commit()
                print(f'  {tbl}: {r.rowcount}건 삭제')
            except Exception as e:
                sp.rollback()
                print(f'  {tbl}: skip ({e.__class__.__name__})')

        # options 삭제
        r = s.execute(text('DELETE FROM options'))
        print(f'  options: {r.rowcount}건 삭제')
        s.commit()

        # 3. 새 옵션 INSERT — 박스히어로 SKU 별로
        print('\n=== 3. 박스히어로 옵션 INSERT ===')

        # 모델 매칭 헬퍼
        def model_for_bx(bx):
            brand = bx.get('브랜드')
            model_name = bx.get('모델명')
            if not brand or not model_name:
                # 메타 누락 — 단독_SKU-XXX 모델로
                return f'단독_{bx["SKU"]}'
            # 우리 규칙: 브랜드_모델명 (공백 → _)
            return f"{brand}_{str(model_name).replace(' ', '_')}"

        # 모델 사전 확인 — 없는 모델은 새로 생성
        existing_models = set(r[0] for r in s.execute(text('SELECT model_code FROM models')).fetchall())

        def ensure_model(mc, brand, category, model_name_raw):
            if mc in existing_models:
                return
            # 기존 모델 row 복제 후 model_code 만 변경 (NOT NULL 컬럼 안전)
            template = s.execute(text(
                'SELECT * FROM models WHERE brand IS NOT NULL LIMIT 1'
            )).fetchone()
            if not template:
                return
            data = dict(template._mapping)
            data['model_code'] = mc
            data['brand'] = brand or ''
            data['category'] = category or ''
            data['model_name_display'] = model_name_raw or mc
            data['model_name_raw'] = model_name_raw or mc
            data['article_no'] = '-'
            data['created_at'] = datetime.now()
            data['updated_at'] = datetime.now()
            cols = ', '.join(data.keys())
            placeholders = ', '.join(f':{k}' for k in data.keys())
            s.execute(text(f'INSERT INTO models ({cols}) VALUES ({placeholders}) ON CONFLICT (model_code) DO NOTHING'), data)
            existing_models.add(mc)

        # 박스히어로 SKU 별 옵션 생성 (canonical_sku = boxhero_sku)
        inserted = 0
        for bx in bx_rows:
            sku = bx.get('SKU')
            if not sku:
                continue
            brand = bx.get('브랜드') or ''
            cat = bx.get('카테고리') or ''
            mname = str(bx.get('모델명') or '')
            mc = model_for_bx(bx)
            # 색상: 박스히어로 제품명 - 브랜드 - 모델명 (마지막 토큰)
            pn = (bx.get('제품명') or '').strip()
            color = pn
            if brand and brand in color:
                color = color.replace(brand, '', 1).strip()
            if mname and mname in color:
                color = color.replace(mname, '', 1).strip()
            color = color.strip(' -:/').strip() or '-'
            size = str(bx.get('사이즈')) if bx.get('사이즈') is not None else '-'

            ensure_model(mc, brand, cat, f'{brand} {mname}'.strip())

            s.execute(text('''
                INSERT INTO options (canonical_sku, model_code, color_code, color_display,
                                     size_code, size_display, boxhero_sku, barcode,
                                     axis_values_json, is_active,
                                     use_purchase_inventory, purchase_priority, lemouton_only)
                VALUES (:cs, :mc, :c, :c, :sz, :sz, :bs, :bc, :av, true,
                        false, 'auto', false)
                ON CONFLICT (canonical_sku) DO NOTHING
            '''), {
                'cs': sku, 'mc': mc, 'c': color, 'sz': size,
                'bs': sku, 'bc': str(bx.get('바코드') or ''),
                'av': json.dumps([color, size], ensure_ascii=False),
            })
            inserted += 1
        print(f'  박스히어로 옵션 INSERT: {inserted}건')

        # 4. 스카이블루·아이보리 옵션 INSERT (커스텀)
        print('\n=== 4. 사용자 추가 색상 (스카이블루·아이보리) INSERT ===')
        sky_iv_inserted = 0
        existing_skus = set(r[0] for r in s.execute(text('SELECT boxhero_sku FROM options WHERE boxhero_sku IS NOT NULL')).fetchall())

        def gen_sku():
            while True:
                sku = 'SKU-' + ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
                if sku not in existing_skus:
                    existing_skus.add(sku)
                    return sku

        for kc in keep_custom:
            csku, mc, color, color_disp, size, size_disp, old_bs, old_bc = kc
            new_sku = old_bs if old_bs and old_bs.startswith('SKU-') else gen_sku()
            color_v = color_disp or color or ''
            size_v = size_disp or size or ''
            s.execute(text('''
                INSERT INTO options (canonical_sku, model_code, color_code, color_display,
                                     size_code, size_display, boxhero_sku, barcode,
                                     axis_values_json, is_active,
                                     use_purchase_inventory, purchase_priority, lemouton_only)
                VALUES (:cs, :mc, :c, :c, :sz, :sz, :bs, :bc, :av, true,
                        false, 'auto', false)
                ON CONFLICT (canonical_sku) DO NOTHING
            '''), {
                'cs': new_sku, 'mc': mc, 'c': color_v, 'sz': size_v,
                'bs': new_sku, 'bc': old_bc or '',
                'av': json.dumps([color_v, size_v], ensure_ascii=False),
            })
            sky_iv_inserted += 1
        print(f'  스카이블루·아이보리 INSERT: {sky_iv_inserted}건')

        s.commit()

        # 5. 박스히어로 재고 sync
        print('\n=== 5. 박스히어로 재고 sync ===')
        locs = s.execute(text(
            "SELECT id, name FROM inventory_locations WHERE deleted_at IS NULL"
        )).fetchall()
        loc_id_by_name = {r[1]: r[0] for r in locs}
        main_loc = loc_id_by_name.get('기본 위치')
        gros_loc = loc_id_by_name.get('그로스')
        ts = datetime.now()
        tx_inserted = 0
        for bx in bx_rows:
            sku = bx.get('SKU')
            if not sku:
                continue
            qty_main = int(bx.get('수량(기본 위치)') or 0)
            qty_gros = int(bx.get('수량(그로스)') or 0)
            price = int(bx.get('구매가') or 0)
            if qty_main > 0:
                s.execute(text("""
                    INSERT INTO inventory_txs (option_canonical_sku, location_id, qty, tx_type, source, unit_purchase_price_at_tx, created_at, status)
                    VALUES (:cs, :loc, :qty, 'in', 'import', :price, :ts, 'completed')
                """), {'cs': sku, 'loc': main_loc, 'qty': qty_main, 'price': price, 'ts': ts})
                tx_inserted += 1
            if qty_gros > 0 and gros_loc:
                s.execute(text("""
                    INSERT INTO inventory_txs (option_canonical_sku, location_id, qty, tx_type, source, unit_purchase_price_at_tx, created_at, status)
                    VALUES (:cs, :loc, :qty, 'in', 'import', :price, :ts, 'completed')
                """), {'cs': sku, 'loc': gros_loc, 'qty': qty_gros, 'price': price, 'ts': ts})
                tx_inserted += 1
            s.execute(text("""
                UPDATE options SET boxhero_stock_total = :total,
                                   boxhero_avg_purchase_price = :price,
                                   boxhero_avg_updated_at = :ts
                WHERE canonical_sku = :cs
            """), {'total': qty_main + qty_gros, 'price': price, 'ts': ts, 'cs': sku})
        s.commit()
        print(f'  inventory_txs INSERT: {tx_inserted}건')

        # 6. 매핑 복원 — 같은 canonical_sku 매핑이 있으면 복원
        print('\n=== 6. URL 매핑 복원 ===')
        restored = 0
        skipped = 0
        for csku, url_id in mappings:
            # 그 canonical_sku 가 새 옵션 중에 있는지
            exists = s.execute(text('SELECT 1 FROM options WHERE canonical_sku = :s'),
                               {'s': csku}).fetchone()
            if not exists:
                skipped += 1
                continue
            # url_id 도 살아있는지 (bundle_source_urls 는 안 건드림)
            url_exists = s.execute(text('SELECT 1 FROM bundle_source_urls WHERE id = :i'),
                                    {'i': url_id}).fetchone()
            if not url_exists:
                skipped += 1
                continue
            s.execute(text(
                'INSERT INTO option_source_url_links (option_canonical_sku, bundle_source_url_id, created_at) '
                'VALUES (:s, :i, NOW()) ON CONFLICT DO NOTHING'
            ), {'s': csku, 'i': url_id})
            restored += 1
        s.commit()
        print(f'  매핑 복원: {restored}건 (스킵 {skipped})')

        # 검증
        print('\n=== 최종 검증 ===')
        total = s.execute(text('SELECT COUNT(*) FROM options')).scalar()
        active = s.execute(text('SELECT COUNT(*) FROM options WHERE is_active = true')).scalar()
        from shared.inventory_stock import get_stock_batch
        all_skus = [r[0] for r in s.execute(text('SELECT canonical_sku FROM options')).fetchall()]
        stock = get_stock_batch(s, all_skus)
        stock_total = sum(stock.values())
        print(f'옵션: {total} (활성 {active})')
        print(f'재고 합계: {stock_total} (목표: 722)')
    except Exception as e:
        s.rollback()
        print(f'\n❌ 에러: {e}')
        raise
    finally:
        s.close()


if __name__ == '__main__':
    main()
