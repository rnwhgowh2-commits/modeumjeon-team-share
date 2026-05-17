"""각 사이트 SourceProduct 별 compute_breakdown 호출 → 무신사 형식 단계별 표현.

DB 의 last_price 를 그대로 사용 (스크롤링 갱신값 반영).
"""
import sys, io, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from shared.db import SessionLocal
from webapp.routes.api_benefits import compute_breakdown

# (site_label, sku, source_id, sp_id, label_text)
TARGETS = [
    ('lemouton',     '르무통 클래식-그레이-230', 1, 1,  '① 르무통 공홈 (product_no=219)'),
    ('ss_lemouton',  '르무통 클래식-그레이-235', 2, 8,  '② 스스 르무통 (9496367527)'),
    ('ssf',          '르무통 클래식-그레이-235', 4, 3,  '④ SSF LEMOUTON (르무통 클래식2)'),
    ('ssf',          '르무통 클래식-그레이-230', 4, 9,  '④ SSF BEANPOLE (티셔츠 / gift_point 5,600)'),
    ('lotteimall',   '르무통 클래식-그레이-235', 6, 7,  '⑤ 롯데홈쇼핑 (2559417201)'),
    ('lotteon',      '르무통 클래식-그레이-230', 5, 12, '⑤ 롯데온 PD52903977 (롯데오너스 1% / 스토어찜)'),
    ('ssg',          '르무통 클래식-그레이-230', 7, 10, '⑦ SSG 1000631699134 (벨트)'),
]

def fmt(amt): return f"{int(amt):>9,}원"

def render(label, result):
    print('━' * 78)
    print(f'  {label}')
    print('━' * 78)
    sp = result['sale_price']
    print(f'  판매가 (베이스)  : {fmt(sp)}')
    print('  ────────────────────────────────────────')
    n = 0
    for it in result['items_used']:
        n += 1
        nm = it['name']
        en = it['enabled']
        typ = it['type']
        val = it['value']
        if en:
            step = next((s for s in result['steps'] if s['name'] == nm), None)
            if step:
                if typ == 'rate':
                    val_txt = f"{val*100:g}%"
                else:
                    val_txt = '정액'
                print(f'  {n:>2}. ✅ [{("정액" if typ=="amount" else "%")}] {nm:<48} {val_txt:>8}  '
                      f'-{int(step["deduct"]):>7,}원  →  {fmt(step["base_after"])}')
        else:
            reason = ' (카드 미반영)' if it.get('disabled_by_card_off') else ' (조건/표시만)'
            if typ == 'rate':
                val_txt = f"{val*100:g}%"
            else:
                val_txt = f"-{int(val):,}원" if val else '정액'
            print(f'  {n:>2}. ❌ [{("정액" if typ=="amount" else "%")}] {nm:<48} {val_txt:>8}{reason}')
    print('  ────────────────────────────────────────')
    print(f'  💰 매입가         : {fmt(result["final_price"])}')
    print()

def get_db_price(con, sp_id):
    cur = con.cursor()
    cur.execute('SELECT last_price FROM source_products WHERE id=?', (sp_id,))
    row = cur.fetchone()
    return int(row[0]) if row and row[0] else None

def main():
    con = sqlite3.connect('data/lemouton.db')
    s = SessionLocal()
    try:
        for site, sku, src, sp_id, label in TARGETS:
            sale = get_db_price(con, sp_id)
            if not sale:
                print(f'  ❌ {label} — DB last_price 없음 (sp_id={sp_id})\n')
                continue
            try:
                result = compute_breakdown(s, sku=sku, source_id=src, sale_price=sale)
                render(label, result)
            except Exception as e:
                print(f'  ❌ {label} ERROR: {e}\n')
    finally:
        s.close()
        con.close()

if __name__ == '__main__':
    main()
