"""color_display 일괄 정리 v2 — 모델명 strip + 박스히어로 제품명 fallback.

다단계:
1. color_display 가 model_name_display 로 시작 → strip
2. 정규화 매칭 (공백·하이픈·괄호·콜론 무시)
3. 박스히어로 제품명에서 brand+model 빼고 색상 추출 → fallback
4. 결과가 더 짧고 의미 있을 때만 적용
"""
import sys
from pathlib import Path
import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BX_PATH = Path(r'C:\Users\seung\Downloads\Items_Export_99LAB_2026-05-27T21-41-37.xlsx')


def normalize(s):
    if not s:
        return ''
    s = s.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    s = s.replace(':', '').replace('/', '').lower()
    return s


def strip_prefix(text, prefix):
    """text 에서 prefix 정확/정규화 매칭으로 strip. 안 되면 None."""
    if not text or not prefix:
        return None
    raw = text.strip()
    # 1. 정확
    if raw.startswith(prefix):
        rest = raw[len(prefix):].strip().lstrip('-:/ ').strip()
        return rest if rest else None
    # 2. 정규화
    norm_t = normalize(raw)
    norm_p = normalize(prefix)
    if not norm_p or not norm_t.startswith(norm_p):
        return None
    consumed = 0
    cut_idx = len(raw)
    for i, ch in enumerate(raw):
        if consumed >= len(norm_p):
            cut_idx = i
            break
        if normalize(ch):
            consumed += 1
    rest = raw[cut_idx:].strip().lstrip('-:/ ').strip()
    return rest if rest else None


def extract_color(raw_color, model_name_display, model_name_raw, brand, bx_product):
    """다단계로 색상 추출. 가장 짧고 의미 있는 결과 선택."""
    candidates = [raw_color]  # 원본 포함

    # color_display 에서 model strip
    for mn in [model_name_display, model_name_raw]:
        if mn:
            r = strip_prefix(raw_color, mn)
            if r:
                candidates.append(r)
    # brand+model 도 시도
    if brand and model_name_display:
        bm = f'{brand} {model_name_display}'
        r = strip_prefix(raw_color, bm)
        if r:
            candidates.append(r)

    # 박스히어로 제품명 fallback
    if bx_product:
        s = bx_product.strip()
        # (W) 보존
        prefix = ''
        if s.startswith('(W)'):
            prefix, s = '(W) ', s[3:].strip()
        # brand 제거
        if brand:
            r = strip_prefix(s, brand)
            if r:
                s = r
        # model 제거
        for mn in [model_name_display, model_name_raw]:
            if mn:
                r = strip_prefix(s, mn)
                if r:
                    s = r
                    break
        s = s.strip(' -:/').strip()
        if s and s != raw_color:
            candidates.append(s)

    # 가장 짧으면서 비어있지 않은 것 선택
    valid = [c for c in candidates if c and c.strip()]
    if not valid:
        return raw_color
    # 길이 기준 정렬, 단 너무 짧으면 (1자) 제외
    valid_filtered = [c for c in valid if len(c) >= 2]
    if not valid_filtered:
        return raw_color
    valid_filtered.sort(key=lambda x: (len(x), x))
    return valid_filtered[0]


def main():
    # 박스히어로
    bx_wb = openpyxl.load_workbook(BX_PATH, data_only=True)
    bx_ws = bx_wb['BoxHero']
    bx_hdr = [c.value for c in bx_ws[1]]
    bx_rows = [dict(zip(bx_hdr, r)) for r in bx_ws.iter_rows(min_row=2, values_only=True)]
    bx_by_sku = {r['SKU']: r for r in bx_rows if r.get('SKU')}

    from sqlalchemy.orm import joinedload
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option

    s = SessionLocal()
    try:
        items = s.query(Option).options(joinedload(Option.model)).all()
        print(f'대상 옵션: {len(items)}')

        updates = []
        for o in items:
            if not o.model:
                continue
            mnd = (o.model.model_name_display or '').strip()
            mnr = (o.model.model_name_raw or '').strip()
            brand = (o.model.brand or '').strip()
            raw_color = (o.color_display or o.color_code or '').strip()
            if not raw_color:
                continue
            bx_product = ''
            if o.boxhero_sku:
                bx = bx_by_sku.get(o.boxhero_sku)
                if bx:
                    bx_product = (bx.get('제품명') or '').strip()

            new_color = extract_color(raw_color, mnd, mnr, brand, bx_product)
            if new_color != raw_color and new_color:
                updates.append((o.canonical_sku, raw_color, new_color, o.model_code))
                o.color_display = new_color[:64]

        s.commit()

        print(f'정리 완료: {len(updates)}건')
        print()
        print('=== 정리 결과 (모델별 그룹) ===')
        from collections import defaultdict
        by_model = defaultdict(list)
        for sku, before, after, mc in updates:
            by_model[mc].append((sku, before, after))
        for mc in sorted(by_model.keys())[:30]:
            print(f'\n[{mc}] {len(by_model[mc])}건')
            for sku, before, after in by_model[mc][:5]:
                print(f'  "{before}" → "{after}"')

        return updates
    finally:
        s.close()


if __name__ == '__main__':
    main()
