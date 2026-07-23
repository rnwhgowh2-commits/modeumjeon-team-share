"""크롤러 추상 인터페이스.

각 사이트별 구현체는 fetch(product_url) -> CrawlResult 만 채우면 된다.
공통 후처리 (정규화, 매칭, 큐 적재)는 pipeline.py에서 담당.
"""
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)


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
    "/icon", "icon_", "_icon", "/btn", "btn_",
    "noimage", "no_image", "no-image", "dummy", "placeholder", "transparent.",
)
# ★ [2026-07-23 리뷰지적 I7] 아래 낱말은 **부분문자열로 보면 진짜 상품을 버린다.**
#   실측 오탐(DROP 됐던 것): `logo_tee_front.jpg` · `BIG_LOGO_HOODIE_1.jpg` ·
#   `BANNER_ITEM_1.jpg` — 패션에서 '로고 티셔츠/후디'는 아주 흔한 상품이다.
#   그렇다고 통째로 빼면 진짜 스킨 자산(`common/logo.png`·`/banner/summer.jpg`)이
#   대표이미지가 된다. → **경계를 준다**: 디렉터리 이름이 통째로 그 낱말이거나
#   (`/logo/…`·`/banner/…`), 파일명 몸통이 그 낱말(+구분자+숫자)일 때만 버린다
#   (`logo.png`·`logo2.png`·`banner_1.jpg`). 몸통이 여러 낱말이면 상품으로 본다.
_NON_PRODUCT_IMG_WORDS = ("logo", "banner", "sprite", "bnr")
_STEM_EXT_RE = re.compile(r"\.[a-z0-9]{2,5}$", re.I)
# 상품 사진이 절대 안 올라오는 호스트 — 쇼핑몰 솔루션의 **스킨/UI 자산** 전용 CDN.
#   `img.echosting.cafe24.com` : Cafe24 기본 스킨(확대 아이콘·'이미지 없음' 회색판).
#     ★ 실측 이력 — 이미지 요청을 abort 하면 Cafe24 `onerror` 가 상품 사진 src 를
#       이 호스트의 `thumb/img_product_big.gif` 로 바꿔 버린다. 라우트 쪽은 고쳤지만
#       (`block_heavy_resources`), 어떤 경로로든 새 나오면 마켓 대표이미지가
#       회색 네모가 되므로 여기서 한 번 더 막는다.
_NON_PRODUCT_IMG_HOSTS = ("img.echosting.cafe24.com",)
# 이미지로 볼 확장자. 쿼리스트링이 붙는 CDN 이 많아 '경로에 포함' 으로 본다.
_IMG_EXT_HINTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif")

# 스킴도 `//` 도 없이 **호스트로 시작**하는 주소. SSG JSON-LD 가 실제로 이렇게 준다
#   (예: `sitem.ssgcdn.com/58/80/93/item/1000809938058_i1_1200.jpg`, 2026-07-23 실측).
#   base_url 로 urljoin 하면 `https://www.ssg.com/sitem.ssgcdn.com/…` 라는 없는 주소가 된다.
#   그래서 '첫 조각이 진짜 호스트명처럼 생겼을 때만' https 를 붙인다 — `img/a.jpg` 같은
#   평범한 상대경로(첫 조각에 점이 없음)나 `photo.jpg/x`(마지막 라벨이 이미지 확장자)는
#   여기에 안 걸린다.
_BARE_HOST_RE = re.compile(r"^([a-z0-9][a-z0-9\-]*(?:\.[a-z0-9][a-z0-9\-]*)+)/", re.I)
# ★ [2026-07-23 리뷰지적 M9] 마지막 라벨은 **화이트리스트**로만 인정한다.
#   종전 규칙(`^[a-z]{2,10}$` − 이미지확장자)은 `view.do/a.jpg` 같은 **평범한 상대경로**를
#   호스트로 오인해 `https://view.do/a.jpg`(실재하는 남의 도메인)를 만들어 냈다.
#   상품 이미지 CDN 이 실제로 쓰는 TLD 만 넣는다 — 모르는 건 상대경로로 본다(추측 금지).
_KNOWN_TLDS = frozenset((
    "com", "net", "org", "co", "kr", "jp", "cn", "us", "io", "me", "tv",
    "info", "biz", "shop", "store", "cloud", "asia", "site", "xyz", "cc",
))


