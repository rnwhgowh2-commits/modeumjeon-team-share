"""[B] 결정 결과 dataclass."""
from dataclasses import dataclass


@dataclass
class Decision:
    """단일 옵션 단일 마켓 가격 결정."""
    market: str
    canonical_sku: str
    price: int
    displayed: bool
    reason: str
    color_group_unified_at: int | None = None
