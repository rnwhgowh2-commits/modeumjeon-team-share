"""박스히어로 엑셀 파서.

박스히어로 export 형식: 19컬럼 (SKU, 바코드, 제품명, 구매가, 판매가, 카테고리,
브랜드, 모델명, 사이즈, 메모, 안전재고x4, 생성일, 수량x4).

색상은 별도 컬럼이 없어 제품명에서 추출:
  '르무통 레츠 브라운' → 브랜드='르무통' + 모델명='레츠' 떼고 → '브라운'
"""
from typing import Iterator
import openpyxl


COL_INDEX = {
    "sku": 0,
    "barcode": 1,
    "name": 2,
    "purchase_price": 3,
    "sale_price": 4,
    "category": 5,
    "brand": 6,
    "model_name": 7,
    "size": 8,
    "memo": 9,
    "stock_safety_total": 10,
    "stock_safety_default": 11,
    "stock_safety_disabled": 12,
    "stock_safety_overall": 13,
    "created_at": 14,
    "quantity": 15,
    "quantity_gross": 16,
    "quantity_default": 17,
    "quantity_disabled": 18,
}


def _extract_color(name: str, brand: str | None, model_name: str | None) -> str:
    """제품명에서 브랜드+모델명을 떼고 나머지를 색상 텍스트로."""
    text = (name or "").strip()
    if brand and text.startswith(brand):
        text = text[len(brand):].strip()
    if model_name and text.startswith(model_name):
        text = text[len(model_name):].strip()
    return text


def parse_boxhero_xlsx(xlsx_path: str) -> Iterator[dict]:
    """박스히어로 엑셀 → 정규화된 dict 레코드 yield."""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return

    for row in rows[1:]:
        if not row or row[COL_INDEX["sku"]] is None:
            continue

        sku = str(row[COL_INDEX["sku"]]).strip()
        name = str(row[COL_INDEX["name"]] or "").strip()
        brand = str(row[COL_INDEX["brand"]] or "").strip() or None
        model_name = str(row[COL_INDEX["model_name"]] or "").strip() or None
        size = row[COL_INDEX["size"]]
        size_str = str(size).strip() if size is not None else ""
        quantity = row[COL_INDEX["quantity"]] or 0
        purchase_price = row[COL_INDEX["purchase_price"]] or 0
        color_text = _extract_color(name, brand, model_name)

        yield {
            "sku": sku,
            "barcode": str(row[COL_INDEX["barcode"]] or "").strip(),
            "name": name,
            "brand": brand,
            "model_name": model_name,
            "size": size_str,
            "color_text": color_text,
            "quantity": int(quantity),
            "purchase_price": int(purchase_price),
        }