def _looks_like_bare_host(value: str) -> bool:
    """`sitem.ssgcdn.com/…` 처럼 스킴 없이 호스트로 시작하는 주소인가."""
    m = _BARE_HOST_RE.match(value)
    if not m:
        return False
    return m.group(1).rsplit(".", 1)[-1].lower() in _KNOWN_TLDS


def _is_non_product_img_path(path: str) -> bool:
    """경로(호스트 제외)가 '상품 사진이 아닌 것'으로 보이는가.

    `_NON_PRODUCT_IMG_HINTS`(부분문자열) + `_NON_PRODUCT_IMG_WORDS`(경계 있는 낱말).
    수집기(`build_image_urls`)와 상세 정제기(`sanitize_detail_html`)가 **같은 판정**을
    쓰도록 한 곳에 둔다 — 리뷰 지적 C2(상세엔 필터가 아예 없었다)의 근본 수정.
    """
    path_l = (path or "").lower()
    if any(h in path_l for h in _NON_PRODUCT_IMG_HINTS):
        return True
    segs = [s for s in path_l.split("/") if s]
    if not segs:
        return False
    stem = _STEM_EXT_RE.sub("", segs[-1])
    for w in _NON_PRODUCT_IMG_WORDS:
        if w in segs[:-1]:                                   # `/logo/…`·`/banner/…`
            return True
        if re.fullmatch(rf"{w}[\-_]?\d*", stem):             # `logo.png`·`banner_1.jpg`
            return True
    return False


def build_image_urls(urls, base_url: str = "", *, limit: int = 20) -> list[str]:
    """이미지 URL 후보 목록 → 정리된 절대 URL 목록. 못 쓸 값이면 빈 리스트.

    - `//cdn/...` 프로토콜 상대 → `https:` 부착, `/path` 상대 → base_url 기준 절대화
    - 상품 사진이 아닌 것(아이콘·배지·1px·placeholder) 제외 (`_NON_PRODUCT_IMG_HINTS`)
    - 순서 유지 중복 제거(첫 원소 = 대표 이미지). 최대 `limit` 개.

    ★ **URL 만 만든다. 파일은 내려받지 않는다.** 이미지는 브랜드 저작물이므로
      실제 마켓 업로드는 브랜드별 지재권 제외 정책을 통과한 뒤 별도 단계에서 한다.

    ★ [2026-07-23 리뷰지적 I3] `data:` placeholder 도 **후보로는 센다**. 지연로딩
      대체(`pick_img_src`)에 실패한 갤러리가 '애초에 후보 0'으로 보이면 아래 무음실패
      경고가 안 떠서, 대표이미지 0장 = 등록 차단이 로그 없이 지나간다.
    ★ [리뷰지적 M4] `limit` 초과로 잘렸으면 경고 한 줄(조용히 버리지 않는다).
    """
    from urllib.parse import urljoin, urlsplit

    out: list[str] = []
    seen: set[str] = set()
    candidates = 0            # 후보(빈 값 제외, data: placeholder 포함) — 조용한 실패 감지용
    truncated = 0             # limit 초과로 버린 사진 수 (M4)
    for raw in (urls or []):
        u = str(raw or "").strip()
        if not u:
            continue
        candidates += 1
        if u.startswith("data:"):
            continue          # placeholder — 세기는 하되 주소로는 못 쓴다 (I3)
        if u.startswith("//"):
            u = "https:" + u
        elif not u.startswith(("http://", "https://")) and _looks_like_bare_host(u):
            u = "https://" + u        # SSG JSON-LD 형태 (`sitem.ssgcdn.com/…`)
        elif not u.startswith(("http://", "https://")):
            if not base_url:
                continue           # 기준 URL 없이 상대경로는 못 만든다 → 버린다(추측 금지)
            u = urljoin(base_url, u)
        if not u.startswith(("http://", "https://")):
            continue
        _split = urlsplit(u)
        if _split.hostname and _split.hostname.lower() in _NON_PRODUCT_IMG_HOSTS:
            continue
        path_l = _split.path.lower()
        if _is_non_product_img_path(path_l):
            continue
        if not any(e in path_l for e in _IMG_EXT_HINTS):
            continue               # 확장자로 이미지 확증 안 되면 제외(HTML 페이지 오수집 방지)
        if u in seen:
            continue
        seen.add(u)
        if len(out) >= limit:
            truncated += 1     # 상한을 넘겨 버린 '진짜 사진' 개수 (M4)
            continue
        out.append(u)
    # ★ [2026-07-23 리뷰지적 I7] 조용한 실패 금지 — 후보가 있었는데 한 장도 안 남았다면
    #   필터 오탐일 수 있다(6마켓 전부 대표이미지 필수라 그대로 두면 등록이 막힌다).
    #   '애초에 후보가 0'인 소싱처(상세만 있는 곳)는 경고 대상이 아니다.
    if candidates and not out:
        _log.warning("[m4img] 이미지 후보 %d건이 전부 걸러졌다 — 필터 오탐 의심 base=%s 예시=%s",
                     candidates, base_url,
                     [str(u)[:120] for u in (urls or [])[:3]])
    # ★ [리뷰지적 M4] 상한 초과 = 뒷장을 버린 것이다. 조용히 버리지 않고 흔적을 남긴다.
    elif truncated:
        _log.warning("[m4img] 이미지가 상한 %d장을 넘어 %d장을 잘랐다 base=%s",
                     limit, truncated, base_url)
    return out


