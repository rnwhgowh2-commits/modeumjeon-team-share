"""[I] /inventory/barcode — 바코드 인쇄 (박스히어로 1:1).

라벨 디자인 (라벨 용지/감열지/사용자 정의) + 제품 선택 + 인쇄 수량 + 미리보기.
v1.4 — 묶음 바코드 추가 (/barcode/bundles).
"""
import json
from pathlib import Path
from flask import render_template, request

from shared.db import SessionLocal
from lemouton.sourcing.models import Option

from . import bp


BUNDLE_FILE = Path(__file__).resolve().parents[3] / 'data' / 'bundles.json'


def _load_bundles() -> list:
    if BUNDLE_FILE.exists():
        try:
            return json.loads(BUNDLE_FILE.read_text(encoding='utf-8'))
        except Exception:
            return []
    return []


# 박스히어로 1:1 라벨 용지 프리셋 (3M Asia Pacific + Formtec 시리즈)
LABEL_TEMPLATES = {
    # ★ 3M Asia Pacific 21314 (A4 4×10 = 40칸) — 기본값
    # 위/아래 여백 제거 — label_h 를 297/10 = 29.7mm 로 늘려 풀스택
    '3m_21314': {'name': '3M Asia Pacific 21314 (A4) — 4×10 = 40칸', 'cols': 4, 'rows': 10,
                'label_w': 48.5, 'label_h': 29.7, 'paper_w': 210, 'paper_h': 297,
                'margin_top': 0, 'margin_left': 7.5, 'gap_x': 0, 'gap_y': 0,
                'per_page': 40},
    'formtec_3102': {'name': 'Formtec 3102 (A4) — 5×13 = 65칸', 'cols': 5, 'rows': 13,
                    'label_w': 38.1, 'label_h': 21.2, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 10.7, 'margin_left': 4.6, 'gap_x': 2.5, 'gap_y': 0,
                    'per_page': 65},
    'formtec_3103': {'name': 'Formtec 3103 (A4)', 'cols': 4, 'rows': 12,
                    'label_w': 48.5, 'label_h': 25.4, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 8, 'margin_left': 8, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 48},
    'formtec_3107': {'name': 'Formtec 3107 (A4) — 24칸', 'cols': 3, 'rows': 8,
                    'label_w': 64, 'label_h': 33.9, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 13, 'margin_left': 7, 'gap_x': 2.5, 'gap_y': 0,
                    'per_page': 24},
    'formtec_3108': {'name': 'Formtec 3108 (A4) — 21칸', 'cols': 3, 'rows': 7,
                    'label_w': 64, 'label_h': 38.1, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 15.1, 'margin_left': 7, 'gap_x': 2.5, 'gap_y': 0,
                    'per_page': 21},
    'thermal_60_35': {'name': '감열지 60×35mm', 'cols': 1, 'rows': 1,
                    'label_w': 60, 'label_h': 35, 'paper_w': 60, 'paper_h': 35,
                    'margin_top': 0, 'margin_left': 0, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 1},
    'thermal_50_30': {'name': '감열지 50×30mm', 'cols': 1, 'rows': 1,
                    'label_w': 50, 'label_h': 30, 'paper_w': 50, 'paper_h': 30,
                    'margin_top': 0, 'margin_left': 0, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 1},
}


def _build_custom_template(args) -> dict | None:
    """사용자 정의 라벨 — 가로/세로 칸 수만 입력 → A4 (210×297mm) 자동 분할.

    위/아래 여백 0 + 좌우 여백 5mm + gap 0 + 라벨 크기 = paper / count (가로는 좌우 여백 빼고)
    """
    try:
        cols = int(args.get('cols') or 0)
        rows = int(args.get('rows') or 0)
        if cols <= 0 or rows <= 0 or cols > 20 or rows > 30:
            return None
        paper_w, paper_h = 210.0, 297.0  # A4 고정
        margin_l = 5.0  # 좌우 여백
        margin_t = 0.0  # 위/아래 여백 — 사용자 요구
        label_w = round((paper_w - 2 * margin_l) / cols, 2)
        label_h = round(paper_h / rows, 2)
        return {
            'name': f'사용자 정의 (A4) — {cols}×{rows} = {cols*rows}칸',
            'cols': cols, 'rows': rows,
            'label_w': label_w, 'label_h': label_h,
            'paper_w': paper_w, 'paper_h': paper_h,
            'margin_top': margin_t, 'margin_left': margin_l,
            'gap_x': 0, 'gap_y': 0,
            'per_page': cols * rows,
        }
    except (ValueError, TypeError):
        return None


