"""sku 분포 진단."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from shared.db import SessionLocal

with SessionLocal() as s:
    total = s.execute(text("SELECT COUNT(*) FROM options")).scalar()
    old_with_av = s.execute(text("SELECT COUNT(*) FROM options WHERE canonical_sku NOT LIKE 'SKU-%' AND axis_values_json IS NOT NULL AND axis_values_json != ''")).scalar()
    new_with_av = s.execute(text("SELECT COUNT(*) FROM options WHERE canonical_sku LIKE 'SKU-%' AND axis_values_json IS NOT NULL AND axis_values_json != ''")).scalar()
    old_no_av = s.execute(text("SELECT COUNT(*) FROM options WHERE canonical_sku NOT LIKE 'SKU-%' AND (axis_values_json IS NULL OR axis_values_json = '')")).scalar()
    new_no_av = s.execute(text("SELECT COUNT(*) FROM options WHERE canonical_sku LIKE 'SKU-%' AND (axis_values_json IS NULL OR axis_values_json = '')")).scalar()
    print(f"total: {total}")
    print(f"  old (str-cs) + axis_values: {old_with_av}")
    print(f"  new (SKU-)   + axis_values: {new_with_av}")
    print(f"  old           - axis_values: {old_no_av}")
    print(f"  new           - axis_values: {new_no_av}")

    # 르무통_메이트 확인
    r = s.execute(text("""
        SELECT canonical_sku, color_code, size_code,
               CASE WHEN axis_values_json IS NULL OR axis_values_json='' THEN 'NULL' ELSE 'YES' END as av,
               is_active
        FROM options
        WHERE model_code = '르무통_메이트' AND color_code = '오렌지' AND size_code IN ('260', '270')
    """)).fetchall()
    print(f"\n르무통_메이트 오렌지 260/270 옵션:")
    for x in r:
        print(f"  {x[0]} | color={x[1]} size={x[2]} | axis_values={x[3]} | is_active={x[4]}")

    # 새 sku 샘플
    r2 = s.execute(text("SELECT canonical_sku, color_code, size_code, axis_values_json, is_active FROM options WHERE canonical_sku LIKE 'SKU-%' LIMIT 5")).fetchall()
    print(f"\n새 sku 샘플 (있다면):")
    for x in r2:
        print(f"  {x[0]} | color={x[1]} size={x[2]} | av_json={x[3]} | is_active={x[4]}")