# 지연로딩 소싱처가 실주소를 숨겨 두는 속성들(우선순위 순).
#   `src` 는 1×1/2×2 base64 placeholder 라 **truthy 지만 쓸모없다** — 이걸 그냥 쓰면
#   상세는 백지, 갤러리는 0장이 된다(리뷰지적 I3).
_LAZY_IMG_SRC_ATTRS = ("ec-data-src", "data-src", "data-original",
                       "data-lazy-src", "data-echo")


def pick_img_src(tag) -> str:
    """`<img>` 태그에서 **실주소 하나**를 고른다. 없으면 빈 문자열.

    규칙(수집기·상세정리기 공통) — `src` 가 비었거나 `data:` placeholder 면
    `_LAZY_IMG_SRC_ATTRS` 를 순서대로 보고 첫 실주소를 쓴다.
    """
    try:
        src = str(tag.get("src") or "").strip()
    except Exception:
        return ""
    if src and not src.startswith("data:"):
        return src
    for attr in _LAZY_IMG_SRC_ATTRS:
        alt = str(tag.get(attr) or "").strip()
        if alt and not alt.startswith("data:"):
            return alt
    return src


# ─────────────────────────────────────────────────────────────────
# [2026-07-23 M4-4] 상세페이지 HTML 정리 (소싱처 공통)
# ─────────────────────────────────────────────────────────────────
# 통째로 지우는 태그 — 마켓 상세설명에 올라가면 안 되는 것들.
#   script/style/noscript : 소싱처 JS·추적 코드(마켓이 어차피 제거하거나 반려한다)
#   iframe/object/embed   : 외부 프레임 = 추적·광고 유입 경로
#   link/meta             : 상세 본문이 아니다
#   video/audio/source     : 마켓이 대부분 반려하고, `source` 는 추적 대체본 통로다
#   svg                    : 인라인 스크립트·외부참조가 숨을 수 있고 상품 사진이 아니다
_DETAIL_DROP_TAGS = ("script", "style", "noscript", "iframe", "object", "embed",
                     "link", "meta", "form", "input", "button",
                     "video", "audio", "source", "svg")
# 껍데기만 벗기는 태그(unwrap) — 안의 알맹이는 살린다.
#   a       : 🔴 **남의 몰 링크**. 마켓 상세에 타 쇼핑몰 링크를 심으면 판매금지·계정
#             제재 사유다. 종전 코드는 오히려 상대 href 를 절대화해 '작동하는 링크'로
#             만들었다(리뷰지적 C1, 2026-07-23 실측). 주소는 버리고 글만 남긴다.
#   picture : 통째로 지우면 그 안 상품 사진(`img`)까지 사라진다 — 껍데기만 벗는다.
_DETAIL_UNWRAP_TAGS = ("a", "picture")


