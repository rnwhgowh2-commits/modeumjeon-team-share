"""모델 분리 — 잔스포츠 슈퍼브레이크 플러스 + 빔즈 음식 키링 (음식별).

기존 row 복제로 NOT NULL 안전 처리.
"""
import sys
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def clone_model(s, source_mc, new_mc, new_display, new_raw):
    """기존 모델 row 복제 → 새 model_code 로 INSERT."""
    row = s.execute(text('SELECT * FROM models WHERE model_code = :m'),
                    {'m': source_mc}).fetchone()
    if not row:
        return False
    data = dict(row._mapping)
    data['model_code'] = new_mc
    data['model_name_display'] = new_display
    data['model_name_raw'] = new_raw
    cols = ', '.join(data.keys())
    placeholders = ', '.join(f':{k}' for k in data.keys())
    s.execute(text(f'INSERT INTO models ({cols}) VALUES ({placeholders}) ON CONFLICT (model_code) DO NOTHING'),
              data)
    return True


def split_supermarket_plus(s):
    print('=== 잔스포츠 슈퍼브레이크 플러스 분리 ===')
    rows = s.execute(text('''
        SELECT canonical_sku, color_code, color_display
        FROM options
        WHERE model_code = '잔스포츠_슈퍼브레이크'
    ''')).fetchall()
    plus_opts = [r for r in rows if r[2] and '플러스' in r[2]]
    if not plus_opts:
        print('  (이미 분리됨)')
        return

    # 새 모델 생성
    clone_model(s, '잔스포츠_슈퍼브레이크', '잔스포츠_슈퍼브레이크_플러스',
                '슈퍼브레이크 플러스', '잔스포츠 슈퍼브레이크 플러스')

    # 옵션 이전 + 색상 정리
    for r in plus_opts:
        new_color = r[2].replace('플러스 ', '').replace('플러스', '').strip() or r[2]
        new_code = (r[1] or '').replace('플러스 ', '').replace('플러스', '').strip() or r[1]
        s.execute(text('''
            UPDATE options
            SET model_code = '잔스포츠_슈퍼브레이크_플러스',
                color_display = :cd, color_code = :cc
            WHERE canonical_sku = :s
        '''), {'cd': new_color[:64], 'cc': new_code[:64], 's': r[0]})
        print(f'  {r[0]}: "{r[2]}" → 모델 이전, 색상="{new_color}"')


def split_food_keyring(s):
    print()
    print('=== 빔즈 음식 키링 — 음식별 모델 분리 ===')
    rows = s.execute(text('''
        SELECT canonical_sku, color_code, color_display, boxhero_sku
        FROM options
        WHERE model_code = '빔즈_빔즈_음식_키링'
        ORDER BY color_display
    ''')).fetchall()
    print(f'  대상: {len(rows)}건')

    for r in rows:
        food = (r[2] or r[1] or '').strip()
        if not food:
            continue
        # 새 model_code = 빔즈_음식_키링_<음식> (공백 → _)
        food_safe = food.replace(' ', '_')
        new_mc = f'빔즈_음식_키링_{food_safe}'
        new_display = f'음식 키링 {food}'
        new_raw = f'빔즈 음식 키링 {food}'

        clone_model(s, '빔즈_빔즈_음식_키링', new_mc, new_display, new_raw)

        # 옵션 이전 + 색상 "-"
        s.execute(text('''
            UPDATE options
            SET model_code = :mc,
                color_display = '-', color_code = '-'
            WHERE canonical_sku = :s
        '''), {'mc': new_mc, 's': r[0]})
        print(f'  {r[0]}: 음식="{food}" → 모델="{new_mc}"')


def main():
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        split_supermarket_plus(s)
        split_food_keyring(s)
        s.commit()
        print('\n✓ 분리 완료')

        # 검증
        print()
        print('=== 검증 ===')
        for mc in ['잔스포츠_슈퍼브레이크', '잔스포츠_슈퍼브레이크_플러스']:
            opts = s.execute(text('''
                SELECT canonical_sku, color_display FROM options WHERE model_code = :m
            '''), {'m': mc}).fetchall()
            print(f'\n[{mc}] {len(opts)}건')
            for o in opts:
                print(f'  {o[0]}: 색상="{o[1]}"')

        # 빔즈 음식 키링 — 분리 결과
        food_models = s.execute(text('''
            SELECT model_code, model_name_display, (SELECT COUNT(*) FROM options o WHERE o.model_code = m.model_code) cnt
            FROM models m
            WHERE model_code LIKE '빔즈_음식_키링_%'
            ORDER BY model_code
        ''')).fetchall()
        print(f'\n[빔즈 음식 키링 분리됨] {len(food_models)}모델')
        for fm in food_models:
            print(f'  {fm[0]}: "{fm[1]}" ({fm[2]}옵션)')

        # 원본 모델에 남은 옵션
        remaining = s.execute(text('''
            SELECT COUNT(*) FROM options WHERE model_code = '빔즈_빔즈_음식_키링'
        ''')).scalar()
        print(f'\n원본 빔즈_빔즈_음식_키링 남은 옵션: {remaining}')
    finally:
        s.close()


if __name__ == '__main__':
    main()
