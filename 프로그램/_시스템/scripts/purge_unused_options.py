"""DB 옵션 정리 — 박스히어로 매칭 + URL 매핑 있는 옵션만 보존, 나머지 삭제.

보존 룰:
1. boxhero_sku 가 박스히어로 엑셀의 SKU 와 매칭
2. option_source_url_links 에 URL 매핑 있음 (사용자가 모음전에 등록)

삭제 대상:
- 박스히어로 SKU 없고 URL 매핑도 없는 옵션
- 주로 르무통_버디 step3 (메이트/클래식) 비활성 옵션
"""
import sys
from pathlib import Path
import openpyxl
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    bx_wb = openpyxl.load_workbook(r'C:\Users\seung\Downloads\Items_Export_99LAB_2026-05-27T22-48-42.xlsx', data_only=True)
    bx_skus = {row[0].value for row in bx_wb['BoxHero'].iter_rows(min_row=2, max_col=1) if row[0].value}
    print(f'박스히어로 SKU: {len(bx_skus)}')

    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        # 1. 살릴 옵션 식별
        keep = s.execute(text('''
            SELECT DISTINCT o.canonical_sku
            FROM options o
            WHERE o.boxhero_sku = ANY(:bx)
               OR o.canonical_sku IN (SELECT DISTINCT option_canonical_sku FROM option_source_url_links)
        '''), {'bx': list(bx_skus)}).fetchall()
        keep_skus = {r[0] for r in keep}
        print(f'살릴 옵션 (박스히어로 매칭 OR URL 매핑): {len(keep_skus)}')

        # 2. 삭제 대상
        total = s.execute(text('SELECT COUNT(*) FROM options')).scalar()
        delete = s.execute(text('''
            SELECT canonical_sku, model_code, color_code, size_code
            FROM options WHERE canonical_sku NOT IN :keep
        '''), {'keep': tuple(keep_skus)}).fetchall()
        delete_skus = [r[0] for r in delete]
        print(f'전체 옵션: {total}, 삭제 대상: {len(delete_skus)}')

        from collections import Counter
        mc_cnt = Counter(r[1] for r in delete)
        print('\n=== 삭제 대상 모델별 ===')
        for mc, c in mc_cnt.most_common():
            print(f'  {mc}: {c}건')

        # 3. FK 정리 — 의존 데이터 먼저 삭제 (각 테이블은 savepoint 로 격리)
        if delete_skus:
            for tbl, col in [
                ('inventory_txs', 'option_canonical_sku'),
                ('option_source_url_links', 'option_canonical_sku'),
                ('option_source_links', 'canonical_sku'),
                ('option_source_urls', 'canonical_sku'),
                ('option_price_config', 'canonical_sku'),
                ('etc_source_urls', 'canonical_sku'),
                ('option_account_registrations', 'canonical_sku'),
                ('option_product_links', 'product_canonical_sku'),
                ('option_benefit_overrides', 'canonical_sku'),
            ]:
                sp = s.begin_nested()
                try:
                    r = s.execute(text(f'DELETE FROM {tbl} WHERE {col} = ANY(:s)'),
                                  {'s': delete_skus})
                    sp.commit()
                    if r.rowcount > 0:
                        print(f'  {tbl} 삭제: {r.rowcount}건')
                except Exception as e:
                    sp.rollback()
                    print(f'  {tbl}: skip ({e.__class__.__name__})')

            # 4. options 자체 삭제
            r = s.execute(text('DELETE FROM options WHERE canonical_sku = ANY(:s)'),
                          {'s': delete_skus})
            print(f'\n✓ options 삭제: {r.rowcount}건')
            s.commit()

        # 검증
        new_total = s.execute(text('SELECT COUNT(*) FROM options')).scalar()
        active = s.execute(text("SELECT COUNT(*) FROM options WHERE is_active = true")).scalar()
        print(f'\n=== 검증 ===')
        print(f'DB 옵션 (정리 후): {new_total}')
        print(f'  활성: {active}')
        print(f'  비활성: {new_total - active}')
    finally:
        s.close()


if __name__ == '__main__':
    main()
