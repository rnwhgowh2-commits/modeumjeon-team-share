# -*- coding: utf-8 -*-
"""등록 URL 9개 크롤 정확도 정밀 진단 (단일 psycopg2 커넥션, raw SQL).
그레이220 기준 — SourceProduct(상품단위) vs SourceOption(색+사이즈) 가격/재고 분리.
매트릭스가 실제 쓰는 값 재현 (_match_option_stock + crawled_price=sp.last_price)."""
import sys, io, os, re, json, psycopg2
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from dotenv import load_dotenv
load_dotenv()
from lemouton.sources.service import normalize_url as _norm

# ── api_pricing.py 순수 헬퍼 인라인 (DB 풀 회피) ──
_STOCK_CAP = 10
def _stk_digits(x): return ''.join(c for c in str(x or '') if c.isdigit())
def _stk_cnorm(x): return re.sub(r'[\s()（）\[\]·,/\-_:：]', '', str(x or '')).lower()
def _resolve_stock(site, raw):
    if raw == 0: return (0, '품절', True)
    if raw is None or raw >= 900: return (None, '재고있음', False)
    if (site or '') == 'musinsa' and raw >= _STOCK_CAP: return (None, '재고있음', False)
    return (int(raw), f'{int(raw)}개', False)
def _match_option_stock(cands, opt_color, opt_size):
    """cands = [(color_text,size_text,current_stock)] for one SP."""
    osz = _stk_digits(opt_size)
    if not osz: return None
    oc = _stk_cnorm(opt_color); size_only = None
    for ct, st, stock in cands:
        st = (st or '').strip()
        s_size = _stk_digits(st) or _stk_digits(ct)
        if not s_size or s_size != osz: continue
        has_color = bool(st) and bool((ct or '').strip())
        if has_color:
            sc = _stk_cnorm(ct)
            if oc and sc and (oc == sc or oc in sc or sc in oc): return stock
            continue
        if size_only is None: size_only = stock
    return size_only

SKU = 'SKU-MQQ1SVDB'
c = psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=10)
cur = c.cursor()
cur.execute("SELECT color_code,size_code FROM options WHERE canonical_sku=%s", (SKU,))
COLOR, SIZE = cur.fetchone()

# 등록 URL (옵션 링크 → bundle_source_urls)
cur.execute("""SELECT b.source_key,b.label,b.url FROM option_source_url_links l
               JOIN bundle_source_urls b ON l.bundle_source_url_id=b.id
               WHERE l.option_canonical_sku=%s ORDER BY b.sort_order,b.id""", (SKU,))
links = cur.fetchall()

# 전체 source_products (정규화 매칭용)
cur.execute("""SELECT id,site,url,last_status,last_price,last_stock,
               last_fetched_at,last_error_msg FROM source_products WHERE deleted_at IS NULL""")
sps = cur.fetchall()
sp_by_norm = {_norm(r[2]): r for r in sps}
# source_options 인덱스
cur.execute("""SELECT source_product_id,color_text,size_text,current_price,current_stock
               FROM source_options WHERE deleted_at IS NULL""")
so_idx = {}
for spid, ct, st, pr, stk in cur.fetchall():
    so_idx.setdefault(spid, []).append((ct, st, pr, stk))

# 고유 URL 9개
seen = {}; order = []
for sk, lb, url in links:
    nu = _norm(url)
    if nu not in seen: seen[nu] = (sk, lb, url); order.append(nu)

print(f"옵션 {SKU} ({COLOR} {SIZE}) — 고유 등록 URL {len(order)}개 (링크행 {len(links)}개)\n")
out = []
for i, nu in enumerate(order, 1):
    sk, lb, url = seen[nu]
    sp = sp_by_norm.get(nu)
    print(f"━━━ #{i} [{sk}] {lb}")
    print(f"   URL: {url[:88]}")
    rec = {'no': i, 'source': sk, 'label': lb, 'url': url}
    if not sp:
        print("   ❌ 미크롤 (SourceProduct 없음)\n"); rec['crawled']=False; out.append(rec); continue
    spid, site, _u, status, lprice, lstock, fetched, err = sp
    cands = [(ct, st, stk) for (ct, st, pr, stk) in so_idx.get(spid, [])]
    # 그레이220 옵션단위 가격/재고
    op_price = op_stock = None
    for ct, st, pr, stk in so_idx.get(spid, []):
        ssz = _stk_digits(st) or _stk_digits(ct)
        if ssz == _stk_digits(SIZE) and (COLOR in (ct or '')):
            op_price, op_stock = pr, stk; break
    matched = _match_option_stock(cands, COLOR, SIZE)
    used = matched if matched is not None else lstock
    q, lbl, _o = _resolve_stock(sk, used)
    print(f"   상품단위: status={status} last_price={lprice} last_stock={lstock} fetched={fetched}")
    if err: print(f"   ⚠️ err: {err[:70]}")
    print(f"   옵션단위(그레이220): price={op_price} stock={op_stock}")
    print(f"   ▶ 매트릭스 표시값: 가격={lprice}  재고='{lbl}'(raw {used})")
    if op_price and lprice and int(op_price) != int(lprice):
        print(f"   ❗ 가격불일치: 매트릭스는 상품 {lprice} 표시, 실제 옵션가는 {op_price}")
    print()
    rec.update(crawled=True, status=status, sp_last_price=lprice, sp_last_stock=lstock,
               opt_price=op_price, opt_stock=op_stock, matrix_price=lprice,
               matrix_stock=lbl, fetched=str(fetched), err=(err or '')[:120])
    out.append(rec)

with open('_diag_9urls_out.json','w',encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("→ _diag_9urls_out.json 저장")
c.close()
