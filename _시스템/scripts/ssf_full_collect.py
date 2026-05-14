"""[live_collect] SSF 4 색상 url 자동 수집 — 정확 추출 패턴 확정.

발견된 정확 추출 절차:
  1. domcontentloaded + wait 4s
  2. button.buy 클릭 (JS evaluate, viewport 우회)
  3. wait 2s — options-layer.open 모달 출현
  4. 모달 내부 div.select.lg.unapplied (사이즈) 클릭 → dropdown 펼침
  5. wait 2s
  6. 사이즈 옵션 텍스트 추출 (regex: '230[230]' / '235[235]\xa0/ 품절임박(3)')
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


URLS = [
    ("그레이",     "https://www.ssfshop.com/LEMOUTON/GRG424102517755/good"),
    ("다크네이비", "https://www.ssfshop.com/LEMOUTON/GRG424102517744/good"),
    ("블랙화이트", "https://www.ssfshop.com/LEMOUTON/GRG424102517707/good"),
    ("블랙블랙",   "https://www.ssfshop.com/LEMOUTON/GRG424102517741/good"),
]


def parse_size_line(line: str) -> tuple[str, int]:
    """'235[235]\xa0/ 품절임박(3)' or '230[230]' or '230 (품절)' 파싱.

    - '품절' / '재입고' 명시 → 0
    - '품절임박(N)' / '품절임박 N' → N
    - 숫자만 (사이즈 라벨만) → 999 (충분)
    """
    line = line.replace("\xa0", " ").strip()
    m_size = re.match(r"(\d{3})", line)
    if not m_size:
        return ("", 0)
    size = m_size.group(1)
    if "품절(" in line or "(품절)" in line or "재입고" in line:
        return (size, 0)
    m_near = re.search(r"품절임박\s*\(?(\d+)\)?", line)
    if m_near:
        return (size, int(m_near.group(1)))
    if re.search(r"(\d+)\s*개\s*남음", line):
        m = re.search(r"(\d+)\s*개\s*남음", line)
        return (size, int(m.group(1)))
    return (size, 999)


def collect_ssf_color(page, url: str) -> dict[str, int]:
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    # 1) 구매 버튼 클릭
    page.evaluate("document.querySelector('button.buy')?.click()")
    page.wait_for_timeout(2000)
    # 2) 사이즈 select trigger 클릭
    page.evaluate("""
        () => {
            const layer = document.querySelector('.options-layer.open, .options-layer');
            if (!layer) return;
            const triggers = Array.from(layer.querySelectorAll('div.select')).filter(
                el => /사이즈/.test(el.innerText)
            );
            if (triggers.length > 0) triggers[0].click();
        }
    """)
    page.wait_for_timeout(2000)

    # 3) 사이즈 옵션 라인 추출 (이전 검증으로 div 1 cls=undefined 안에 모든 라인 있음)
    text = page.evaluate(r"""
        () => {
            // 사이즈 라인이 있는 list 찾기
            const lists = Array.from(document.querySelectorAll('ul, ol, [class*=List], div'))
                .filter(el => {
                    const t = el.innerText || '';
                    // 230 ~ 290 에 / 또는 (품절) 또는 줄바꿈으로 라벨된 패턴
                    return /\d{3}\s*\[/.test(t);
                });
            if (lists.length === 0) return null;
            // 가장 적은 길이의 (정밀한) list
            lists.sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
            return lists[0].innerText;
        }
    """)

    out = {}
    if text:
        for line in text.split("\n"):
            size, stock = parse_size_line(line)
            if size and size in ("220", "225", "230", "235", "240", "245", "250", "255", "260", "265", "270", "275", "280", "285", "290"):
                out[size] = stock
    return out


def main():
    print("=== SSF 4 색상 자동 수집 ===")
    ssf_data: dict[tuple[str, str], int] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for color, url in URLS:
            ctx = browser.new_context(viewport={"width": 1280, "height": 4000})
            page = ctx.new_page()
            try:
                opts = collect_ssf_color(page, url)
                print(f"[{color}] 수집 옵션 {len(opts)}: {opts}")
                for size, stock in opts.items():
                    ssf_data[(color, size)] = stock
            except Exception as e:
                print(f"[{color}] FAIL: {type(e).__name__}: {e}")
            finally:
                ctx.close()
        browser.close()

    print(f"\nSSF 자동 수집 총 {len(ssf_data)} 옵션")
    out_path = _ROOT / "data" / "ssf_live_stock.json"
    out_path.write_text(
        json.dumps({f"{c}|{s}": v for (c, s), v in ssf_data.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"저장: {out_path}")
    return ssf_data


if __name__ == "__main__":
    main()
