# -*- coding: utf-8 -*-
"""musinsa brand 페이지 렌더 → 상품 list 추출."""
import sys, json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

_LOG = Path("data/_inspect_musinsa_brand.log")
_LOG.parent.mkdir(parents=True, exist_ok=True)
log = open(_LOG, "w", encoding="utf-8", buffering=1)
def W(s): log.write(s + "\n"); log.flush()

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, channel="chrome")
    ctx = browser.new_context(locale="ko-KR", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36")
    page = ctx.new_page()

    # XHR 요청 캡쳐
    api_calls = []
    def on_response(resp):
        u = resp.url
        if any(k in u for k in ['/api/', '/goods', '/products', 'lemouton', 'brand']):
            try:
                if resp.status == 200 and 'json' in (resp.headers.get('content-type', '')):
                    api_calls.append({'url': u, 'status': resp.status})
            except Exception:
                pass
    page.on('response', on_response)

    # 검색 페이지 시도 — 키워드로 르무통 클래식 2 검색
    page.goto("https://www.musinsa.com/search/goods?keyword=%EB%A5%B4%EB%AC%B4%ED%86%B5%20%ED%81%B4%EB%9E%98%EC%8B%9D%202",
              wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(8000)
    for _ in range(5):
        page.evaluate("window.scrollBy(0, 1000)")
        page.wait_for_timeout(800)

    page_url = page.url
    W(f"final URL: {page_url}")
    body_html = page.content()
    W(f"body size: {len(body_html)}")

    # 모든 /products/N 추출
    pids = set(re.findall(r'/products/(\d{5,9})', body_html))
    W(f'/products/ pid 추출: {len(pids)}개')

    # XHR 응답 캐치 — listen for /goods or /products list API calls
    products = page.evaluate("""() => {
        const out = [];
        const seen = new Set();
        document.querySelectorAll('a[href*="/products/"]').forEach(a => {
            const m = a.href.match(/\\/products\\/(\\d+)/);
            if (!m || seen.has(m[1])) return;
            seen.add(m[1]);
            const card = a.closest('li, [class*="card"], [class*="item"]') || a;
            const txt = (card.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 100);
            out.push({pid: m[1], name: txt});
        });
        return out;
    }""")
    W(f"\nproducts via DOM: {len(products)}")
    for p in products[:50]:
        W(f"  {p['pid']}: {p['name']}")

    # __NEXT_DATA__ 추출
    nd_match = re.search(r'__NEXT_DATA__\"\s*type=\"application/json\">(.+?)</script>', body_html, re.DOTALL)
    if nd_match:
        try:
            nd = json.loads(nd_match.group(1))
            txt = json.dumps(nd, ensure_ascii=False)
            pairs = re.findall(r'"goodsNo"\s*:\s*(\d+)[^{}]*?"goodsNm"\s*:\s*"([^"]+)', txt)
            W(f"\n__NEXT_DATA__ goodsNo+Nm: {len(pairs)}")
            for gid, name in pairs[:30]:
                if '클래식' in name:
                    W(f"  ★ {gid}: {name}")
        except Exception as _e:
            W(f"  __NEXT_DATA__ parse err: {_e}")

    W(f"\n=== XHR JSON 응답: {len(api_calls)} ===")
    for c in api_calls[:30]:
        W(f"  [{c['status']}] {c['url'][:120]}")

    browser.close()
W("done")
