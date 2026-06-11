"""④ 예제 '기준 스크린샷' 서버 캡처 — Playwright 로 공개 PDP 를 찍어 R2 에 저장.

캡처(Playwright)는 브라우저 바이너리가 설치된 환경(개발 PC)에서 admin 이 실행한다.
결과 public URL 은 Supabase 의 guide JSON 에 저장되므로, 표시는 prod/dev 어디서나
R2 URL 만 렌더하면 된다(Playwright 불필요).

크롤 회원가/혜택 펼침과 무관한 '레이아웃 기준 스냅샷'이다 — 비로그인 공개화면.
"""
from __future__ import annotations

import hashlib

from shared import storage

# 무신사 PDP '가격 택' 영역 셀렉터(합집합 bbox 로 크롭) — 크롤러와 동일 클래스 패턴.
#  PriceTotal/DiscountWrap/CurrentPrice = 정가·할인율·할인가, MaxBenefitPrice__Wrap = 나의 할인가·최대적립
MUSINSA_PRICE_ANCHORS = (
    '[class*="PriceTotal"]',
    '[class*="DiscountWrap"]',
    '[class*="CurrentPrice"]',
    '[class*="MaxBenefitPrice__Wrap"]',
)


def capture_screenshot(url: str, *, anchors=MUSINSA_PRICE_ANCHORS, pad: int = 16,
                       width: int = 1024, full_page: bool = False,
                       timeout_ms: int = 25000) -> bytes:
    """url 을 headless Chromium 으로 열어 JPEG 스크린샷 bytes 반환.

    anchors 가 주어지면 해당 요소들의 합집합 bounding box(+pad)만 크롭(='가격 택'만).
    anchors 매칭 실패 또는 anchors=None 이면 full_page/뷰포트 폴백.
    브라우저 미설치/실행 실패 시 RuntimeError(사용자에게 그대로 노출).
    """
    if not (url.startswith("http://") or url.startswith("https://")):
        raise RuntimeError("http(s) URL 이 아닙니다")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover - import 환경 의존
        raise RuntimeError(f"Playwright 미설치: {e}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(
                    viewport={"width": width, "height": 1400},
                    device_scale_factor=1,
                    user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0 Safari/537.36"),
                )
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2500)  # 가격/이미지 렌더 대기
                clip = _price_clip(page, anchors, pad) if anchors else None
                if clip:
                    return page.screenshot(type="jpeg", quality=85, clip=clip)
                return page.screenshot(full_page=full_page, type="jpeg", quality=78)
            finally:
                browser.close()
    except RuntimeError:
        raise
    except Exception as e:
        msg = str(e)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            raise RuntimeError("Playwright 브라우저 미설치 — `python -m playwright install chromium` 필요")
        raise RuntimeError(f"캡처 실패: {msg[:200]}")


def _price_clip(page, anchors, pad: int):
    """anchors 요소들의 합집합 bounding box(+pad) 반환. 못 찾으면 None."""
    boxes = []
    for sel in anchors:
        try:
            for el in page.query_selector_all(sel):
                bb = el.bounding_box()
                if bb and bb["width"] > 0 and bb["height"] > 0:
                    boxes.append(bb)
        except Exception:
            continue
    if not boxes:
        return None
    x0 = min(b["x"] for b in boxes)
    y0 = min(b["y"] for b in boxes)
    x1 = max(b["x"] + b["width"] for b in boxes)
    y1 = max(b["y"] + b["height"] for b in boxes)
    x = max(0, x0 - pad)
    y = max(0, y0 - pad)
    return {"x": x, "y": y, "width": (x1 - x0) + 2 * pad, "height": (y1 - y0) + 2 * pad}


def store_guide_screenshot(sid: int, index: int, data: bytes) -> str:
    """캡처 bytes 를 R2 에 저장하고 public URL 반환.

    키는 내용 해시 기반(content-addressed) — 재캡처 시 URL 이 바뀌어 브라우저 캐시도 자동 무효화.
    """
    h = hashlib.sha1(data).hexdigest()[:10]
    key = f"guide-shots/{int(sid)}/ex{int(index)}-{h}.jpg"
    return storage.put_object(data, key, "image/jpeg")
