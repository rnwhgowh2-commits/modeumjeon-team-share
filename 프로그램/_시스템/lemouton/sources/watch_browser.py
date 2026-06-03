"""[2026-06-03] '보면서 크롤' 보기 전용 브라우저.

WATCH_CRAWL=1 (내 PC 로컬 실행) 일 때, HTTP(curl) 방식 소싱처(SSF/SSG/스스 등)의
URL 을 '보이는' Chromium 으로 잠깐 띄워 사용자가 눈으로 확인하게 한다.
(르무통/무신사·회원가/롯데온 같은 Playwright 크롤러는 자체적으로 headful 로 뜸.)

설계 메모:
  - 데이터 수집과 무관 — 순수 화면 표시용. 실패해도 크롤 자체엔 영향 없음.
  - 각 URL 마다 '열고 → 보여주고 → 닫는' 단발 방식.
    이유: 크롤러도 sync_playwright 를 쓰므로, 보기 브라우저를 루프 내내 열어두면
    같은 스레드에서 sync API 가 중첩돼 충돌할 수 있다. 단발이면 절대 겹치지 않음.
"""
from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)


def watch_enabled() -> bool:
    """'보면서 크롤' 모드 여부 (로컬 .bat 가 WATCH_CRAWL=1 설정)."""
    return os.environ.get('WATCH_CRAWL') == '1'


def show_url(url: str, *, dwell_ms: int = 1300) -> None:
    """보이는 브라우저로 URL 을 열어 ~dwell_ms 동안 보여준 뒤 닫는다.

    WATCH_CRAWL 미설정이면 아무 것도 안 함. 모든 예외는 삼켜서 크롤을 막지 않음.
    """
    if not watch_enabled() or not url:
        return
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                page = browser.new_page()
                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                page.wait_for_timeout(dwell_ms)
            finally:
                browser.close()
    except Exception as e:
        _log.debug('[watch] show_url 실패 %s: %s', url, e)
