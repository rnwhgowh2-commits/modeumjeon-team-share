"""박스히어로 통합 서비스 — API/엑셀 dual mode.

두 채널 모두 동일한 정규화된 dict 리스트를 반환. 후속 모듈은 mode 무관하게 동일하게 사용.
"""
from typing import Literal

from .boxhero_api import BoxHeroClient
from .boxhero_xlsx import parse_boxhero_xlsx, _extract_color


def _normalize_api_item(item: dict) -> dict:
    """BoxHero API 응답 item → boxhero_xlsx와 동일한 형식."""
    name = item.get("name", "") or ""
    brand = item.get("brand")
    model_name = item.get("modelName")
    return {
        "sku": item.get("sku", ""),
        "barcode": item.get("barcode", ""),
        "name": name,
        "brand": brand,
        "model_name": model_name,
        "size": str(item.get("size", "")).strip(),
        "color_text": _extract_color(name, brand, model_name),
        "quantity": int(item.get("currentQuantity", 0) or 0),
        "purchase_price": int(item.get("purchasePrice", 0) or 0),
    }


def fetch_boxhero_records(
    mode: Literal["api", "excel"],
    *,
    api_token: str | None = None,
    excel_path: str | None = None,
) -> list[dict]:
    """박스히어로에서 사입품 데이터 가져오기.
    반환: 표준 dict 리스트 (sku, brand, model_name, size, color_text, quantity, ...).

    mode='excel': excel_path 필수
    mode='api':   api_token 필수
    """
    if mode == "excel":
        if not excel_path:
            raise ValueError("excel_path is required for mode=excel")
        return list(parse_boxhero_xlsx(excel_path))

    if mode == "api":
        if not api_token:
            raise ValueError("api_token is required for mode=api")
        client = BoxHeroClient(api_token)
        return [_normalize_api_item(item) for item in client.list_items()]

    raise ValueError(f"unsupported mode: {mode}")
