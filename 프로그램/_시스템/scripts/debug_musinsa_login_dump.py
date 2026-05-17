"""무신사 로그인 모드 분석 — 4 URL 전체 회원 화면 텍스트 dump + breakdown.

실행: python -m scripts.debug_musinsa_login_dump
출력:
  - scripts/_musinsa_dump_{pid}.txt — textContent + breakdown JSON
  - 콘솔: 4 URL 결과 매트릭스
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Add repo root to PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from config import SOURCING_AUTH, DEFAULT_HEADERS
from lemouton.sourcing.auth import get_state_path, has_state
from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler, _EXTRACT_JS


URLS = [
    "https://www.musinsa.com/products/3728480",
    "https://www.musinsa.com/products/3976350",
    "https://www.musinsa.com/products/4210142",
    "https://www.musinsa.com/products/6111473",
]

ACCOUNT = "영빈"
OUT_DIR = ROOT / "scripts"
HEADLESS = True   # 안정성 vs 가시화 trade-off — 디버깅은 False 추천


# ── 추가 dump JS: textContent 펼친 후 + 쿠폰 영역 raw ─────────
_DUMP_JS = """
async () => {
    // Dimmed 제거 + PointSummaryWrap 클릭 (펼침)
    document.querySelectorAll('[class*="Dimmed"], [class*="Modal"]').forEach(el => {
        try { el.remove(); } catch(_) {}
    });
    document.querySelectorAll('[class*="MaxBenefitPrice__PointSummaryWrap"]').forEach(el => {
        try { el.click(); } catch(_) {}
    });
    await new Promise(r => setTimeout(r, 1000));

    // 가장 큰 MaxBenefitPrice
    let wrap = null;
    let largestLen = 0;
    document.querySelectorAll('[class*="MaxBenefitPrice"]').forEach(el => {
        const len = (el.textContent || '').length;
        if (len > largestLen) { largestLen = len; wrap = el; }
    });

    const result = {
        url: location.href,
        title: document.title,
        max_benefit_textContent: wrap ? (wrap.textContent || '').slice(0, 4000) : '',
        max_benefit_textContent_length: wrap ? (wrap.textContent || '').length : 0,
        // 쿠폰 영역 추정
        coupon_area_texts: [],
        // 등급 노출 영역
        grade_text_samples: [],
        // PointDetailWrap 존재 여부
        point_detail_wrap: !!document.querySelector('[class*="MaxBenefitPrice__PointDetailWrap"]'),
        // 무신사머니 토글
        money_toggle_text: '',
    };

    // 쿠폰 영역 — Coupon 클래스 또는 "쿠폰" 텍스트 포함
    document.querySelectorAll('[class*="Coupon"], [class*="coupon"]').forEach(el => {
        const t = (el.textContent || '').trim();
        if (t && t.length < 500 && /쿠폰|할인/.test(t)) {
            result.coupon_area_texts.push(t.slice(0, 300));
        }
    });

    // 등급 텍스트 samples
    document.querySelectorAll('*').forEach(el => {
        const t = (el.textContent || '').trim();
        if (/LV\\.[0-9]/.test(t) && t.length < 200) {
            result.grade_text_samples.push(t.slice(0, 200));
        }
    });
    result.grade_text_samples = [...new Set(result.grade_text_samples)].slice(0, 5);

    // 무신사머니 토글 (활성/비활성)
    document.querySelectorAll('*').forEach(el => {
        const t = (el.textContent || '').trim();
        if (/무신사\\s*머니/.test(t) && t.length < 100 && !result.money_toggle_text) {
            result.money_toggle_text = t;
        }
    });

    return result;
}
"""


def dump_one(page, url: str, pid: str) -> dict:
    print(f"\n{'='*70}\nURL: {url}")
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    try:
        page.wait_for_selector(
            '[data-mds="DropdownTriggerBox"], [class*="CalculatedPrice"]',
            timeout=8000,
        )
    except PWTimeout:
        print("  (timeout — 셀렉터 대기 실패 but 계속)")

    time.sleep(2)  # 추가 안정화

    # Dump
    dump = page.evaluate(_DUMP_JS)
    # Extract (실 산식)
    try:
        extract = page.evaluate(_EXTRACT_JS, {"dropdownWait": 200, "stockCap": 10})
    except Exception as e:
        extract = {"error": str(e)}

    # Save full dump
    out_path = OUT_DIR / f"_musinsa_dump_{pid}.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"URL: {url}\n")
        f.write(f"Title: {dump.get('title','')}\n")
        f.write(f"PointDetailWrap found: {dump.get('point_detail_wrap')}\n")
        f.write(f"max_benefit textContent length: {dump.get('max_benefit_textContent_length')}\n")
        f.write("\n─── max_benefit textContent (펼친 후) ───\n")
        f.write(dump.get('max_benefit_textContent', ''))
        f.write("\n\n─── 쿠폰 영역 ───\n")
        for t in dump.get('coupon_area_texts', []):
            f.write(f"  · {t}\n")
        f.write("\n─── 등급 LV.X 샘플 ───\n")
        for t in dump.get('grade_text_samples', []):
            f.write(f"  · {t}\n")
        f.write(f"\n─── 무신사머니 토글 텍스트 ───\n  {dump.get('money_toggle_text','')}\n")
        f.write("\n\n═══ 추출 결과 (extract JS) ═══\n")
        f.write(json.dumps(extract, indent=2, ensure_ascii=False))
    print(f"  → {out_path}")

    return {"dump": dump, "extract": extract}


def main():
    # 로그인 세션 확인
    src_used = None
    for src in ("무신사", "musinsa"):
        if has_state(src, ACCOUNT):
            src_used = src
            print(f"세션 발견: {get_state_path(src, ACCOUNT)}")
            break
    if not src_used:
        print(f"ERROR: 무신사 로그인 세션 없음 (account={ACCOUNT})")
        sys.exit(1)

    state_path = get_state_path(src_used, ACCOUNT)
    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            storage_state=state_path,
            user_agent=DEFAULT_HEADERS["User-Agent"],
            extra_http_headers={"Accept-Language": DEFAULT_HEADERS["Accept-Language"]},
        )
        try:
            for url in URLS:
                pid = url.rstrip("/").rsplit("/", 1)[-1]
                page = context.new_page()
                try:
                    r = dump_one(page, url, pid)
                    r["pid"] = pid
                    r["url"] = url
                    results.append(r)
                except Exception as e:
                    print(f"  ERROR: {e}")
                    results.append({"pid": pid, "url": url, "error": str(e)})
                finally:
                    page.close()
        finally:
            context.close()
            browser.close()

    # Summary table
    print(f"\n\n{'='*90}\n매트릭스 요약 (login mode)\n{'='*90}")
    headers = ["pid", "wrap", "len", "grade_disc", "grade_rwd", "money_rwd", "coupon", "review", "tier2"]
    print(f"{'pid':<10} {'wrap':<6} {'len':<6} {'g_dis%':<8} {'g_rwd%':<8} {'mny%':<7} {'coupon':<9} {'review':<7} {'ben_ui':<10}")
    for r in results:
        if "error" in r:
            print(f"{r['pid']:<10} ERROR: {r['error'][:60]}")
            continue
        ex = r["extract"]
        bd = ex.get("breakdown", {}) if isinstance(ex, dict) else {}
        print(
            f"{r['pid']:<10} "
            f"{'Y' if bd.get('wrap_found') else 'N':<6} "
            f"{bd.get('text_length',0):<6} "
            f"{bd.get('grade_discount_rate',0)*100:<8.2f} "
            f"{bd.get('grade_reward_rate',0)*100:<8.2f} "
            f"{bd.get('money_reward_rate',0)*100:<7.2f} "
            f"{bd.get('coupon',0):<9} "
            f"{'Y' if bd.get('has_review_reward_item') else 'N':<7} "
            f"{ex.get('benefitPriceFromUI',0):<10}"
        )


if __name__ == "__main__":
    main()
