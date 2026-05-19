"""제품 표시명·색상 정리 헬퍼 — 모든 라우트가 import.

원칙:
- 제품명 = '브랜드 모델명' (색상 X, 브랜드 중복 X, 색상 끝 strip)
- 색상 = LCP strip 후 (한가지면 'ONE Color')
- 단일 SKU 표시도 동일 로직 (그룹 없으면 LCP 생략, brand-strip 만)

사용처:
- 리스트 뷰 (home, data_items, matrix, sku_mapping 등) → `compute_display_maps()`
- 단일 SKU 뷰 (inbound/outbound/move detail, popover 등) → `format_pname_single()` + `format_color_single()`
- Jinja 필터 — `app.py` 에서 등록 → 템플릿에서 `{{ opt | display_pname }}` 식으로 사용 가능
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def lcp_words(strs: list[str]) -> str:
    """단어 경계까지 LCP 추출 (마지막 단어 미완성 시 잘라냄)."""
    if len(strs) < 2:
        return ''
    ss = sorted(strs)
    first, last = ss[0], ss[-1]
    i = 0
    while i < len(first) and i < len(last) and first[i] == last[i]:
        i += 1
    cp = first[:i]
    while cp and not cp[-1].isspace():
        cp = cp[:-1]
    return cp.strip()


def strip_brand_tokens(name: str, brand: str) -> str:
    """이름 안의 brand 토큰 모두 제거 (단어 경계 기준). 다중 공백 정리.

    예: '(W) 나이키 코르테즈 텍스타일' + '나이키' → '(W) 코르테즈 텍스타일'
    """
    if not name or not brand:
        return name or ''
    tokens = name.split()
    tokens = [t for t in tokens if t != brand]
    out = ' '.join(tokens).strip()
    while '  ' in out:
        out = out.replace('  ', ' ')
    return out


def format_pname_single(brand: str | None, name: str | None, *, fallback: str = '') -> str:
    """단일 SKU 의 제품명 = brand + (name 안의 brand 토큰 제거).

    그룹 LCP 없이도 brand 중복 제거. 매트릭스/리스트가 아닌 단일 표시 화면용.
    """
    brand_v = (brand or '').strip()
    name_v = (name or '').strip()
    if not name_v:
        return fallback
    cleaned_name = strip_brand_tokens(name_v, brand_v) if brand_v else name_v
    if brand_v:
        return f'{brand_v} {cleaned_name}'.strip()
    return cleaned_name


def format_color_single(raw: str | None, *, pname: str | None = None) -> str:
    """단일 SKU 의 색상 표시 — 빈값 / pname 와 동일 → 'ONE Color'."""
    c = (raw or '').strip()
    if not c:
        return 'ONE Color'
    if pname and c == pname.strip():
        return 'ONE Color'
    return c


def compute_display_maps(
    options: list[Any],
    *,
    get_sku=lambda o: o.canonical_sku,
    get_brand=lambda o: (o.model.brand if o.model else '') or '',
    get_model_code=lambda o: o.model_code or '',
    get_model_name=lambda o: (o.model.model_name_display or o.model.model_name_raw if o.model else '') or '',
    get_color=lambda o: (o.color_display or o.color_code or ''),
    one_color_label: str = 'ONE Color',
) -> tuple[dict[str, str], dict[str, str]]:
    """리스트 뷰용 — LCP·brand-strip 일괄 계산.

    Returns:
        (cleaned_color, display_pname) — 각각 {sku: 정리된 값}
    """
    # 1) model_code 그룹별 color 모아서 LCP prefix 추출
    color_by_model: dict[str, list[str]] = defaultdict(list)
    for opt in options:
        raw_c = (get_color(opt) or '').strip()
        mc = get_model_code(opt) or ''
        if raw_c and mc:
            color_by_model[mc].append(raw_c)

    model_lcp: dict[str, str] = {}
    for mc, colors in color_by_model.items():
        cp = lcp_words(colors)
        if cp and len(cp) >= 2:
            model_lcp[mc] = cp

    # 2) 각 옵션의 cleaned_color + display_pname 계산
    cleaned_color: dict[str, str] = {}
    display_pname: dict[str, str] = {}
    for opt in options:
        sku = get_sku(opt)
        raw_c = (get_color(opt) or '').strip()
        mc = get_model_code(opt) or ''
        prefix = model_lcp.get(mc, '')
        if prefix and raw_c.startswith(prefix):
            cleaned = raw_c[len(prefix):].strip() or one_color_label
        else:
            cleaned = raw_c or one_color_label

        brand_v = (get_brand(opt) or '').strip()
        raw_pname = (get_model_name(opt) or '').strip()
        # 색상이 제품명과 통째로 같은 더러운 케이스 → ONE Color
        if cleaned and raw_pname and cleaned == raw_pname:
            cleaned = one_color_label
        cleaned_color[sku] = cleaned

        disp_model = raw_pname
        if not disp_model:
            disp_model = prefix
        if not disp_model and brand_v and raw_pname.startswith(brand_v):
            disp_model = raw_pname[len(brand_v):].strip()
        if disp_model and brand_v:
            disp_model = strip_brand_tokens(disp_model, brand_v)
        if disp_model:
            # 색상이 끝에 붙어있으면 strip
            if cleaned and cleaned != one_color_label and disp_model.endswith(cleaned):
                disp_model = disp_model[:-len(cleaned)].strip()
            display_pname[sku] = (f'{brand_v} {disp_model}'.strip() if brand_v else disp_model)
        else:
            display_pname[sku] = raw_pname or sku

    return cleaned_color, display_pname
