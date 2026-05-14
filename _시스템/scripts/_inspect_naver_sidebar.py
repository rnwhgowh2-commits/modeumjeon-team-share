# -*- coding: utf-8 -*-
"""Naver Seller Center 사이드바 DOM 자동 검사.

dashboard 도달 후 [상품관리] / 상품 검색 메뉴 후보 노드들을 dump.
launcher selector 추출용 일회성 스크립트.
"""
from __future__ import annotations
import sys, io, time, json
from pathlib import Path

_LOG_PATH = Path("data/_inspect_naver_sidebar.log")
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
_log_file = open(_LOG_PATH, "w", encoding="utf-8", buffering=1)  # line-buffered

def print(*a, **kw):  # type: ignore[no-redef]
    msg = " ".join(str(x) for x in a)
    _log_file.write(msg + "\n")
    _log_file.flush()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from lemouton.auth.profile_store import default_store, STEALTH_ARGS

store = default_store()
profile_path = store.profile_dir("smartstore", "SMARTSTORE_MAIN")
store.kill_chrome_using(profile_path)
store.cleanup_lock(profile_path)

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(profile_path),
        headless=False,
        channel="chrome",
        args=list(STEALTH_ARGS),
        ignore_default_args=["--enable-automation"],
        locale="ko-KR",
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://sell.smartstore.naver.com/", wait_until="domcontentloaded", timeout=30000)
    print("waited; settle 8s for SPA")
    page.wait_for_timeout(8000)
    print("URL:", page.url)

    # 1) "상품관리" 텍스트 포함 요소 모두 dump
    js = """() => {
        const out = [];
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.children.length > 5) continue;  // 컨테이너 제외
            const txt = (el.textContent || '').trim();
            if (txt.length > 30) continue;
            if (txt === '상품관리' || txt === '상품 조회·수정' || txt === '상품 조회' ||
                txt === '상품 조회/수정' || txt === '상품 등록' || txt.includes('상품관리')) {
                let parentChain = [];
                let p = el.parentElement;
                let depth = 0;
                while (p && depth < 4) { parentChain.push(p.tagName + (p.className ? '.' + (typeof p.className === 'string' ? p.className.slice(0,40) : '') : '')); p = p.parentElement; depth++; }
                out.push({
                    tag: el.tagName,
                    txt: txt,
                    cls: typeof el.className === 'string' ? el.className.slice(0, 80) : '',
                    href: el.getAttribute('href') || '',
                    role: el.getAttribute('role') || '',
                    id: el.id || '',
                    parents: parentChain,
                });
            }
        }
        return out;
    }"""
    matches = page.evaluate(js)
    print()
    print(f"=== '상품관리' 매칭 노드: {len(matches)}개 ===")
    for m in matches[:20]:
        print(json.dumps(m, ensure_ascii=False))

    # 2) 사이드바 / nav 영역의 모든 a 태그 dump
    js2 = """() => {
        const containers = document.querySelectorAll('aside, nav, [role="navigation"], .gnb, .lnb, [class*="nav"], [class*="menu"], [class*="LNB"], [class*="GNB"], [class*="sidebar"]');
        const out = [];
        for (const c of containers) {
            const links = c.querySelectorAll('a, button[role="link"], li[role="menuitem"]');
            for (const a of links) {
                const txt = (a.textContent || '').trim().replace(/\\s+/g, ' ');
                if (txt.length === 0 || txt.length > 30) continue;
                if (!/상품|관리|조회|수정/.test(txt)) continue;
                out.push({
                    container: c.tagName + (typeof c.className === 'string' ? '.' + c.className.slice(0,40) : ''),
                    tag: a.tagName,
                    txt: txt,
                    cls: typeof a.className === 'string' ? a.className.slice(0, 80) : '',
                    href: a.getAttribute('href') || '',
                });
            }
        }
        return out;
    }"""
    matches2 = page.evaluate(js2)
    print()
    print(f"=== 사이드바·nav 안 '상품/관리/조회' 링크: {len(matches2)}개 ===")
    for m in matches2[:20]:
        print(json.dumps(m, ensure_ascii=False))

    print()
    print("inspect 완료. 창 닫지 마세요 — 결과 보고 후 launcher 업데이트 시작.")
    # 사용자가 닫을 때까지 대기
    try:
        while context.pages:
            time.sleep(1)
    except Exception:
        pass
