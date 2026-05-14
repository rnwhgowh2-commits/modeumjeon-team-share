"""[live_collect] 무신사 4 색상 url 자동 수집 — 정확 추출 패턴.

발견된 정확 추출 절차:
  1. domcontentloaded (networkidle 은 무신사 background 요청으로 타임아웃)
  2. wait 4s (React 렌더 안정)
  3. 오버레이 제거 (FeatureNudging, Dimmed, Modal, Overlay)
  4. [data-mds="DropdownTriggerBox"] 마지막 trigger click(force=True)
  5. wait 2s (메뉴 펼침)
  6. [data-mds="StaticDropdownMenuItem"] innerText 추출
  7. parse: 사이즈 (`230mm`), 품절 여부, `N개 남음`
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
from lemouton.sourcing.auth import new_context_with_state


URLS = [
    ("그레이",     "https://www.musinsa.com/products/3728477"),
    ("다크네이비", "https://www.musinsa.com/products/3728480"),
    ("블랙화이트", "https://www.musinsa.com/products/3728431"),
    ("블랙블랙",   "https://www.musinsa.com/products/3728475"),
]


def parse_item_text(text: str) -> tuple[str, int]:
    """'235mm\\n내일(목) 발송 예정\\n4개 남음' → ('235', 4).

    - 품절 / 재입고 알림 → stock=0
    - N개 남음 → stock=N
    - 표시 없음 → stock=999 (충분)
    """
    size = ""
    m = re.search(r"(\d{3})\s*mm", text)
    if m:
        size = m.group(1)
    if "품절" in text or "재입고" in text:
        return (size, 0)
    m = re.search(r"(\d+)\s*개\s*남음", text)
    if m:
        return (size, int(m.group(1)))
    return (size, 999)


def collect_musinsa_color(page, url: str) -> dict[str, int]:
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)
    # 오버레이 제거
    page.evaluate("""
        () => {
            document.querySelectorAll(
                '[class*=FeatureNudging], [class*=Dimmed], [class*=Modal], [class*=Overlay]'
            ).forEach(el => el.remove());
        }
    """)
    triggers = page.query_selector_all('[data-mds="DropdownTriggerBox"]')
    if not triggers:
        return {}
    triggers[-1].click(force=True)
    page.wait_for_timeout(2000)
    items = page.query_selector_all('[data-mds="StaticDropdownMenuItem"]')
    out = {}
    for it in items:
        size, stock = parse_item_text(it.inner_text())
        if size:
            out[size] = stock
    return out


def main():
    print("=== 무신사 4 색상 자동 수집 ===")
    musinsa_data: dict[tuple[str, str], int] = {}
    with sync_playwright() as pw:
        browser, ctx = new_context_with_state(pw, "musinsa", "영빈", browser=None)
        page = ctx.new_page()
        for color, url in URLS:
            try:
                opts = collect_musinsa_color(page, url)
                print(f"[{color}] 수집 옵션 {len(opts)}: {opts}")
                for size, stock in opts.items():
                    musinsa_data[(color, size)] = stock
            except Exception as e:
                print(f"[{color}] FAIL: {type(e).__name__}: {e}")
        ctx.close()
        browser.close()

    print()
    print(f"무신사 자동 수집 총 {len(musinsa_data)} 옵션")
    return musinsa_data


if __name__ == "__main__":
    data = main()
    # JSON 저장 (다음 단계 통합용)
    out_path = _ROOT / "data" / "musinsa_live_stock.json"
    out_path.write_text(
        json.dumps({f"{c}|{s}": v for (c, s), v in data.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n저장 위치: {out_path}")
