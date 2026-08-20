# -*- coding: utf-8 -*-
"""소싱처 상세 HTML 안 **타 마켓 브랜딩 자산** 감지 — 자동 제거 ❌ · 표면화 ⭕.

[2026-07-23 사장님 결정 (나)안]
  「타 마켓 브랜딩 이미지는 **자동으로 제거하지 않고**, 등록 전 점검에서 보여 주고
   사장님이 판단한다.」

왜 자동 제거가 아닌가
  파일명 판정은 **오탐**이 난다. 패션 소싱처에는 `ssg` · `emart` 같은 조각이 들어간
  멀쩡한 상품 사진이 섞여 있고, 자동으로 지우면 대표·상세 사진이 조용히 사라져
  **빈 상세로 등록**된다(조용한 실패). 반대로 안 보여 주면 경쟁 마켓 배너가 그대로
  올라가 **판매금지·상품삭제**다. → 지우지 말고 **보여 준다**.

무엇이 문제인가 (실측, 2026-07-23 · `tests/sources/fixtures/ssg_detail_iframe.html`)
    <a href="https://department.ssg.com/plan/planShop.ssg?dispCmptId=…">
      <img src="https://nike2094.godohosting.com/products/info/ssg_banner.jpg">
  링크는 공통 관문(`base.sanitize_detail_html` 의 `a` unwrap)이 이미 버렸지만 **사진은
  남는다**. 그 상세가 `registration/compile_more.py:98` 을 지나 옥션·G마켓·11번가·
  롯데온 본문으로 그대로 올라간다.

이 모듈은 **읽기만 한다.** 실제로 빼는 것은 사장님이 화면에서 고른 주소뿐이고,
그때만 `remove_assets_from_detail` 이 불린다.
"""
import re
from urllib.parse import urljoin, urlsplit

# ─────────────────────────────────────────────────────────────────
# 타 마켓 브랜드 토큰
# ─────────────────────────────────────────────────────────────────
#: 호스트·경로에서 찾는 경쟁 마켓 이름. 소문자 비교.
#:   순서가 곧 **보고 우선순위**다 — 한 주소에 둘이 걸리면 앞엣것을 보고한다
#:   (`sell.smartstore.naver.com` → naver 가 아니라 smartstore 로 말해야 뜻이 통한다).
FOREIGN_MARKET_TOKENS = (
    "smartstore", "elevenst", "wemakeprice", "lotteimall", "shinsegae",
    "interpark", "gmarket", "coupang", "auction", "lotteon",
    "emart", "naver", "11st", "tmon", "ssg",
)

# 상품 사진만 올라오는 CDN 호스트 — **여기 있는 건 절대 신고하지 않는다.**
#   호스트 이름 자체에 마켓 이름이 들어 있어(`ssgcdn` · `lotteimall`) 규칙만으로는
#   상품 사진과 브랜딩 배너를 못 가른다. 소싱처의 상품 사진 CDN 을 명시로 빼 준다.
#   ※ 하위 도메인까지 인정한다(`newimg.ssgcdn.com`). 단 `ssgcdn.com.evil.kr` 처럼
#     **뒤에 다른 도메인이 붙은 사칭**은 인정하지 않는다(끝이 일치해야 한다).
PRODUCT_IMAGE_CDN_HOSTS = (
    "ssgcdn.com",            # SSG.COM 상품 사진 (sitem·simg·sui)
    "lotteimall.com",        # 롯데아이몰 상품 사진 (image·image2·ca)
    "pstatic.net",           # 네이버 스마트스토어 상품 사진 (shop-phinf 등)
    "msscdn.net",            # 무신사
    "ssfshop.com",           # SSF샵
    "thehyundai.com",        # 현대Hmall
    "hmall.com",             # 현대Hmall (구 도메인)
    "esmplus.com",           # 셀러 이미지 호스팅(ESM Plus) — 소싱처 셀러가 실제로 쓴다
)

#: `<img>` 에서 실주소가 숨어 있는 지연로딩 속성 (base.sanitize_detail_html 과 같은 목록).
_LAZY_SRC_ATTRS = ("src", "ec-data-src", "data-src", "data-original",
                   "data-lazy-src", "data-echo")


def _compile(token: str) -> re.Pattern:
    """토큰 경계 규칙 — 🔴 오탐이 곧 상품 사진 삭제라 여기가 핵심이다.

    - **왼쪽**: 글자·숫자가 오면 안 된다. 해시 한복판(`a1tmon2`)·다른 낱말
      (`lastmonth` 의 `tmon`, `themart` 의 `emart`)을 걸러낸다.
    - **오른쪽**: 글자가 오면 안 된다(`ssgcdn` · `auctions` · `navera`).
      숫자는 허용한다 — `emart24` · `ssg2_banner.jpg` 는 진짜 브랜딩이다.
    - 숫자를 품은 토큰(`11st`)은 오른쪽도 숫자를 막는다(`2011street`).
    """
    right = r"(?![a-z0-9])" if any(c.isdigit() for c in token) else r"(?![a-z])"
    return re.compile(rf"(?<![a-z0-9]){re.escape(token)}{right}", re.I)


