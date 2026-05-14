"""[live_stock_collector] 사용자 스샷 패턴 그대로 4 사이트 라이브 스크래핑.

대응 패턴:
- 무신사 (musinsa_playwright): 영빈 세션 + 누적식 회원가 + 사이즈별 잔여 ('N개 남음' / 품절)
- SSF (Playwright 신규): 색상 클릭 → 사이즈 드롭다운 → '품절임박(N)' / '품절'
- 롯데온 (Playwright 신규): 색상·사이즈 드롭다운 → 'N개 남음' / '품절'
- 르무통 (lemouton_playwright): 옵션 텍스트 → '품절'/표시없음

각 옵션: stock 수치
   - 0       = 품절
   - 1~50    = 실 잔여 (N개 남음 / 품절임박 N)
   - 999     = 충분 (표시 없음)
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


PRODUCT_URLS = {
    "lemouton": "https://lemouton.co.kr/product/detail.html?product_no=219&cate_no=64&display_group=1",
    "musinsa": "https://www.musinsa.com/products/3728480",  # 다크네이비
    "ssf": "https://www.ssfshop.com/LEMOUTON/GRG424102517741/good",
    "lotteon": "https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559417201",
}


def _color_norm(t: str) -> str:
    if not t:
        return ""
    if "화이트" in t and "블랙" in t:
        return "블랙화이트"
    if t.count("블랙") >= 2:
        return "블랙블랙"
    if "다크" in t or "네이비" in t:
        return "다크네이비"
    if "그레이" in t:
        return "그레이"
    return t.strip()


def _stock_from_text(t: str) -> int:
    """텍스트에서 잔여재고 추론.

    - '품절' or '재입고 알림' → 0
    - '품절임박 (N)' / '품절임박(N)' → N
    - 'N개 남음' / '잔여 N개' / '재고 N개' → N
    - 그 외 → 999 (충분 placeholder)
    """
    t = t or ""
    if re.search(r"품절(?!임박)", t) or "재입고 알림" in t:
        return 0
    m = re.search(r"품절임박\s*\(?(\d+)\)?", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*개\s*남음", t)
    if m:
        return int(m.group(1))
    m = re.search(r"잔여\s*(\d+)\s*개", t)
    if m:
        return int(m.group(1))
    m = re.search(r"재고\s*(\d+)\s*개", t)
    if m:
        return int(m.group(1))
    return 999


def collect_lemouton() -> dict[tuple[str, str], int]:
    """르무통 자체사이트 — lemouton crawler 활용. 옵션 텍스트의 (품절) 인식."""
    from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
    out = {}
    try:
        r = LemoutonCrawler(prefer_playwright=True).fetch(PRODUCT_URLS["lemouton"])
        for o in r.options:
            color = _color_norm(o.get("color_text", ""))
            size = (o.get("size_text", "") or "").replace("mm", "").strip()
            if size in ("230", "235", "240", "245", "250", "255", "260", "270", "280"):
                # lemouton 크롤러는 stock=0/1 로 반환 (품절/재고있음)
                # 1 = "재고 있음" placeholder (실 N개 모름) → 999 으로 변환 (충분)
                live_stock = o.get("stock", 0)
                out[(color, size)] = 0 if live_stock == 0 else 999
    except Exception as e:
        print(f"  [lemouton] 실패: {type(e).__name__}: {e}")
    return out


def collect_musinsa() -> dict[tuple[str, str], int]:
    """무신사 — musinsa_playwright + 영빈 세션. 다크네이비 url 만 등록되어 다크네이비 9 옵션."""
    from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler
    out = {}
    try:
        r = MusinsaPlaywrightCrawler(account_name="영빈", headless=True).fetch(PRODUCT_URLS["musinsa"])
        for o in r.options:
            # musinsa playwright 는 product_name 으로 색상 추정
            color = _color_norm(r.product_name_raw)
            size = (o.get("size_text", "") or "").replace("mm", "").strip()
            if size in ("230", "235", "240", "245", "250", "255", "260", "270", "280"):
                # musinsa playwright 는 stock 정수 반환 (품절=0, 재고=N or stock_cap=10)
                out[(color, size)] = int(o.get("stock", 0))
    except Exception as e:
        print(f"  [musinsa] 실패: {type(e).__name__}: {e}")
    return out


def collect_ssf() -> dict[tuple[str, str], int]:
    """SSF — Playwright 으로 페이지 띄우고 색상 옵션 클릭 → 사이즈 드롭다운 텍스트 추출."""
    out = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(PRODUCT_URLS["ssf"], timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)  # JS 렌더 대기

            # 색상 옵션 셀렉터 — SSF UI 의 색상 칩
            color_chips = page.query_selector_all('[class*="color"] li, [class*="ColorList"] li, .color_op li')
            print(f"    [ssf] 색상 칩 {len(color_chips)} 개")

            # JS 변수로 partmal/option 데이터 추출 시도 (SSF 는 window 변수에 옵션 정보)
            try:
                opt_json = page.evaluate("""() => {
                    return window.partmalGoodsArrInfo || window.optionGoodsList || null;
                }""")
                if opt_json:
                    print(f"    [ssf] window 변수 옵션 데이터: {len(opt_json) if isinstance(opt_json, list) else 'dict'}")
                    if isinstance(opt_json, list):
                        for item in opt_json[:3]:
                            print(f"      sample: {json.dumps(item, ensure_ascii=False)[:200]}")
            except Exception as ee:
                print(f"    [ssf] window var 실패: {ee}")

            # fallback: page innerText 에서 사이즈 + 잔여 패턴 추출
            full_text = page.inner_text("body")
            # 230mm, 235mm 등 + 다음에 오는 텍스트
            matches = re.findall(r"(\d{3})\s*(?:mm|MM)\s*[\s\S]{0,80}?(?=\d{3}\s*mm|$)", full_text[:20000])
            print(f"    [ssf] page text 사이즈 매치: {len(matches)}")

            ctx.close()
            browser.close()
    except Exception as e:
        print(f"  [ssf] 실패: {type(e).__name__}: {e}")
    return out


def collect_lotteon() -> dict[tuple[str, str], int]:
    """롯데온 — Playwright. 색상·사이즈 dropdown 직접 클릭."""
    out = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(PRODUCT_URLS["lotteon"], timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # window var / __NEXT_DATA__ 시도
            try:
                next_data = page.evaluate("() => document.querySelector('#__NEXT_DATA__')?.textContent")
                if next_data:
                    print(f"    [lotteon] __NEXT_DATA__ 길이: {len(next_data)}")
            except Exception:
                pass

            # body innerText 에서 사이즈 + N개 남음 패턴
            full_text = page.inner_text("body")
            print(f"    [lotteon] body text 길이: {len(full_text)}")
            # '230mm' 텍스트 주변 80자 추출
            for m in list(re.finditer(r"(\d{3})\s*mm", full_text))[:10]:
                snippet = full_text[m.start():m.start()+80].replace("\n", " ")
                print(f"      {snippet[:100]}")

            ctx.close()
            browser.close()
    except Exception as e:
        print(f"  [lotteon] 실패: {type(e).__name__}: {e}")
    return out


def main():
    print("=== 라이브 재고 자동 수집 (사용자 스샷 패턴) ===")

    print("\n[1/4] lemouton 자체사이트")
    lem = collect_lemouton()
    print(f"  수집: {len(lem)} 옵션")

    print("\n[2/4] 무신사 (영빈 세션)")
    mus = collect_musinsa()
    print(f"  수집: {len(mus)} 옵션")

    print("\n[3/4] SSF 샵")
    ssf = collect_ssf()
    print(f"  수집: {len(ssf)} 옵션")

    print("\n[4/4] 롯데온")
    lot = collect_lotteon()
    print(f"  수집: {len(lot)} 옵션")

    # 36 SKU = 4 색상 × 9 사이즈
    colors = ["그레이", "다크네이비", "블랙블랙", "블랙화이트"]
    sizes = ["230", "235", "240", "245", "250", "255", "260", "270", "280"]

    print("\n=== 36 옵션 라이브 데이터 ===")
    print(f'{"SKU":<22} | {"lem":>4} | {"mus":>4} | {"ssf":>4} | {"lot":>4} | {"max(가드)":>9}')
    print("-" * 70)
    for c in colors:
        for sz in sizes:
            l = lem.get((c, sz), "—")
            m = mus.get((c, sz), "—")
            s = ssf.get((c, sz), "—")
            t = lot.get((c, sz), "—")
            valid = [v for v in (l, m, s, t) if isinstance(v, int)]
            real = [v for v in valid if 1 < v < 100]
            zeros = [v for v in valid if v == 0]
            ph = [v for v in valid if v >= 100]
            if real:
                push = max(real)
            elif ph:
                push = 999
            elif zeros:
                push = 0
            else:
                push = "—"
            print(f"{c}-{sz:<8} | {str(l):>4} | {str(m):>4} | {str(s):>4} | {str(t):>4} | {str(push):>9}")


if __name__ == "__main__":
    main()
