"""color_display 일괄 정리 — 모델명이 색상에 통째 포함된 케이스 strip.

규칙:
1. 정확 매칭: raw_color.startswith(model_name) → strip
2. 정규화 매칭: 공백·하이픈·괄호·콜론 무시 비교
3. model_name_display 시도 후, model_name_raw 도 시도
4. 결과가 비면 변경 안 함 (단일 토큰 색상 보호)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def normalize(s):
    if not s:
        return ''
    s = s.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    s = s.replace(':', '').replace('/', '').lower()
    return s


def strip_model_prefix(color, model_name):
    """색상에서 모델명 prefix 제거."""
    if not color or not model_name:
        return color
    raw = color.strip()
    # 1. 정확 매칭
    if raw.startswith(model_name):
        rest = raw[len(model_name):].strip()
        return rest if rest else raw  # 비면 원본 유지
    # 2. 정규화 매칭
    norm_c = normalize(raw)
    norm_m = normalize(model_name)
    if not norm_m or not norm_c.startswith(norm_m):
        return raw
    # raw 글자 단위로 norm_m 길이만큼 자르기
    consumed = 0
    cut_idx = len(raw)
    for i, ch in enumerate(raw):
        if consumed >= len(norm_m):
            cut_idx = i
            break
        if normalize(ch):  # 의미 있는 문자
            consumed += 1
    rest = raw[cut_idx:].strip().lstrip('-:/').strip()
    return rest if rest else raw


def main(dry_run=False):
    from sqlalchemy.orm import joinedload
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option

    s = SessionLocal()
    try:
        items = s.query(Option).options(joinedload(Option.model)).all()
        print(f'대상 옵션: {len(items)}')

        updates = []  # (sku, before, after)
        for o in items:
            if not o.model:
                continue
            mnd = (o.model.model_name_display or '').strip()
            mnr = (o.model.model_name_raw or '').strip()
            # raw_color: color_display 우선 (없으면 color_code)
            raw_color = (o.color_display or o.color_code or '').strip()
            if not raw_color:
                continue
            new_color = raw_color
            # mnd 로 시도
            if mnd:
                stripped = strip_model_prefix(raw_color, mnd)
                if stripped != raw_color and stripped:
                    new_color = stripped
            # mnr 로도 시도 (mnd 와 다르면)
            if new_color == raw_color and mnr and mnr != mnd:
                stripped = strip_model_prefix(raw_color, mnr)
                if stripped != raw_color and stripped:
                    new_color = stripped
            # 브랜드 + 모델명 형태 (\"잔스포츠 슈퍼브레이크 ...\" → \"슈퍼브레이크 ...\" 강제)
            if new_color == raw_color and o.model.brand:
                brand_model = f'{o.model.brand} {mnd}'.strip()
                if brand_model != mnd:
                    stripped = strip_model_prefix(raw_color, brand_model)
                    if stripped != raw_color and stripped:
                        new_color = stripped

            if new_color != raw_color:
                updates.append((o.canonical_sku, raw_color, new_color))
                if not dry_run:
                    o.color_display = new_color[:64]

        if not dry_run:
            s.commit()

        print(f'정리 대상: {len(updates)}건')
        print()
        print('=== 샘플 (최대 30건) ===')
        for sku, before, after in updates[:30]:
            print(f'  {sku}: "{before}" → "{after}"')

        # 모델별 카운트
        from collections import Counter
        model_changes = Counter()
        for sku, _, _ in updates:
            o = next((x for x in items if x.canonical_sku == sku), None)
            if o:
                model_changes[o.model_code] += 1
        print()
        print('=== 모델별 변경 카운트 (상위 20) ===')
        for mc, cnt in model_changes.most_common(20):
            print(f'  {mc}: {cnt}건')

        return updates
    finally:
        s.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    main(dry_run=args.dry_run)