_TOKEN_RES = tuple((t, _compile(t)) for t in FOREIGN_MARKET_TOKENS)


def _is_product_cdn(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in PRODUCT_IMAGE_CDN_HOSTS)


def _match_token(url: str) -> str | None:
    """주소 하나 → 걸린 마켓 토큰 (없으면 None).

    ★ **쿼리스트링·프래그먼트는 보지 않는다.** SSG 상품 URL 은 실제로
      `?ckwhere=naver`(네이버 유입 쿠폰) 같은 유입·추적 파라미터를 달고 다녀서,
      거기까지 보면 멀쩡한 상품 사진이 전부 「네이버 이미지」가 된다.
    """
    if not url:
        return None
    try:
        sp = urlsplit(url)
    except ValueError:
        return None
    host = (sp.hostname or "").lower()
    if host and _is_product_cdn(host):
        return None
    # 스킴 없는 상대경로면 urlsplit 이 전부 path 로 준다 — 그대로 본다.
    hay = f"{host}{sp.path}".lower()
    for token, rx in _TOKEN_RES:
        if rx.search(hay):
            return token
    return None


def _abs(url: str, base_url: str) -> str:
    u = (url or "").strip()
    if not u or u.startswith("data:"):
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith(("http://", "https://")):
        return u
    return urljoin(base_url, u) if base_url else u


def detect_foreign_market_assets(html, base_url: str = "") -> list[dict]:
    """상세 HTML → 타 마켓 브랜딩으로 **의심되는** 자산 목록.

    반환: ``[{'url': 절대주소, 'token': 'ssg', 'where': 'img'|'link'}, …]``
      · 같은 주소는 한 번만 (화면에서 중복 체크박스가 뜨면 못 쓴다)
      · **아무것도 지우지 않는다** — 판단은 사장님이 화면에서 한다

    인자는 HTML 문자열 또는 BeautifulSoup Tag. 못 읽으면 빈 리스트.
    """
    if html is None:
        return []
    text = html if isinstance(html, str) else str(html)
    if not text.strip():
        return []
    try:
        from bs4 import BeautifulSoup
        node = BeautifulSoup(text, "html.parser")
    except Exception:
        return []

    out: list[dict] = []
    seen: set[str] = set()

    def _add(raw: str, where: str) -> None:
        url = _abs(raw, base_url)
        if not url or url in seen:
            return
        token = _match_token(url)
        if not token:
            return
        seen.add(url)
        out.append({"url": url, "token": token, "where": where})

    for tag in node.find_all("img"):
        for attr in _LAZY_SRC_ATTRS:
            v = str(tag.get(attr) or "").strip()
            if v and not v.startswith("data:"):
                _add(v, "img")
                break
    for tag in node.find_all("a"):
        _add(str(tag.get("href") or "").strip(), "link")
    return out


def remove_assets_from_detail(html, urls) -> tuple[str, int]:
    """상세 HTML 에서 **지정한 주소만** 빼고 나머지는 그대로 → (정리본, 뺀 개수).

    · `<img>` 는 통째로 제거한다(사진 자체가 문제라서).
    · `<a>` 는 **껍데기만 벗긴다**(unwrap) — 안의 글·사진은 상세 본문이라 살린다.
      공통 관문 `base.sanitize_detail_html` 의 `a` 처리와 같은 규약이다.
    · 되돌리기는 **재크롤**이다(이 함수는 원본을 복원하지 못한다).
    """
    text = "" if html is None else (html if isinstance(html, str) else str(html))
    wanted = {str(u).strip() for u in (urls or []) if str(u or "").strip()}
    if not text.strip() or not wanted:
        return text, 0
    try:
        from bs4 import BeautifulSoup
        node = BeautifulSoup(text, "html.parser")
    except Exception:
        return text, 0

    removed = 0
    for tag in list(node.find_all("img")):
        vals = [str(tag.get(a) or "").strip() for a in _LAZY_SRC_ATTRS]
        if any(v in wanted for v in vals if v):
            tag.decompose()
            removed += 1
    for tag in list(node.find_all("a")):
        if str(tag.get("href") or "").strip() in wanted:
            tag.unwrap()
            removed += 1
    if not removed:
        return text, 0
    return str(node).strip(), removed