@bp.get('/barcode')
def barcode_view():
    """바코드 인쇄 — 박스히어로 1:1 라벨 디자인 + 제품 선택 + 미리보기."""
    s = SessionLocal()
    try:
        # ★ 'sku' 는 사전 선택된 옵션 list (multi value) 로 사용 — SQL 필터 ❌, 클라이언트 검색만.
        sku_filter = ''  # SQL 필터 비활성
        template_key = request.args.get('template', '3m_21314')  # 기본 4×10
        cutline = request.args.get('cutline') == '1'
        options = s.query(Option).order_by(Option.model_code).limit(500).all()
        # 사용자 정의 템플릿 우선
        custom = _build_custom_template(request.args) if template_key == 'custom' else None
        template = custom or LABEL_TEMPLATES.get(template_key, LABEL_TEMPLATES['3m_21314'])
        return render_template('inventory/barcode.html',
                               active='barcode', options=options, sku_filter=sku_filter,
                               templates=LABEL_TEMPLATES, template_key=template_key,
                               template=template, cutline=cutline,
                               custom_args=dict(request.args) if template_key == 'custom' else {})
    finally:
        s.close()


@bp.get('/barcode/bundles')
def barcode_bundles_view():
    """묶음 바코드 인쇄 — 묶음 SKU 단위 라벨."""
    bundles = _load_bundles()
    template_key = request.args.get('template', '3m_21314')
    cutline = request.args.get('cutline') == '1'
    return render_template('inventory/barcode/bundles.html',
                           active='barcode', bundles=bundles,
                           templates=LABEL_TEMPLATES, template_key=template_key,
                           template=LABEL_TEMPLATES.get(template_key, LABEL_TEMPLATES['formtec_3102']),
                           cutline=cutline)


@bp.get('/barcode/bundles/print')
def barcode_bundles_print():
    """선택 묶음 SKU 바코드 인쇄."""
    bundle_skus = request.args.getlist('bundle_sku')
    template_key = request.args.get('template', '3m_21314')
    cutline = request.args.get('cutline') == '1'
    tpl = LABEL_TEMPLATES.get(template_key, LABEL_TEMPLATES['formtec_3102'])
    bundles = _load_bundles()
    rows = []
    bundle_map = {b['sku']: b for b in bundles}
    for sku in bundle_skus:
        b = bundle_map.get(sku)
        if b:
            qty = int(request.args.get(f'qty_{sku}', 1) or 1)
            for _ in range(min(qty, 200)):
                rows.append({'canonical_sku': b['sku'], 'name': b['name'],
                             'is_bundle': True, 'price': b.get('price', 0)})
    return render_template('inventory/barcode_print.html', rows=rows,
                           template=tpl, cutline=cutline)


@bp.get('/barcode/print')
def barcode_print():
    """선택한 SKU 바코드 인쇄 — 라벨 용지 템플릿 적용."""
    skus = request.args.getlist('sku')
    template_key = request.args.get('template', '3m_21314')
    cutline = request.args.get('cutline') == '1'
    custom = _build_custom_template(request.args) if template_key == 'custom' else None
    tpl = custom or LABEL_TEMPLATES.get(template_key, LABEL_TEMPLATES['3m_21314'])
    s = SessionLocal()
    try:
        rows = []
        if skus:
            options = s.query(Option).filter(Option.canonical_sku.in_(skus)).all()
            opt_map = {o.canonical_sku: o for o in options}
            for sku in skus:
                opt = opt_map.get(sku)
                if opt:
                    qty = int(request.args.get(f'qty_{sku}', 1) or 1)
                    for _ in range(min(qty, 200)):
                        rows.append(opt)
        return render_template('inventory/barcode_print.html', rows=rows,
                               template=tpl, cutline=cutline)
    finally:
        s.close()
