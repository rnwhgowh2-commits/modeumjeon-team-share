"""[test] 새 모델 4 url 크롤러 테스트 — 재고 cap=10 적용."""
from __future__ import annotations

import sys
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

from playwright.sync_api import sync_playwright
from lemouton.sourcing.auth import new_context_with_state

MUSINSA = "https://www.musinsa.com/products/3798322"
SSF = "https://www.ssfshop.com/LEMOUTON/GRG424102517791/good"
LOTTEON = "https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559418051"
LEM = "https://m.lemouton.co.kr/product/detail.html?product_no=227&cate_no=65&display_group=1"

CAP = 10


def parse_musinsa(text: str) -> tuple[str, int]:
    m = re.search(r"(\d{3})\s*mm", text)
    sz = m.group(1) if m else ""
    if "품절" in text or "재입고" in text:
        return (sz, 0)
    m = re.search(r"(\d+)\s*개\s*남음", text)
    if m:
        return (sz, min(int(m.group(1)), CAP))
    return (sz, CAP)


def parse_ssf(line: str) -> tuple[str, int]:
    line = line.replace("\xa0", " ").strip()
    m = re.match(r"(\d{3})", line)
    if not m:
        return ("", 0)
    sz = m.group(1)
    if "품절(" in line or "(품절)" in line or "재입고" in line:
        return (sz, 0)
    m_n = re.search(r"품절임박\s*\(?(\d+)\)?", line)
    if m_n:
        return (sz, min(int(m_n.group(1)), CAP))
    return (sz, CAP)


def parse_lotte(cls: str, text: str) -> tuple[str, int]:
    m = re.match(r"(\d{3})", text)
    if not m:
        return ("", 0)
    sz = m.group(1)
    if "soldout" in (cls or "").lower() or "품절" in text or "재입고" in text:
        return (sz, 0)
    m_n = re.search(r"(\d+)\s*개\s*남음", text)
    if m_n:
        return (sz, min(int(m_n.group(1)), CAP))
    return (sz, CAP)


def lem_color(t: str) -> str:
    if "화이트" in t and "블랙" in t:
        return "블랙화이트"
    if t.count("블랙") >= 2:
        return "블랙블랙"
    if "다크" in t or "네이비" in t:
        return "다크네이비"
    if "그레이" in t:
        return "그레이"
    if "크림" in t:
        return "크림"
    if "아이보리" in t:
        return "아이보리"
    return t


