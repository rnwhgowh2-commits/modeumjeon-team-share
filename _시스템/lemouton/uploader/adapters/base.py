"""마켓 어댑터 인터페이스."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class UploadResult:
    market: str
    canonical_sku: str
    success: bool
    http_status: int | None = None
    error: str | None = None


class MarketAdapter(ABC):
    market_name: str = ""

    @abstractmethod
    def update_price_and_stock(
        self,
        *,
        canonical_sku: str,
        market_product_id: str,
        market_option_id: str,
        new_price: int,
        new_stock: int,
    ) -> UploadResult:
        """단일 옵션의 가격·재고 업데이트.
        성공 시 UploadResult(success=True), 실패 시 (success=False, error=...)
        """
