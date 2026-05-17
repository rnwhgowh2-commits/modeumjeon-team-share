"""크롤링 시연 v2 — SSF 매핑 정정 후 + 무신사는 storage_state(영빈) 직접 사용."""
import sys, io, time, urllib.parse, urllib.request, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SKU = '르무통 클래식-그레이-230'
BASE = 'http://localhost:5052'

# 무신사는 storage_state(영빈) 직접 호출 (API 우회)
def musinsa_logged_in():
    from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler
    import sqlite3
    con = sqlite3.connect('data/lemouton.db')
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        'SELECT product_url FROM option_source_urls WHERE canonical_sku=? AND source_id=3',
        (SKU,))
    row = cur.fetchone()
    url = row['product_url'] if row else None
    con.close()
    if not url:
        return None
    t0 = time.time()
    crawler = MusinsaPlaywrightCrawler(account_name='영빈', headless=True)
    cr = crawler.fetch(url)
    dt = time.time() - t0
    sale_price = cr.options[0].get('sale_price') if cr.options else None
    # DB last_price 만 직접 UPDATE (FK ORM 이슈 우회)
    con = sqlite3.connect('data/lemouton.db')
    c = con.cursor()
    c.execute('UPDATE source_products SET last_price=? WHERE url=?', (sale_price, url))
    c.execute('UPDATE option_source_urls SET price_cached=? WHERE product_url=? AND source_id=3', (sale_price, url))
    con.commit()
    con.close()
    return {'sale_price': sale_price, 'dt': dt, 'opt_count': len(cr.options)}

def http_post(url, timeout=120):
    req = urllib.request.Request(url, method='POST', headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return 0, {'error': str(e)}

sku_enc = urllib.parse.quote(SKU)

print('=' * 96)
print(f'  📦 크롤링 시연 v2 — {SKU}')
print(f'      SSF 매핑 정정 (BEANPOLE → LEMOUTON) + 무신사 storage_state(영빈) 직접 사용')
print('=' * 96)

# SSF (src=4) — 정정된 URL 로 재크롤
print()
print('  ⏳ [4/SSF — 정정 후] ...', end='', flush=True)
t0 = time.time()
status, body = http_post(f'{BASE}/api/options/{sku_enc}/sources/4/refetch', timeout=120)
dt = time.time() - t0
ssf_price = body.get('sale_price') or body.get('crawled_price') or body.get('data', {}).get('sale_price')
print(f'  ✅ {dt:.1f}s  sale_price={ssf_price}')

# 무신사 (src=3) — storage_state(영빈) 직접 호출
print('  ⏳ [3/무신사 — 영빈 로그인] ...', end='', flush=True)
try:
    mu = musinsa_logged_in()
    print(f'  ✅ {mu["dt"]:.1f}s  sale_price={mu["sale_price"]} (옵션 {mu["opt_count"]}개)')
    mus_price = mu['sale_price']
except Exception as e:
    import traceback; traceback.print_exc()
    print(f'  ❌ {e}')
    mus_price = None

# breakdown 계산
print()
print('=' * 96)
print('  💰 매입가 (compute_breakdown)')
print('=' * 96)
items = []
if ssf_price: items.append({'sku': SKU, 'source_id': 4, 'sale_price': ssf_price})
if mus_price: items.append({'sku': SKU, 'source_id': 3, 'sale_price': mus_price})

if items:
    payload = json.dumps({'items': items}).encode('utf-8')
    req = urllib.request.Request(f'{BASE}/api/source-benefits/breakdowns', data=payload, method='POST',
                                  headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        bd = json.loads(resp.read().decode('utf-8')).get('results', {})
    for it in items:
        key = f'{it["sku"]}|{it["source_id"]}'
        r = bd.get(key, {})
        buy = r.get('final_price')
        label = {3:'무신사 (영빈 로그인)', 4:'SSF (정정 후 LEMOUTON)'}.get(it['source_id'])
        if buy is not None:
            save = it['sale_price'] - buy
            pct = save / it['sale_price'] * 100
            print(f'  [{it["source_id"]}] {label:30}  sale={it["sale_price"]:>8,}원  →  buy={buy:>8,}원  (-{save:>5,}원, {pct:.1f}%↓)')
            for st in r.get('steps', [])[:6]:
                print(f'         · {st.get("name","")[:40]:42}  -{int(st.get("deduct",0)):,}원  → {int(st.get("base_after",0)):,}원')
