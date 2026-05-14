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


class AbstractCrawler(ABC):
    """모든 사이트 크롤러의 베이스."""
    source_name: str = ""

    @abstractmethod
    def fetch(self, product_url: str) -> CrawlResult:
        """상품 URL을 받아 옵션·가격·재고를 추출."""
        ...