# ===== 무신사 =====
print("===== 무신사 =====")
print(f"URL: {MUSINSA}")
with sync_playwright() as pw:
    browser, ctx = new_context_with_state(pw, "musinsa", "영빈", browser=None)
    page = ctx.new_page()
    page.goto(MUSINSA, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    page.evaluate("""() => {
        document.querySelectorAll('[class*=FeatureNudging], [class*=Dimmed], [class*=Modal], [class*=Overlay]').forEach(el => el.remove());
    }""")
    print(f"product: {page.title()[:80]}")
    triggers = page.query_selector_all('[data-mds="DropdownTriggerBox"]')
    if triggers:
        triggers[-1].click(force=True)
        page.wait_for_timeout(2000)
        items = page.query_selector_all('[data-mds="StaticDropdownMenuItem"]')
        print(f"사이즈 옵션 {len(items)}:")
        for it in items:
            t = it.inner_text()
            sz, st = parse_musinsa(t)
            print(f"  {sz} → stock={st}  | raw={t[:80]!r}")
    ctx.close()
    browser.close()

# ===== SSF =====
print()
print("===== SSF =====")
print(f"URL: {SSF}")
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_context(viewport={"width": 1280, "height": 4000}).new_page()
    page.goto(SSF, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    print(f"product: {page.title()[:80]}")
    page.evaluate("document.querySelector('button.buy')?.click()")
    page.wait_for_timeout(2000)
    page.evaluate(r"""() => {
        const layer = document.querySelector('.options-layer.open, .options-layer');
        if (!layer) return;
        const triggers = Array.from(layer.querySelectorAll('div.select')).filter(el => /사이즈/.test(el.innerText));
        if (triggers.length > 0) triggers[0].click();
    }""")
    page.wait_for_timeout(2000)
    text = page.evaluate(r"""() => {
        const lists = Array.from(document.querySelectorAll('ul, ol, [class*=List], div'))
            .filter(el => /\d{3}\s*\[/.test(el.innerText || ''));
        if (lists.length === 0) return null;
        lists.sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
        return lists[0].innerText;
    }""")
    if text:
        for line in text.split("\n"):
            sz, st = parse_ssf(line)
            if sz:
                print(f"  {sz} → stock={st}  | raw={line.strip()!r}")
    browser.close()

# ===== 롯데온 =====
print()
print("===== 롯데온 =====")
print(f"URL: {LOTTEON}")
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_context(viewport={"width": 1280, "height": 4000}).new_page()
    page.goto(LOTTEON, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(5000)
    print(f"product: {page.title()[:80]}")
    colors = page.evaluate(r"""() => {
        const containers = Array.from(document.querySelectorAll('div.layer_option, .inp_option'));
        for (const c of containers) {
            const lis = Array.from(c.querySelectorAll('li')).map(li => (li.innerText || '').trim()).filter(t => t && !/선택|사이즈|^\d{3}/.test(t));
            if (lis.length > 0 && lis.length < 10) return lis;
        }
        return [];
    }""")
    print(f"색상 옵션 {len(colors)}: {colors}")
    for color in colors:
        page.evaluate(r"""() => {
            const t = Array.from(document.querySelectorAll('a.btn_product_common_option')).filter(a => /색상/.test(a.innerText));
            if (t.length > 0) t[0].click();
        }""")
        page.wait_for_timeout(1500)
        page.evaluate(f"""() => {{
            const lis = Array.from(document.querySelectorAll('li, a, button')).filter(el => (el.innerText || '').trim() === {color!r});
            if (lis.length > 0) lis[0].click();
        }}""")
        page.wait_for_timeout(2000)
        page.evaluate(r"""() => {
            const t = Array.from(document.querySelectorAll('a.btn_product_common_option')).filter(a => /사이즈/.test(a.innerText));
            if (t.length > 0) t[0].click();
        }""")
        page.wait_for_timeout(2000)
        items = page.evaluate(r"""() => {
            const containers = Array.from(document.querySelectorAll('.wrap_scroll_option, .layer_option, .inp_option'))
                .filter(c => Array.from(c.querySelectorAll('li')).some(li => /\d{3}\s*mm/.test(li.innerText || '')));
            for (const c of containers) {
                const lis = Array.from(c.querySelectorAll('li'));
                const out = [];
                for (const li of lis) {
                    const t = (li.innerText || '').trim();
                    if (/\d{3}\s*mm/.test(t)) out.push({cls: (li.className||'').toString(), text: t});
                }
                if (out.length > 0) return out;
            }
            return [];
        }""")
        print(f"\n[{color}] 사이즈 {len(items)}:")
        for it in items:
            sz, st = parse_lotte(it["cls"], it["text"])
            if sz:
                print(f"  {sz} → stock={st}  | raw={it['text'][:60]!r}")
    browser.close()

# ===== 르무통 자체사이트 =====
print()
print("===== 르무통 자체사이트 =====")
print(f"URL: {LEM}")
from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
r = LemoutonCrawler(prefer_playwright=True).fetch(LEM)
print(f"product: {r.product_name_raw[:80]}")
print(f"옵션 총 {len(r.options)}:")
seen_colors = set()
for o in r.options:
    color = lem_color(o.get("color_text", "") or "")
    sz = (o.get("size_text", "") or "").replace("mm", "").strip()
    raw_st = o.get("stock", 0)
    st = 0 if raw_st == 0 else CAP
    if color not in seen_colors:
        print(f"\n[{color}]")
        seen_colors.add(color)
    print(f"  {sz}: stock={st}  | raw_color={o.get('color_text', '')!r} stock_raw={raw_st}")
