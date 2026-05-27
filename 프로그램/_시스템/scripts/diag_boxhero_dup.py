"""박스히어로 SKU 중복 진단."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from shared.db import SessionLocal

with SessionLocal() as s:
    # 1. boxhero_sku 가 NULL/빈 옵션 비율
    total = s.execute(text("SELECT COUNT(*) FROM options")).scalar()
    bs_null = s.execute(text("SELECT COUNT(*) FROM options WHERE boxhero_sku IS NULL OR boxhero_sku = ''")).scalar()
    bs_set = total - bs_null
    print(f"전체 옵션: {total}  /  boxhero_sku 설정: {bs_set}  /  NULL: {bs_null}")

    # 2. boxhero_sku 중복 (같은 박스히어로 SKU 가 여러 옵션에 등록)
    dups = s.execute(text("""
        SELECT boxhero_sku, COUNT(*) cnt, STRING_AGG(canonical_sku, ', ') skus
        FROM options
        WHERE boxhero_sku IS NOT NULL AND boxhero_sku != ''
        GROUP BY boxhero_sku
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC LIMIT 20
    """)).fetchall()
    print(f"\nboxhero_sku 중복 (같은 박스히어로 SKU → 여러 우리 옵션): {len(dups)}")
    for d in dups[:10]:
        print(f"  {d[0]}: {d[1]}개 — {d[2][:120]}")

    # 3. canonical_sku == boxhero_sku 비율 (1:1 정책 준수)
    same = s.execute(text("SELECT COUNT(*) FROM options WHERE canonical_sku = boxhero_sku")).scalar()
    print(f"\ncanonical_sku == boxhero_sku (1:1 정책): {same} / {bs_set}")

    # 4. 모음전별 옵션 수 + boxhero 매핑 비율
    bundles = s.execute(text("""
        SELECT model_code, COUNT(*) total,
               SUM(CASE WHEN boxhero_sku IS NOT NULL AND boxhero_sku != '' THEN 1 ELSE 0 END) with_bs,
               SUM(CASE WHEN canonical_sku LIKE 'SKU-%' THEN 1 ELSE 0 END) new_format
        FROM options
        GROUP BY model_code
        ORDER BY total DESC LIMIT 10
    """)).fetchall()
    print(f"\n모음전 상위 10개 (옵션 수 + boxhero + 새 형식):")
    for b in bundles:
        print(f"  [{b[0]}] total={b[1]} with_boxhero={b[2]} SKU-format={b[3]}")
