"""[live_collect] 롯데온 4 색상 자동 수집 — 정확 추출 패턴.

발견된 절차:
  1. 페이지 load (domcontentloaded + 5s wait, JS 렌더 대기)
  2. 색상 trigger 클릭 (a.btn_product_common_option with text "색상")
  3. 색상 li 클릭 (텍스트 매칭)
  4. 사이즈 trigger 클릭 (a.btn_product_common_option with text "사이즈")
  5. 사이즈 layer li 추출
     - li.className == 'soldout' → 0
     - li.innerText 안 'N개 남음' → N
     - 그 외 → 999 (충분)
"""
from __future__ import annotations

import sys
import re
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

from playwright.sync_api import sync_playwright


URL = "https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559417201"
COLORS = ["그레이", "다크네이비", "블랙(블랙아웃솔)", "블랙(화이트아웃솔)"]
COLOR_NORMAL = {
    "그레이": "그레이",
    "다크네이비": "다크네이비",
    "블랙(블랙아웃솔)": "블랙블랙",
    "블랙(화이트아웃솔)": "블랙화이트",
}


def parse_size(cls: str, text: str) -> tuple[str, int]:
    m = re.match(r"(\d{3})", text)
    if not m:
        return ("", 0)
    size = m.group(1)
    cls = (cls or "").lower()
    text = text or ""
    if "soldout" in cls or "품절" in text or "재입고" in text:
        return (size, 0)
    m_n = re.search(r"(\d+)\s*개\s*남음", text)
    if m_n:
        return (size, int(m_n.group(1)))
    return (size, 999)


def collect_lotteon_color(page, color_text_in_page: str) -> dict[str, int]:
    """단일 색상의 사이즈+재고 추출. 페이지가 이미 load 된 상태."""
    # 색상 trigger
    page.evaluate(r"""
        () => {
            const triggers = Array.from(document.querySelectorAll('a.btn_product_common_option'))
                .filter(a => /색상/.test(a.innerText));
            if (triggers.length > 0) triggers[0].click();
        }
    """)
    page.wait_for_timeout(1500)
    # 색상 클릭
    page.evaluate(f"""
        () => {{
            const lis = Array.from(document.querySelectorAll('li, a, button'))
                .filter(el => (el.innerText || '').trim() === {color_text_in_page!r});
            if (lis.length > 0) lis[0].click();
        }}
    """)
    page.wait_for_timeout(2000)
    # 사이즈 trigger
    page.evaluate(r"""
        () => {
            const triggers = Array.from(document.querySelectorAll('a.btn_product_common_option'))
                .filter(a => /사이즈/.test(a.innerText));
            if (triggers.length > 0) triggers[0].click();
        }
    """)
    page.wait_for_timeout(2000)
    # 사이즈 li 추출
    items = page.evaluate(r"""
        () => {
            const containers = Array.from(document.querySelectorAll('.wrap_scroll_option, .layer_option, .inp_option'))
                .filter(c => Array.from(c.querySelectorAll('li')).some(li => /\d{3}\s*mm/.test(li.innerText||'')));
            for (const c of containers) {
                const lis = Array.from(c.querySelectorAll('li'));
                const out = [];
                for (const li of lis) {
                    const t = (li.innerText || '').trim();
                    if (/\d{3}\s*mm/.test(t)) {
                        out.push({cls: (li.className||'').toString(), text: t});
                    }
                }
                if (out.length > 0) return out;
            }
            return [];
        }
    """)
    out = {}
    for it in items:
        size, stock = parse_size(it["cls"], it["text"])
        if size:
            out[size] = stock
    return out


def main():
    print("=== 롯데온 4 색상 자동 수집 ===")
    lotteon_data: dict[tuple[str, str], int] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for raw_color in COLORS:
            ctx = browser.new_context(viewport={"width": 1280, "height": 4000})
            page = ctx.new_page()
            try:
                page.goto(URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)
                opts = collect_lotteon_color(page, raw_color)
                norm = COLOR_NORMAL[raw_color]
                print(f"[{raw_color} → {norm}] 수집 {len(opts)}: {opts}")
                for size, stock in opts.items():
                    lotteon_data[(norm, size)] = stock
            except Exception as e:
                print(f"[{raw_color}] FAIL: {type(e).__name__}: {e}")
            finally:
                ctx.close()
        browser.close()
    print(f"\n롯데온 자동 수집 총 {len(lotteon_data)} 옵션")
    out_path = _ROOT / "data" / "lotteon_live_stock.json"
    out_path.write_text(
        json.dumps({f"{c}|{s}": v for (c, s), v in lotteon_data.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"저장: {out_path}")
    return lotteon_data


if __name__ == "__main__":
    main()