def sanitize_detail_html(fragment, base_url: str = "", *, limit: int = 200_000) -> str:
    """상세설명 영역 HTML → 마켓에 올릴 수 있는 정리본. 못 쓸 값이면 빈 문자열.

    ★ **이 함수가 유일한 관문이다.** 여기서 나온 값은 `registration/compile_more.py`·
      `compile_coupang.py` 가 아무 검사 없이 마켓 spec 에 그대로 넣는다(옥션·G마켓·
      11번가·롯데온 상세설명 + 쿠팡 contentDetails). 즉 여기서 새는 것 = 마켓에 실린다.

    - `_DETAIL_DROP_TAGS` 통째 제거(스크립트·추적 태그·미디어)
    - `_DETAIL_UNWRAP_TAGS` 껍데기만 제거 — 특히 **`a` 는 주소를 통째로 버린다**
      (🔴 타 쇼핑몰 링크 = 판매금지·계정 제재. 리뷰지적 C1)
    - `on*` 이벤트 핸들러 속성 제거
    - `img/@src` 상대경로 → 절대 URL (마켓 서버에서 열려야 하므로)
    - **비상품 이미지 제거** — 수집기와 같은 판정(`_is_non_product_img_path` ·
      `_NON_PRODUCT_IMG_HOSTS`) + 1×1 크기표기 (🔴 추적픽셀. 리뷰지적 C2)
    - 텍스트도 **주소 있는** 이미지도 없으면 빈 문자열(= 상세 확인불가)
    - `limit` 초과 시 **마지막 태그 경계(`>`)까지만** 자른다(리뷰지적 I8)

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
    # HTML 주석 제거 — 소싱처 내부 메모(작업일자·담당자·A/B 분기)라 마켓 상세에 갈 게 아니다.
    from bs4 import Comment
    for c in node.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    # 🔴 [리뷰지적 C1] 링크 껍데기 벗기기 — 주소는 통째로 버리고 글·사진만 남긴다.
    #   `decompose` 가 아니라 `unwrap` 인 이유: 상세 본문 글이나 상품 사진이 링크 안에
    #   들어 있는 경우가 흔해, 통째로 지우면 상세가 반토막 난다.
    for tag in node.find_all(_DETAIL_UNWRAP_TAGS):
        tag.unwrap()
    _placeholders: list = []
    for tag in node.find_all(True):
        for attr in [a for a in tag.attrs if str(a).lower().startswith("on")]:
            del tag[attr]
        if tag.name == "img":
            # 지연로딩 소싱처가 많다. src 가 비었거나 **1px base64 placeholder** 면
            # (Cafe24 edibot 이 실제로 이렇게 준다 — 2026-07-23 라이브 확인)
            # data-src 계열 실주소를 대신 쓴다. 그대로 두면 마켓 상세가 백지가 된다.
            src = pick_img_src(tag)          # 수집기와 **같은 규칙**(I3)
            if src.startswith("//"):
                src = "https:" + src
            elif src and not src.startswith(("http://", "https://", "data:")) and base_url:
                src = urljoin(base_url, src)
            if src:
                tag["src"] = src
            if not src or src.startswith("data:"):
                _placeholders.append(tag)   # 실주소를 못 찾은 placeholder = 알맹이 아님
            elif _is_tracking_or_non_product_img(tag, src):
                _placeholders.append(tag)   # 🔴 추적픽셀·스킨자산 (리뷰지적 C2)

    for tag in _placeholders:
        tag.decompose()

    # ⏸ [2026-07-23 리뷰지적 C1] 살아남은 이미지에 **타 마켓 브랜딩**이 있으면 경고만.
    #   제거는 사장님 결정 전까지 하지 않는다(파일명 판정은 오탐 = 상품 사진 삭제).
    _warn_foreign_market_assets(node, base_url)

    html = str(node).strip()
    # 🔴 [리뷰지적 M10] `<img>` 가 있다고 알맹이가 아니다 — **주소가 있는** 이미지여야
    #   마켓 상세가 백지가 안 된다. (src 없는 img 는 위에서 이미 지웠지만 이중 확인)
    _has_img = any(str(i.get("src") or "").strip() for i in node.find_all("img"))
    if not node.get_text(strip=True) and not _has_img:
        return ""                  # 알맹이 없음 = 상세 확인불가(빈 껍데기 저장 금지)
    if len(html) <= limit:
        return html
    # 🔴 [리뷰지적 I8] 그냥 자르면 태그 **중간**이 잘려 깨진 HTML 이 4마켓 상세로 나간다
    #   (실측 꼬리: `...alt="상세이미지`). 마지막 태그 경계까지만 남긴다.
    cut = html.rfind(">", 0, limit)
    if cut < 0:
        _log.warning("[m4img] 상세 HTML 이 %d자를 넘는데 자를 태그 경계가 없다 — 버린다(len=%d)",
                     limit, len(html))
        return ""
    _log.warning("[m4img] 상세 HTML %d자 → %d자로 잘랐다(상한 %d, 태그 경계 기준)",
                 len(html), cut + 1, limit)
    return html[:cut + 1]


# ⏸ [2026-07-23 리뷰지적 C1] **사장님 판단 대기 — 지우지 말 것.**
#   소싱처 셀러가 상세에 심어 둔 **경쟁 마켓 기획전 배너**(실측: SSG
#   `department.ssg.com` 링크 + `ssg_banner.jpg` 그림). 링크(`a`)는 위에서 unwrap 으로
#   버리지만 **그림은 남는다** → 그 상세가 옥션·G마켓·11번가·롯데온 본문으로 올라가면
#   경쟁 마켓 브랜딩이 우리 리스팅에 실린다(판매금지·상품삭제 사유가 될 수 있다).
#   파일명 자동판정은 오탐(`ssg` 가 들어간 멀쩡한 상품 사진)이 나므로 **차단이 아니라
#   표면화**가 맞다 — 여기서는 경고 한 줄만 남기고 제거는 하지 않는다.
#   선택지·결정 대기: `docs/사장님_판단대기.md` 12번 「타 마켓 브랜딩 이미지」.
#
#   ★ 판정 규칙은 **여기 두지 않는다** — `crawlers/foreign_assets.py` 가 단일 진실
#     원천이다(등록 전 점검 화면·「상세에서 빼기」가 같은 판정을 쓴다). 규칙이 두 벌이면
#     화면에 안 뜨는데 로그만 경고하거나 그 반대가 난다(모순 금지).
def _warn_foreign_market_assets(node, base_url: str = "") -> list[dict]:
    """상세에 남은 **타 마켓 브랜딩 의심 자산**을 로그로 표면화. 지우지는 않는다.

    판정은 `foreign_assets.detect_foreign_market_assets` 에 위임한다.
    반환값은 감지 목록(호출부는 안 써도 된다 — 테스트·후속 표면화용).
    """
    try:
        from .foreign_assets import detect_foreign_market_assets
        hits = detect_foreign_market_assets(node, base_url)
    except Exception:
        return []                  # 표면화 실패가 상세 정리를 죽이면 안 된다
    if hits:
        _log.warning(
            "[m4img] 상세에 **타 마켓 브랜딩으로 보이는 이미지** %d장이 남아 있다 "
            "— 지우지 않았다(사장님 판단 대기 C1). base=%s 예시=%s",
            len(hits), base_url, [str(h.get("url"))[:120] for h in hits[:3]])
    return hits


def _is_tracking_or_non_product_img(tag, src: str) -> bool:
    """상세 안 `<img>` 가 추적픽셀·스킨자산인가 (🔴 리뷰지적 C2).

    종전엔 이 판정이 `build_image_urls` 에만 있어, 상세 HTML 안 추적픽셀
    (실측: `<img src="//log.ssfshop.com/px.gif?pid=123" width="1" height="1">`)이
    그대로 통과했다 → **우리 마켓 상세가 열릴 때마다 소싱처로 비콘**이 날아간다.
    """
    from urllib.parse import urlsplit

    try:
        sp = urlsplit(src)
    except Exception:
        return False
    if sp.hostname and sp.hostname.lower() in _NON_PRODUCT_IMG_HOSTS:
        return True
    if _is_non_product_img_path(sp.path):
        return True
    # 1×1(또는 0) 크기 표기 = 상품 사진일 수 없다. 경로가 멀쩡한 추적픽셀 위장을 잡는다.
    dims = []
    for attr in ("width", "height"):
        v = str(tag.get(attr) or "").strip().rstrip("px").strip()
        try:
            dims.append(int(float(v)))
        except (TypeError, ValueError):
            dims.append(None)
    if all(d is not None and d <= 2 for d in dims):
        return True
    return False


# ─────────────────────────────────────────────────────────────────
# [2026-06-05 PERF] 크롤 속도·대역폭 최적화 — 불필요 리소스 차단
#   가격·재고 데이터는 document/script/xhr/fetch 로 오므로, 그 외
#   image/media/font 만 차단한다. → 추출 데이터 100% 동일, 다운로드만 절약.
#   (JS·CSS·API 응답은 절대 차단 안 함. 로그인 캡차 위험 회피 위해 상품조회 page 에만 적용.)
#
#   🔴 [2026-07-23 M4-4] **이미지는 abort 하면 안 된다** — Playwright 실측으로 확인.
#     르무통(Cafe24) 상품 페이지의 `<img>` 에는 인라인 `onerror="this.src='…'"` 가 붙어
#     있다. abort 하면 브라우저가 **로드 실패로 보고 → onerror 가 실행 → src 가 회색
#     플레이스홀더(`img.echosting.cafe24.com/thumb/img_product_big.gif`)로 바뀐다.**
#     그 뒤에 DOM 을 읽으면 상품 사진 URL 이 아니라 전부 같은 플레이스홀더가 나온다
#     (실측: 대표 1 + 추가 5 = 6장 전부 오염). SSG 썸네일도 같은 onerror 패턴이다.
#     → 이미지는 abort 대신 **1×1 투명 GIF 로 즉시 fulfill** 한다. 요청은 '성공'으로
#       끝나 onerror 가 안 돌고 src 원본이 보존되며, 네트워크 전송량은 여전히 0
#       (43바이트를 로컬에서 돌려줄 뿐)이라 속도 이점도 그대로다.
#     ※ meta[og:image]·JSON-LD·`ec-data-src` 같은 **문자열 출처는 애초에 영향 없다**
#       (이미지 요청이 아니므로). 오염되는 건 실제로 로드되는 `<img src>` 뿐이다.
# ─────────────────────────────────────────────────────────────────
_BLOCK_RESOURCE_TYPES = ("image", "media", "font")
# abort 대신 이걸로 응답하는 리소스 (위 🔴 사유 참조)
_STUB_RESOURCE_TYPES = ("image",)
# 1×1 투명 GIF (43 bytes)
_STUB_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00!\xf9\x04\x01"
    b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


def block_heavy_resources(context_or_page) -> bool:
    """이미지/동영상/폰트 다운로드를 차단(가격·재고 데이터는 그대로 수신).

    - media/font : abort (그냥 버린다)
    - image      : **1×1 투명 GIF 로 fulfill** — abort 하면 사이트의 `onerror` 가
                   src 를 플레이스홀더로 바꿔 버려 이미지 URL 수집이 망가진다.
                   (위 모듈 주석의 🔴 항목이 실측 근거)

    크롤 페이지 또는 컨텍스트에 적용. 실패해도 크롤은 정상 진행(차단만 미적용).
    반환 True=적용됨. 사용: page = ctx.new_page(); block_heavy_resources(page)
    """
    try:
        def _route(route):
            try:
                rtype = route.request.resource_type
                if rtype in _STUB_RESOURCE_TYPES:
                    route.fulfill(status=200, content_type="image/gif", body=_STUB_GIF)
                elif rtype in _BLOCK_RESOURCE_TYPES:
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
