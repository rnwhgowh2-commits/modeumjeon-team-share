# -*- coding: utf-8 -*-
"""origin-list 페이지의 검색 input 자동 탐지."""
from __future__ import annotations
import sys, io, time, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

_LOG_PATH = Path("data/_inspect_origin_list.log")
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
_log = open(_LOG_PATH, "w", encoding="utf-8", buffering=1)

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
        user_data_dir=str(profile),
        headless=False, channel="chrome",
        args=list(STEALTH_ARGS),
        ignore_default_args=["--enable-automation"],
        locale="ko-KR",
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://sell.smartstore.naver.com/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(6000)
    W(f"after dashboard — URL: {page.url}")

    # 사이드바 [상품관리] → [상품 조회/수정] JS click
    page.evaluate("""() => {
        const items = document.querySelectorAll('a[role="menuitem"]');
        for (const el of items) {
            if ((el.textContent || '').trim() === '상품관리') { el.click(); break; }
        }
    }""")
    page.wait_for_timeout(1500)
    page.evaluate("""() => {
        const a = document.querySelector('a[href="#/products/origin-list"]');
        if (a) a.click();
    }""")
    page.wait_for_timeout(6000)
    W(f"after origin-list click — URL: {page.url}")

    # 모든 visible input 의 메타 dump
    inputs = page.evaluate("""() => {
        const out = [];
        const ins = document.querySelectorAll('input');
        for (const i of ins) {
            const r = i.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) continue;  // hidden
            out.push({
                type: i.type || '',
                name: i.name || '',
                id: i.id || '',
                placeholder: i.placeholder || '',
                cls: typeof i.className === 'string' ? i.className.slice(0, 80) : '',
                aria: i.getAttribute('aria-label') || '',
                width: Math.round(r.width),
                height: Math.round(r.height),
            });
        }
        return out;
    }""")
    W(f"\n=== visible input: {len(inputs)}개 ===")
    for inp in inputs:
        W(json.dumps(inp, ensure_ascii=False))

    # 검색 버튼 후보
    btns = page.evaluate("""() => {
        const out = [];
        const els = document.querySelectorAll('button, a[role="button"]');
        for (const b of els) {
            const txt = (b.textContent || '').trim();
            if (txt === '검색' || txt === '조회' || /검색|조회/.test(txt)) {
                if (txt.length > 20) continue;
                const r = b.getBoundingClientRect();
                if (r.width === 0) continue;
                out.push({
                    tag: b.tagName,
                    txt: txt,
                    cls: typeof b.className === 'string' ? b.className.slice(0, 80) : '',
                    type: b.getAttribute('type') || '',
                });
            }
        }
        return out;
    }""")
    W(f"\n=== 검색/조회 버튼: {len(btns)}개 ===")
    for b in btns[:15]:
        W(json.dumps(b, ensure_ascii=False))

    W("\ninspect 완료")
    try:
        while ctx.pages:
            time.sleep(1)
    except Exception:
        pass
