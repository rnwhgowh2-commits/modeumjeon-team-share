# -*- coding: utf-8 -*-
"""origin-list 의 searchKeywordType 라디오 라벨 정확히 dump."""
from __future__ import annotations
import sys, time, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

_LOG = Path("data/_inspect_search_radios.log")
_LOG.parent.mkdir(parents=True, exist_ok=True)
_log = open(_LOG, "w", encoding="utf-8", buffering=1)

def W(s):
    _log.write(s + "\n")
    _log.flush()

from lemouton.auth.profile_store import default_store, STEALTH_ARGS
store = default_store()
profile = store.profile_dir("smartstore", "SMARTSTORE_MAIN")
store.kill_chrome_using(profile)
store.cleanup_lock(profile)

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(profile), headless=False, channel="chrome",
        args=list(STEALTH_ARGS), ignore_default_args=["--enable-automation"], locale="ko-KR",
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://sell.smartstore.naver.com/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(6000)

    # 사이드바 → 상품관리 → 상품 조회/수정
    page.evaluate("""() => {
        for (const el of document.querySelectorAll('a[role="menuitem"]')) {
            if ((el.textContent || '').trim() === '상품관리') { el.click(); break; }
        }
    }""")
    page.wait_for_timeout(1500)
    page.evaluate("""() => {
        const a = document.querySelector('a[href="#/products/origin-list"]');
        if (a) a.click();
    }""")
    page.wait_for_timeout(6000)
    W(f"URL: {page.url}")

    # searchKeywordType 라디오 + 그 주변 텍스트 정확히 dump
    radios_info = page.evaluate("""() => {
        const out = [];
        const radios = document.querySelectorAll('input[type="radio"][name="searchKeywordType"]');
        for (const r of radios) {
            // method 1: htmlFor 라벨
            let labelByFor = null;
            if (r.id) {
                const lab = document.querySelector(`label[for="${r.id}"]`);
                if (lab) labelByFor = (lab.textContent || '').trim();
            }
            // method 2: closest label
            const closeLabel = r.closest('label');
            const closeLabelTxt = closeLabel ? (closeLabel.textContent || '').trim() : null;
            // method 3: 부모/형제 텍스트
            const parent = r.parentElement;
            const parentTxt = parent ? (parent.textContent || '').trim() : null;
            // method 4: 다음 형제 텍스트
            let nextText = null;
            let n = r.nextSibling;
            while (n && nextText === null) {
                if (n.nodeType === 3 && (n.textContent || '').trim()) nextText = n.textContent.trim();
                else if (n.nodeType === 1) nextText = (n.textContent || '').trim();
                n = n.nextSibling;
            }
            out.push({
                id: r.id || null,
                value: r.value || null,
                checked: r.checked,
                labelByFor: labelByFor,
                closeLabel: closeLabelTxt ? closeLabelTxt.slice(0, 50) : null,
                parent: parentTxt ? parentTxt.slice(0, 80) : null,
                nextSibling: nextText ? nextText.slice(0, 50) : null,
            });
        }
        return out;
    }""")
    W(f"\n=== searchKeywordType 라디오 {len(radios_info)}개 ===")
    for r in radios_info:
        W(json.dumps(r, ensure_ascii=False))

    W("\ninspect 완료")
    try:
        while ctx.pages:
            time.sleep(1)
    except Exception:
        pass
