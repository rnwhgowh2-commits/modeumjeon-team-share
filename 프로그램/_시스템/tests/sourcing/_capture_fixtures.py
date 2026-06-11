"""소싱처 HTML 픽스처 캡처 스크립트.

실행:
    python tests/sourcing/_capture_fixtures.py

각 소싱처 URL 에서 raw HTML 을 받아
tests/sourcing/fixtures/<key>_sample.html 로 저장한다.

실패 소싱처는 중단하지 않고 건너뛰며, 결과를 콘솔에 보고한다.
"""
from __future__ import annotations

import pathlib
import sys
import traceback

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# 캡처 대상 (key → URL)
# ─────────────────────────────────────────────────────────────
TARGETS: dict[str, str] = {
    "ssf": "https://www.ssfshop.com/LEMOUTON/GRG426021974780/good",
    "ssg": (
        "https://www.ssg.com/item/itemView.ssg"
        "?itemId=1000809938058&siteNo=6009&salestrNo=1004"
    ),
    "ss_lemouton": "https://brand.naver.com/lemouton/products/9496367527",
    "lemouton": (
        "https://lemouton.co.kr/product/detail.html"
        "?product_no=219&cate_no=64&display_group=1"
    ),
}

MIN_BYTES = 3_000  # 픽스처 유효성 최소 크기

# ─────────────────────────────────────────────────────────────
# HTML fetch 헬퍼
# ─────────────────────────────────────────────────────────────

def _fetch_ssf(url: str) -> str:
    """SSF: curl_cffi chrome120 impersonate."""
    from curl_cffi import requests as cffi_requests
    resp = cffi_requests.get(url, impersonate="chrome120", timeout=30)
    resp.raise_for_status()
    return resp.text


def _fetch_ssg(url: str) -> str:
    """SSG: curl_cffi + 세션 워밍업 + 네이버 유입 파라미터."""
    # SsgCrawler._fetch_html 와 동일 로직을 인라인 (의존성 최소화)
    import time
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    from curl_cffi import requests as cffi_requests

    NAVER_COUPON_PARAMS = {
        "ckwhere": "ssg_naver",
        "appPopYn": "n",
        "utm_medium": "PCS",
        "utm_source": "naver",
        "utm_campaign": "naver_pcs",
    }

    def _apply_params(u: str) -> str:
        parts = urlsplit(u)
        q = dict(parse_qsl(parts.query, keep_blank_values=True))
        q.update(NAVER_COUPON_PARAMS)
        return urlunsplit(parts._replace(query=urlencode(q)))

    HEADERS = {
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.ssg.com/",
    }

    fetch_url = _apply_params(url)
    sess = cffi_requests.Session(impersonate="chrome120")
    # 워밍업
    try:
        sess.get("https://www.ssg.com/", timeout=15,
                 headers={"Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"})
        time.sleep(1.5)
    except Exception:
        pass

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = sess.get(fetch_url, timeout=30, headers=HEADERS)
        except Exception as e:
            last_exc = e
            time.sleep(4 * (attempt + 1))
            continue
        if resp.status_code == 429:
            last_exc = RuntimeError("HTTP 429")
            time.sleep(8 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.text
    raise last_exc or RuntimeError("[SSG] fetch 실패")


def _fetch_ss_lemouton(url: str) -> str:
    """스마트스토어(brand.naver.com): curl_cffi."""
    from curl_cffi import requests as cffi_requests
    resp = cffi_requests.get(url, impersonate="chrome120", timeout=30,
                              allow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _fetch_lemouton(url: str) -> str:
    """르무통 공홈: requests (표준 HTTP)."""
    import requests
    UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    return resp.text


FETCHERS = {
    "ssf": _fetch_ssf,
    "ssg": _fetch_ssg,
    "ss_lemouton": _fetch_ss_lemouton,
    "lemouton": _fetch_lemouton,
}

# ─────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────

def main() -> None:
    success: list[tuple[str, int]] = []
    failures: list[tuple[str, str]] = []

    for key, url in TARGETS.items():
        out_path = FIXTURES_DIR / f"{key}_sample.html"
        fetcher = FETCHERS[key]
        print(f"[{key}] 캡처 시작 → {url}")
        try:
            html = fetcher(url)
            nbytes = len(html.encode("utf-8"))
            if nbytes < MIN_BYTES:
                raise ValueError(
                    f"응답이 너무 작음 ({nbytes} bytes < {MIN_BYTES}). "
                    "차단/리다이렉트 의심."
                )
            out_path.write_text(html, encoding="utf-8")
            print(f"  [OK] saved: {out_path.name}  ({nbytes:,} bytes)")
            success.append((key, nbytes))
        except Exception as e:
            err_summary = f"{type(e).__name__}: {e}"
            # 상세 트레이스는 stderr
            traceback.print_exc(file=sys.stderr)
            print(f"  [NG] failed: {err_summary}")
            failures.append((key, err_summary))

    print("\n" + "=" * 60)
    print(f"캡처 결과: 성공 {len(success)}/{len(TARGETS)}")
    for key, nbytes in success:
        print(f"  [OK]  {key}: {nbytes:,} bytes")
    for key, reason in failures:
        print(f"  [NG]  {key}: {reason}")
    print("=" * 60)

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    # sys.path 에 _시스템 루트 추가 (lemouton 패키지 import 가능하게)
    _here = pathlib.Path(__file__).parent.parent.parent  # _시스템 루트
    if str(_here) not in sys.path:
        sys.path.insert(0, str(_here))
    main()
