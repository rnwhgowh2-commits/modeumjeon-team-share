"""④ 예제 '기준 스크린샷' 서버 캡처 — Playwright 로 PDP 가격 상세를 찍어 R2 에 저장.

캡처(Playwright)는 브라우저 바이너리·로그인 세션이 있는 환경(개발 PC)에서 admin 이 실행한다.
결과 public URL 은 Supabase 의 guide JSON 에 저장되므로, 표시는 prod/dev 어디서나
R2 URL 만 렌더하면 된다(Playwright 불필요).

무신사는 **로그인 세션(data/auth/musinsa_*.json)** 으로 접속해 '나의 할인가/최대 적립'
상세를 펼친(셀렉터 클릭) 뒤 그 회원가 상세 영역만 크롭한다 — 비로그인 공개가 아님.
"""
from __future__ import annotations

import glob
import hashlib
import os

from shared import storage

# 비로그인/폴백용 '가격 택' 셀렉터(접힌 요약).
MUSINSA_PRICE_ANCHORS = (
    '[class*="PriceTotal"]',
    '[class*="DiscountWrap"]',
    '[class*="CurrentPrice"]',
    '[class*="MaxBenefitPrice__Wrap"]',
)
# 로그인+펼침 후 캡처용 — 정가/할인가(PriceTotal) + 펼쳐진 나의할인가·적립 상세(MaxBenefitPrice 전체).
MUSINSA_EXPANDED_ANCHORS = (
    '[class*="PriceTotal"]',
    '[class*="MaxBenefitPrice"]',
)

# 무신사 PDP '나의 할인가/최대 적립' 상세 펼침 — 크롤러(musinsa_playwright)의 펼침 로직 포팅.
#   1) lazy render 발동(스크롤) → 2) CollapseButton 클릭(나의 할인가 펼침)
#   → 3) PointSummaryWrap 반복 클릭(적립 상세) → PointDetailWrap 에 후기/등급/결제수단 적립 보이면 성공
_EXPAND_JS = r"""async () => {
  document.querySelectorAll('[class*="Dimmed"],[class*="Modal"]').forEach(el=>{try{el.remove()}catch(_){}})
  window.scrollTo(0,800); await new Promise(r=>setTimeout(r,1200));
  window.scrollTo(0,0);   await new Promise(r=>setTimeout(r,1200));
  document.querySelectorAll('[class*="MaxBenefitPriceTitle__CollapseButton"]').forEach(el=>{try{el.click()}catch(_){}})
  await new Promise(r=>setTimeout(r,700));
  const mk=/후기\s*적립|등급\s*적립|결제수단\s*적립/;
  for(let i=0;i<12;i++){
    document.querySelectorAll('[class*="MaxBenefitPrice__PointSummaryWrap"]').forEach(el=>{try{el.click()}catch(_){}})
    if(i>=8){document.querySelectorAll('button[aria-expanded="false"]').forEach(el=>{try{el.click()}catch(_){}})}
    await new Promise(r=>setTimeout(r,i<8?450:750));
    const d=document.querySelector('[class*="MaxBenefitPrice__PointDetailWrap"]');
    if(d&&mk.test(d.textContent||'')){await new Promise(r=>setTimeout(r,300));return {ok:true,attempt:i+1};}
  }
  return {ok:false};
}"""


def latest_account(source: str = "musinsa"):
    """auth_dir 에서 가장 최근(mtime) {source}_*.json 세션의 account 명 반환. 없으면 None."""
    from config import SOURCING_AUTH
    auth_dir = SOURCING_AUTH["auth_dir"]
    files = glob.glob(os.path.join(auth_dir, f"{source}_*.json"))
    if not files:
        return None
    newest = max(files, key=os.path.getmtime)
    base = os.path.basename(newest)
    if base.endswith(".json"):
        base = base[:-5]
    prefix = f"{source}_"
    return base[len(prefix):] if base.startswith(prefix) else None


def capture_screenshot(url: str, *, source: str = "musinsa", account=None,
                       expand: bool = True, pad: int = 14, width: int = 1024,
                       timeout_ms: int = 30000) -> bytes:
    """url 의 가격 상세를 JPEG 로 캡처. 로그인 세션이 있으면 회원가 상세를 펼쳐 캡처.

    - source/account: data/auth/{source}_{account}.json 세션. account=None 이면 최신 세션 자동 선택.
    - expand=True: 무신사 '나의 할인가/적립' 상세 펼침 후 캡처.
    - 세션이 있으면 로그인 컨텍스트, 없으면 비로그인 폴백(접힌 공개가).
    브라우저 미설치/실행 실패 시 RuntimeError.
    """
    if not (url.startswith("http://") or url.startswith("https://")):
        raise RuntimeError("http(s) URL 이 아닙니다")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover - import 환경 의존
        raise RuntimeError(f"Playwright 미설치: {e}")

    from lemouton.sourcing import auth as sauth
    acct = account or latest_account(source)
    logged_in = bool(acct and sauth.has_state(source, acct))

    try:
        with sync_playwright() as p:
            if logged_in:
                browser, ctx = sauth.new_context_with_state(p, source, acct)
                anchors = MUSINSA_EXPANDED_ANCHORS if expand else MUSINSA_PRICE_ANCHORS
            else:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0 Safari/537.36"),
                )
                anchors = MUSINSA_PRICE_ANCHORS
            try:
                page = ctx.new_page()
                page.set_viewport_size({"width": width, "height": 1500})
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(1800)
                if logged_in and expand:
                    try:
                        page.evaluate(_EXPAND_JS)
                    except Exception:
                        pass
                    page.wait_for_timeout(500)
                clip = _price_clip(page, anchors, pad)
                if clip:
                    return page.screenshot(type="jpeg", quality=85, clip=clip)
                return page.screenshot(type="jpeg", quality=80)
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
