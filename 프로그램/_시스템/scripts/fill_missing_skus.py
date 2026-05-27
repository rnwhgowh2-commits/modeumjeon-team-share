"""boxhero_sku 없는 옵션에 임의 SKU 생성·채우기.

룰:
- SKU 형식: SKU-XXXXXXXX (영숫자 대문자 8자)
- 기존 boxhero_sku 와 중복 X
"""
import sys
import secrets
import string
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def gen_unique_sku(existing: set) -> str:
    """unique SKU 생성."""
    while True:
        suffix = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        sku = f'SKU-{suffix}'
        if sku not in existing:
            existing.add(sku)
            return sku


def main():
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        # 기존 boxhero_sku 모두 (충돌 회피)
        existing = set()
        for r in s.execute(text("SELECT boxhero_sku FROM options WHERE boxhero_sku IS NOT NULL AND boxhero_sku != ''")).fetchall():
            existing.add(r[0])
        # canonical_sku 도 충돌 회피
        for r in s.execute(text("SELECT canonical_sku FROM options WHERE canonical_sku LIKE 'SKU-%'")).fetchall():
            existing.add(r[0])
        print(f'기존 SKU pool: {len(existing)}')

        # boxhero_sku 없는 옵션
        rows = s.execute(text('''
            SELECT canonical_sku, model_code, color_code, color_display, size_code, is_active
            FROM options
            WHERE boxhero_sku IS NULL OR boxhero_sku = ''
            ORDER BY model_code, color_code, size_code
        ''')).fetchall()
        print(f'대상: {len(rows)}건')

        updated = []
        for r in rows:
            new_sku = gen_unique_sku(existing)
            s.execute(text('UPDATE options SET boxhero_sku = :bs WHERE canonical_sku = :cs'),
                      {'bs': new_sku, 'cs': r[0]})
            updated.append((r[0], new_sku, r[1], r[2], r[3], r[4], r[5]))

        s.commit()

        print(f'\n✓ SKU 생성·채움: {len(updated)}건')
        print()
        print('=== 샘플 (15건) ===')
        for csku, new_sku, mc, cc, cd, sz, active in updated[:15]:
            print(f'  {csku[:30]:<30} → {new_sku} ({mc} {cd or cc} {sz}) active={active}')

        # 모델별 카운트
        from collections import Counter
        mc_cnt = Counter(u[2] for u in updated)
        print()
        print('=== 모델별 ===')
        for mc, c in mc_cnt.most_common(15):
            print(f'  {mc}: {c}건')
    finally:
        s.close()


if __name__ == '__main__':
    main()
