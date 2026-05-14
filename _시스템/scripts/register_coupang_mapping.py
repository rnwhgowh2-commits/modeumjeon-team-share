"""[등록] 쿠팡 sellerProductId 1개 → 36 옵션 자동 매핑.

- GET seller-products/{sellerProductId}
- 응답 items[] 에서 (itemName, vendorItemId) 추출
- 시스템 옵션 (canonical_sku) 의 (color_code, size_code) 와 문자열 매칭
- DB 등록: model.coupang_product_id (productId), model.coupang_seller_product_id, options.coupang_option_id
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

import sqlite3
from shared.platforms.coupang.products import get_product

MODEL_CODE = "르무통 클래식"
SELLER_PRODUCT_ID = 16166577423


def normalize_color(s: str) -> str:
    """'블랙(블랙아웃솔)' ↔ '블랙블랙' 정규화."""
    s = s.replace(' ', '').replace('(', '').replace(')', '')
    # 시스템 표기 → 쿠팡 표기 매핑
    s = s.replace('블랙블랙아웃솔', '블랙블랙')
    s = s.replace('블랙화이트아웃솔', '블랙화이트')
    return s


def normalize_size(s: str) -> str:
    m = re.search(r'(\d{3})', str(s))
    return m.group(1) if m else str(s)


def main():
    print(f"[1] 쿠팡 GET sellerProductId={SELLER_PRODUCT_ID}")
    p = get_product(SELLER_PRODUCT_ID)
    seller_name = (p or {}).get('sellerProductName', '')
    product_id = (p or {}).get('productId')
    items = (p or {}).get('items') or []
    print(f"    상품명: {seller_name[:60]}")
    print(f"    productId: {product_id}")
    print(f"    옵션 수: {len(items)}건")

    # 쿠팡 옵션 → (color, size) 인덱스
    coupang_idx = {}
    for it in items:
        nm = it.get('itemName', '').strip()
        # "블랙블랙 230" 또는 "그레이 230" 형식
        m = re.match(r'^(.+?)\s+(\d{3})\s*$', nm)
        if not m:
            continue
        color_raw, size = m.group(1).strip(), m.group(2)
        color_norm = normalize_color(color_raw)
        coupang_idx[(color_norm, size)] = {
            'vendor_item_id': it.get('vendorItemId'),
            'item_name': nm,
            'price': it.get('salePrice'),
        }
    print(f"    쿠팡 인덱스: {len(coupang_idx)}건")

    # DB 옵션 매칭
    conn = sqlite3.connect(_ROOT / 'data' / 'lemouton.db')
    cur = conn.cursor()
    cur.execute("SELECT canonical_sku, color_code, size_code FROM options WHERE model_code=?", (MODEL_CODE,))
    sys_opts = cur.fetchall()
    print(f"\n[2] 시스템 옵션 매칭")
    matched = 0
    unmatched = []
    updates = []
    for sku, color, size in sys_opts:
        c_norm = normalize_color(color)
        s_norm = normalize_size(size)
        coup = coupang_idx.get((c_norm, s_norm))
        if coup:
            matched += 1
            updates.append((coup['vendor_item_id'], sku))
        else:
            unmatched.append((sku, color, size, c_norm, s_norm))
    print(f"    매칭: {matched}/{len(sys_opts)}")
    if unmatched:
        print(f"    미매칭 {len(unmatched)}건:")
        for x in unmatched[:5]:
            print(f"      sku={x[0]} (시스템 {x[1]}/{x[2]} → norm {x[3]}/{x[4]})")

    print(f"\n[3] DB 등록 (sellerProductId={SELLER_PRODUCT_ID}, productId={product_id})")
    cur.execute("UPDATE models SET coupang_product_id=?, coupang_seller_product_id=? WHERE model_code=?",
                (str(product_id), str(SELLER_PRODUCT_ID), MODEL_CODE))
    print(f"    model 업데이트: {cur.rowcount}건")
    n_opt = 0
    for vid, sku in updates:
        cur.execute("UPDATE options SET coupang_option_id=? WHERE canonical_sku=?",
                    (str(vid), sku))
        n_opt += cur.rowcount
    print(f"    options 업데이트: {n_opt}건")
    conn.commit()
    conn.close()
    print("\n✅ 매핑 등록 완료")


if __name__ == "__main__":
    main()
