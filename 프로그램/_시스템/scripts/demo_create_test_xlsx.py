"""박스히어로 형식 테스트 엑셀 생성 — 시연용.

실제 모음전 옵션 SKU 일부에 fake 박스히어로 SKU + 재고 + 매입가 부여.
"""
import openpyxl
from pathlib import Path

# 박스히어로 19컬럼 헤더 (boxhero_xlsx.py COL_INDEX 순서)
HEADERS = [
    'SKU', '바코드', '제품명', '구매가', '판매가', '카테고리',
    '브랜드', '모델명', '사이즈', '메모',
    '안전재고합계', '안전재고기본', '안전재고비활성', '안전재고전체',
    '생성일', '수량', '수량합계', '수량기본', '수량비활성',
]

# 시연용 8개 옵션 — 메이트 그레이 4 사이즈 + 다크네이비 4 사이즈
DEMO_DATA = [
    # (boxhero_sku, name, size, qty, purchase_price)
    ('BH-MATE-GR-220', '르무통 메이트 그레이', 220, 12, 85000),
    ('BH-MATE-GR-225', '르무통 메이트 그레이', 225, 25, 85000),
    ('BH-MATE-GR-230', '르무통 메이트 그레이', 230, 38, 87000),
    ('BH-MATE-GR-235', '르무통 메이트 그레이', 235, 30, 87000),
    ('BH-MATE-NV-220', '르무통 메이트 다크네이비', 220,  8, 90000),
    ('BH-MATE-NV-225', '르무통 메이트 다크네이비', 225, 15, 90000),
    ('BH-MATE-NV-230', '르무통 메이트 다크네이비', 230, 22, 92000),
    ('BH-MATE-NV-235', '르무통 메이트 다크네이비', 235,  5, 92000),
]


def create_test_xlsx(out_path: str) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '박스히어로_재고'
    ws.append(HEADERS)
    for sku, name, size, qty, price in DEMO_DATA:
        ws.append([
            sku, sku, name, price, int(price * 1.30), '신발',
            '르무통', '메이트', size, '시연 데이터',
            5, 5, 0, 5,
            '2026-05-08', qty, qty, qty, 0,
        ])
    wb.save(out_path)
    return out_path


if __name__ == '__main__':
    out = Path(__file__).parent.parent / 'data' / 'TEST_boxhero_demo.xlsx'
    out.parent.mkdir(parents=True, exist_ok=True)
    p = create_test_xlsx(str(out))
    print(f'생성: {p}')
    print(f'레코드: {len(DEMO_DATA)}')
