"""크롤러 추상 인터페이스.

각 사이트별 구현체는 fetch(product_url) -> CrawlResult 만 채우면 된다.
공통 후처리 (정규화, 매칭, 큐 적재)는 pipeline.py에서 담당.
"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class LoginExpiredError(RuntimeError):
    """로그인 세션 만료 — 송장전송기 무제한 로그인 패턴.

    크롤러가 비로그인 페이지를 감지했을 때 던짐.
    상위 호출자 (api_pricing 등) 가 catch 후 자동 재로그인 + 재시도.
    """
    def __init__(self, site: str, detail: str = ""):
        super().__init__(f"[{site}] 세션 만료 감지" + (f" — {detail}" if detail else ""))
        self.site = site
        self.detail = detail


@dataclass
class CrawlResult:
    source: str                    # 'lemouton' | 'musinsa' | ...
    product_url: str
    product_name_raw: str          # 사이트의 원본 상품명
    options: list[dict] = field(default_factory=list)
    # options 항목: {
    #   option_id: str,            # 사이트의 옵션 ID
    #   color_text: str,           # 원본 색상 표기
    #   size_text: str,            # 원본 사이즈 표기
    #   price: int,                # 원 단위 가격
    #   stock: int,                # 재고 수량 (품절이면 0)
    # }
    brand: str = ""                # 브랜드명 (사이트에서 추출, 없으면 빈 문자열)
    discount_info: str = ""        # 할인 명목 텍스트 (즉시할인/쿠폰/등급 등 자유 텍스트)
    fetched_at: str | None = None  # ISO 8601, pipeline에서 set
    # [2026-07-23 M3] 소싱처 카테고리 경로(빵부스러기). 예: '신발>스니커즈>여성운동화'.
    #   못 뽑으면 빈 문자열 — 추측 금지. asdict(res) → JSON → 확장까지 그대로 전파된다.
    category_path: str = ""
    # ─────────────────────────────────────────────────────────────
    # [2026-07-23 M4-4] 소싱처 상품 이미지·상세페이지
    # ─────────────────────────────────────────────────────────────
    # image_urls : 대표(첫 원소) + 추가 이미지의 **절대 URL 목록**. 파일은 받지 않는다.
    #   ★ 지식재산권 — 이미지는 브랜드 저작물이다. 이번 단계는 **URL 수집·저장까지**만
    #     하고 마켓 업로드는 하지 않는다. 실제 업로드는 이후 단계에서 브랜드별
    #     제외 정책(스펙의 '브랜드 지재권 제한표')을 통과한 건에 대해서만 한다.
    #   ★ 마켓별 쓰임 — 스스는 원본 URL 을 못 쓰고 네이버 CDN 업로드가 필수
    #     (`registration/image_prep.py::prepare_cdn_images`), 나머지 5마켓은 공개 URL 그대로.
    #   못 뽑으면 빈 리스트 — 추측·대체이미지 금지.
    image_urls: list[str] = field(default_factory=list)
    # detail_html : 소싱처 상세설명 영역 HTML 원문(스크립트·추적 태그 제거본).
    #   옥션·G마켓·11번가·롯데온 4마켓은 필수값(`registration/compile_more.py`).
    #   못 뽑으면 빈 문자열 — 상품명·가격으로 지어내지 않는다.
    detail_html: str = ""


# ─────────────────────────────────────────────────────────────────
# [2026-07-23 M3] 빵부스러기 조각 → 카테고리 경로 문자열 (소싱처 공통)
# ─────────────────────────────────────────────────────────────────
# 최상위 '홈' 더미 라벨 — 모든 상품에 똑같이 붙어 카테고리를 구분하지 못한다(정보량 0).
#   제외 근거: ①경로 depth 가 소싱처마다 1씩 어긋나 맵핑 키가 안 맞는다
#             ②사이트 루트는 이미 source_id 가 표현한다(중복)
#   맨 앞 조각에만 적용한다 — 중간에 '홈'이라는 실제 카테고리가 있어도 지우지 않기 위해서.
_HOME_LABELS = {"홈", "home", "메인", "main", "처음", "top", "전체"}


def build_category_path(parts) -> str:
    """빵부스러기 조각 목록 → ``'대>중>소'``. 못 쓸 값이면 빈 문자열.

    - 조각별 앞뒤 공백·개행·중복 공백 정리, 빈 조각 제거
    - 맨 앞의 '홈'/'HOME' 같은 최상위 더미 라벨 제외 (사유는 ``_HOME_LABELS`` 주석)
    - 사이트별 셀렉터는 각 크롤러가 담당하고, 여기서는 문자열 정리만 한다.
    """
    cleaned: list[str] = []
    for raw in (parts or []):
        seg = re.sub(r"\s+", " ", str(raw or "")).strip()
        if seg:
            cleaned.append(seg)
    while cleaned and cleaned[0].strip().lower() in _HOME_LABELS:
        cleaned.pop(0)
    return ">".join(cleaned)


# ─────────────────────────────────────────────────────────────────
# [2026-07-23 M4-4] 이미지 URL 목록 조립 (소싱처 공통)
# ─────────────────────────────────────────────────────────────────
# 상품 이미지가 아닌 게 섞이면 그대로 마켓에 올라가 오등록이 된다. 파일명·경로에
# 아래 조각이 있으면 상품 사진이 아니다(아이콘·배지·1px 트래킹 픽셀·플레이스홀더).
_NON_PRODUCT_IMG_HINTS = (
    "blank.gif", "blank.png", "spacer.gif", "1x1.", "pixel.gif", "loading.gif",
    "/icon", "icon_", "_icon", "/btn", "btn_", "sprite", "logo", "/banner",
    "noimage", "no_image", "no-image", "dummy", "placeholder", "transparent.",
)
# 이미지로 볼 확장자. 쿼리스트링이 붙는 CDN 이 많아 '경로에 포함' 으로 본다.
_IMG_EXT_HINTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif")


def build_image_urls(urls, base_url: str = "", *, limit: int = 20) -> list[str]:
    """이미지 URL 후보 목록 → 정리된 절대 URL 목록. 못 쓸 값이면 빈 리스트.

    - `//cdn/...` 프로토콜 상대 → `https:` 부착, `/path` 상대 → base_url 기준 절대화
    - 상품 사진이 아닌 것(아이콘·배지·1px·placeholder) 제외 (`_NON_PRODUCT_IMG_HINTS`)
    - 순서 유지 중복 제거(첫 원소 = 대표 이미지). 최대 `limit` 개.

    ★ **URL 만 만든다. 파일은 내려받지 않는다.** 이미지는 브랜드 저작물이므로
      실제 마켓 업로드는 브랜드별 지재권 제외 정책을 통과한 뒤 별도 단계에서 한다.
    """
    from urllib.parse import urljoin, urlsplit

    out: list[str] = []
    seen: set[str] = set()
    for raw in (urls or []):
        u = str(raw or "").strip()
        if not u or u.startswith("data:"):
            continue
        if u.startswith("//"):
            u = "https:" + u
        elif not u.startswith(("http://", "https://")):
            if not base_url:
                continue           # 기준 URL 없이 상대경로는 못 만든다 → 버린다(추측 금지)
            u = urljoin(base_url, u)
        if not u.startswith(("http://", "https://")):
            continue
        path_l = urlsplit(u).path.lower()
        if any(h in path_l for h in _NON_PRODUCT_IMG_HINTS):
            continue
        if not any(e in path_l for e in _IMG_EXT_HINTS):
            continue               # 확장자로 이미지 확증 안 되면 제외(HTML 페이지 오수집 방지)
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= limit:
            break
    return out


# ─────────────────────────────────────────────────────────────────
# [2026-07-23 M4-4] 상세페이지 HTML 정리 (소싱처 공통)
# ─────────────────────────────────────────────────────────────────
# 통째로 지우는 태그 — 마켓 상세설명에 올라가면 안 되는 것들.
#   script/style/noscript : 소싱처 JS·추적 코드(마켓이 어차피 제거하거나 반려한다)
#   iframe/object/embed   : 외부 프레임 = 추적·광고 유입 경로
#   link/meta             : 상세 본문이 아니다
_DETAIL_DROP_TAGS = ("script", "style", "noscript", "iframe", "object", "embed",
                     "link", "meta", "form", "input", "button")


def sanitize_detail_html(fragment, base_url: str = "", *, limit: int = 200_000) -> str:
    """상세설명 영역 HTML → 마켓에 올릴 수 있는 정리본. 못 쓸 값이면 빈 문자열.

    - `_DETAIL_DROP_TAGS` 통째 제거(스크립트·추적 태그)
    - `on*` 이벤트 핸들러 속성 제거
    - `img/@src`·`a/@href` 상대경로 → 절대 URL (마켓 서버에서 열려야 하므로)
    - 텍스트도 이미지도 하나 없으면 빈 문자열(껍데기 div 만 남은 경우 = 상세 확인불가)

    인자는 BeautifulSoup Tag 또는 HTML 문자열 둘 다 받는다.
    """
    from urllib.parse import urljoin

    from bs4 import BeautifulSoup

    if fragment is None:
        return ""
    try:
        if isinstance(fragment, str):
            if not fragment.strip():
                return ""
            node = BeautifulSoup(fragment, "html.parser")
        else:
            # 원본 DOM 을 건드리지 않도록 복제해서 손질한다.
            node = BeautifulSoup(str(fragment), "html.parser")
    except Exception:
        return ""

    for tag in node.find_all(_DETAIL_DROP_TAGS):
        tag.decompose()
    for tag in node.find_all(True):
        for attr in [a for a in tag.attrs if str(a).lower().startswith("on")]:
            del tag[attr]
        if tag.name == "img":
            # 지연로딩 소싱처가 많다 — src 가 비면 data-src 계열을 대신 쓴다.
            src = (tag.get("src") or tag.get("data-src") or tag.get("data-original")
                   or tag.get("data-lazy-src") or "")
            src = str(src).strip()
            if src.startswith("//"):
                src = "https:" + src
            elif src and not src.startswith(("http://", "https://", "data:")) and base_url:
                src = urljoin(base_url, src)
            if src:
                tag["src"] = src
        elif tag.name == "a":
            href = str(tag.get("href") or "").strip()
            if href.startswith("//"):
                tag["href"] = "https:" + href
            elif href and not href.startswith(("http://", "https://", "#", "mailto:")) and base_url:
                tag["href"] = urljoin(base_url, href)

    html = str(node).strip()
    if not node.get_text(strip=True) and not node.find("img"):
        return ""                  # 알맹이 없음 = 상세 확인불가(빈 껍데기 저장 금지)
    return html[:limit]


# ─────────────────────────────────────────────────────────────────
# [2026-06-05 PERF] 크롤 속도·대역폭 최적화 — 불필요 리소스 차단
#   가격·재고 데이터는 document/script/xhr/fetch 로 오므로, 그 외
#   image/media/font 만 차단한다. → 추출 데이터 100% 동일, 다운로드만 절약.
#   (JS·CSS·API 응답은 절대 차단 안 함. 로그인 캡차 위험 회피 위해 상품조회 page 에만 적용.)
#
#   [2026-07-23 M4-4] 이미지 **URL 수집**과 이 차단은 무관하다 — 확인 결과:
#     이 라우트는 이미지 *바이트 다운로드*만 막고, DOM 의 `<img src>`·`data-src`·
#     JSON-LD·`__PRELOADED_STATE__` 문자열은 그대로 남는다(HTML 은 document 라 통과).
#     우리는 그 문자열만 읽으므로 차단을 풀 이유가 없다 → **그대로 둔다**(속도 유지).
#     푸는 게 필요해지는 경우는 단 하나 — 이미지 바이트를 실제로 받아야 할 때고,
#     그건 이번 범위가 아니다(지재권 정책 통과 후 별도 단계).
# ─────────────────────────────────────────────────────────────────
_BLOCK_RESOURCE_TYPES = ("image", "media", "font")


def block_heavy_resources(context_or_page) -> bool:
    """이미지/동영상/폰트 다운로드를 차단(가격·재고 데이터는 그대로 수신).

    크롤 페이지 또는 컨텍스트에 적용. 실패해도 크롤은 정상 진행(차단만 미적용).
    반환 True=적용됨. 사용: page = ctx.new_page(); block_heavy_resources(page)
    """
    try:
        def _route(route):
            try:
                if route.request.resource_type in _BLOCK_RESOURCE_TYPES:
                    route.abort()
                else:
                    route.continue_()
            except Exception:
                try:
                    route.continue_()
                except Exception:
                    pass
        context_or_page.route("**/*", _route)
        return True
    except Exception:
        return False


class AbstractCrawler(ABC):
    """모든 사이트 크롤러의 베이스."""
    source_name: str = ""

    @abstractmethod
    def fetch(self, product_url: str) -> CrawlResult:
        """상품 URL을 받아 옵션·가격·재고를 추출."""
        ...
