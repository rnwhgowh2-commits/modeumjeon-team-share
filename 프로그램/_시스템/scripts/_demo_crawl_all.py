"""크롤링 시연 — 르무통 클래식-그레이-230 의 7개 소싱처 동시 재크롤 → 매입가 비교."""
import sys, io, time, urllib.parse, urllib.request, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SKU = '르무통 클래식-그레이-230'
BASE = 'http://localhost:5052'

SOURCES = [
    (1, '르무통 공홈'),
    (2, '스스 르무통'),
    (3, '무신사 (로그인 세션)'),
    (4, 'SSF'),
    (5, '롯데온'),
    (6, '롯데홈쇼핑'),
    (7, 'SSG'),
]

def http_post(url, timeout=120):
    req = urllib.request.Request(url, method='POST', headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {'error': e.read().decode('utf-8', errors='replace')}
    except Exception as e:
        return 0, {'error': str(e)}

def http_get(url, timeout=60):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {'error': e.read().decode('utf-8', errors='replace')}
    except Exception as e:
        return 0, {'error': str(e)}

sku_enc = urllib.parse.quote(SKU)
print('=' * 96)
print(f'  📦 크롤링 시연 — {SKU} · 7개 소싱처 동시 재크롤')
print('=' * 96)
print()

results = {}
for src_id, label in SOURCES:
    t0 = time.time()
    print(f'  ⏳ [{src_id}/{label}] 크롤링 중...', end='', flush=True)
    url = f'{BASE}/api/options/{sku_enc}/sources/{src_id}/refetch'
    status, body = http_post(url, timeout=180)
    dt = time.time() - t0
    if status == 200 and body.get('ok'):
        sp = body.get('sale_price') or body.get('crawled_price') or body.get('data', {}).get('sale_price')
        results[src_id] = {'ok': True, 'sale_price': sp, 'time': dt, 'body': body}
        print(f'  ✅ {dt:.1f}s  sale_price={sp}')
    else:
        results[src_id] = {'ok': False, 'time': dt, 'body': body}
        err = body.get('error', body)
        if isinstance(err, dict): err = str(err)[:100]
        print(f'  ❌ {dt:.1f}s  {err[:120] if isinstance(err, str) else err}')

print()
print('=' * 96)
print('  💰 매입가 (compute_breakdown) 일괄 계산')
print('=' * 96)
items = [{'sku': SKU, 'source_id': sid, 'sale_price': results[sid].get('sale_price') or 0}
         for sid, _ in SOURCES if results.get(sid, {}).get('sale_price')]
if items:
    payload = json.dumps({'items': items}).encode('utf-8')
    req = urllib.request.Request(f'{BASE}/api/source-benefits/breakdowns', data=payload, method='POST',
                                  headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            bd_body = json.loads(resp.read().decode('utf-8'))
        bd_results = bd_body.get('results', {})
        for src_id, label in SOURCES:
            r = results.get(src_id, {})
            sp = r.get('sale_price')
            key = f'{SKU}|{src_id}'
            bd = bd_results.get(key, {})
            buy = bd.get('final_price')
            steps = bd.get('steps', [])
            if sp and buy is not None:
                save = sp - buy
                pct = (save / sp * 100) if sp else 0
                print(f'  [{src_id}] {label:30}  sale={sp:>8,}원  →  buy={buy:>8,}원  (-{save:>5,}원, {pct:.1f}%↓)  steps={len(steps)}')
            elif sp:
                print(f'  [{src_id}] {label:30}  sale={sp:>8,}원  (breakdown 없음)')
            else:
                print(f'  [{src_id}] {label:30}  ❌ 크롤링 실패')
    except Exception as e:
        print(f'  ❌ breakdown API 에러: {e}')
print()
print('  ✅ 시연 완료')
