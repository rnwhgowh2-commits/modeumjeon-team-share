"""color_display 일괄 정리 v3 — raw SQL 로 ORM 우회."""
import sys
from pathlib import Path
import openpyxl
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BX_PATH = Path(r'C:\Users\seung\Downloads\Items_Export_99LAB_2026-05-27T21-41-37.xlsx')


def normalize(s):
    if not s:
        return ''
    s = s.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    s = s.replace(':', '').replace('/', '').lower()
    return s


def strip_prefix(text_v, prefix):
    if not text_v or not prefix:
        return None
    raw = text_v.strip()
    if raw.startswith(prefix):
        rest = raw[len(prefix):].strip().lstrip('-:/ ').strip()
        return rest if rest else None
    norm_t = normalize(raw)
    norm_p = normalize(prefix)
    if not norm_p or not norm_t.startswith(norm_p):
        return None
    consumed = 0
    cut_idx = len(raw)
    for i, ch in enumerate(raw):
        if consumed >= len(norm_p):
            cut_idx = i
            break
        if normalize(ch):
            consumed += 1
    rest = raw[cut_idx:].strip().lstrip('-:/ ').strip()
    return rest if rest else None


def extract_color(raw_color, mnd, mnr, brand, bx_product):
    candidates = []
    for mn in [mnd, mnr]:
        if mn:
            r = strip_prefix(raw_color, mn)
            if r:
                candidates.append(r)
    if brand and mnd:
        bm = f'{brand} {mnd}'
        r = strip_prefix(raw_color, bm)
        if r:
            candidates.append(r)
    if bx_product:
        s = bx_product.strip()
        if s.startswith('(W)'):
            s = s[3:].strip()
        if brand:
            r = strip_prefix(s, brand)
            if r:
                s = r
        for mn in [mnd, mnr]:
            if mn:
                r = strip_prefix(s, mn)
                if r:
                    s = r
                    break
        s = s.strip(' -:/').strip()
        if s and s != raw_color:
            candidates.append(s)
    valid = [c for c in candidates if c and len(c.strip()) >= 2]
    if not valid:
        return raw_color
    valid.sort(key=lambda x: (len(x), x))
    return valid[0]


def main():
    bx_wb = openpyxl.load_workbook(BX_PATH, data_only=True)
    bx_ws = bx_wb['BoxHero']
    bx_hdr = [c.value for c in bx_ws[1]]
    bx_rows = [dict(zip(bx_hdr, r)) for r in bx_ws.iter_rows(min_row=2, values_only=True)]
    bx_by_sku = {r['SKU']: r for r in bx_rows if r.get('SKU')}

    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        rows = s.execute(text('''
            SELECT o.canonical_sku, o.color_code, o.color_display, o.boxhero_sku,
                   m.brand, m.model_name_display, m.model_name_raw
            FROM options o
            LEFT JOIN models m ON m.model_code = o.model_code
        ''')).fetchall()
        print(f'대상 옵션: {len(rows)}')

        updates = []
        for r in rows:
            csku, color_code, color_display, bs, brand, mnd, mnr = r
            mnd = (mnd or '').strip()
            mnr = (mnr or '').strip()
            brand = (brand or '').strip()
            raw_color = (color_display or color_code or '').strip()
            if not raw_color:
                continue
            bx_product = ''
            if bs:
                bx = bx_by_sku.get(bs)
                if bx:
                    bx_product = (bx.get('제품명') or '').strip()
            new_color = extract_color(raw_color, mnd, mnr, brand, bx_product)
            if new_color != raw_color and new_color:
                updates.append((csku, raw_color, new_color))

        print(f'정리 대상: {len(updates)}건')
        # 적용
        for csku, _, new in updates:
            s.execute(text('UPDATE options SET color_display = :c WHERE canonical_sku = :s'),
                      {'c': new[:64], 's': csku})
        s.commit()
        print(f'✓ DB 적용 완료: {len(updates)}건')

        print()
        print('=== 샘플 (50건) ===')
        for sku, before, after in updates[:50]:
            print(f'  {sku}: "{before}" → "{after}"')

        # 모델별 카운트
        from collections import Counter
        # 다시 model_code 조회
        sku_to_mc = {}
        if updates:
            update_skus = [u[0] for u in updates]
            mc_rows = s.execute(text('SELECT canonical_sku, model_code FROM options WHERE canonical_sku = ANY(:s)'),
                                 {'s': update_skus}).fetchall()
            for cs, mc in mc_rows:
                sku_to_mc[cs] = mc
        cnt = Counter(sku_to_mc.get(u[0], '?') for u in updates)
        print()
        print('=== 모델별 변경 카운트 ===')
        for mc, c in cnt.most_common(20):
            print(f'  {mc}: {c}건')
    finally:
        s.close()


if __name__ == '__main__':
    main()
