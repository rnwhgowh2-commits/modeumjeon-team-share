"""크롤러 추상 인터페이스.

각 사이트별 구현체는 fetch(product_url) -> CrawlResult 만 채우면 된다.
공통 후처리 (정규화, 매칭, 큐 적재)는 pipeline.py에서 담당.
"""
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


# ─────────────────────────────────────────────────────────────────
# [2026-06-05 PERF] 크롤 속도·대역폭 최적화 — 불필요 리소스 차단
#   가격·재고 데이터는 document/script/xhr/fetch 로 오므로, 그 외
#   image/media/font 만 차단한다. → 추출 데이터 100% 동일, 다운로드만 절약.
#   (JS·CSS·API 응답은 절대 차단 안 함. 로그인 캡차 위험 회피 위해 상품조회 page 에만 적용.)
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
