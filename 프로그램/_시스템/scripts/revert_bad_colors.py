"""잘못된 color_display 변경 revert.

룰: color_display 길이 > color_code 길이 인 케이스 = raw 가 더 짧은데 정리 후 더 길어짐.
    이는 박스히어로 폴백이 raw 의 단일 단어 색상을 무시하고 다단어로 덮어쓴 잘못된 변경.
    color_display = color_code 로 복원.
단, color_code 가 '-' 이거나 빈 값이면 박스히어로 폴백이 정상 — 그대로.
"""
import sys
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        # 잘못된 변경 식별: color_display 가 color_code 보다 길고, color_code 가 의미 있는 단어
        rows = s.execute(text('''
            SELECT canonical_sku, color_code, color_display
            FROM options
            WHERE color_code IS NOT NULL AND color_code != '' AND color_code != '-'
              AND color_display IS NOT NULL AND color_display != color_code
              AND LENGTH(color_display) > LENGTH(color_code)
        ''')).fetchall()
        print(f'잘못된 변경 감지: {len(rows)}건')
        for r in rows[:30]:
            print(f'  {r[0]}: code="{r[1]}" display="{r[2]}" → revert')
        if len(rows) > 30:
            print(f'  ... +{len(rows)-30}건')

        # revert
        for r in rows:
            s.execute(text('UPDATE options SET color_display = :c WHERE canonical_sku = :s'),
                      {'c': r[1], 's': r[0]})
        s.commit()
        print(f'\n✓ revert 완료: {len(rows)}건')
    finally:
        s.close()


if __name__ == '__main__':
    main()
