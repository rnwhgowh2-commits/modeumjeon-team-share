"""[I] /inventory/barcode — 바코드 인쇄 (박스히어로 1:1).

라벨 디자인 (라벨 용지/감열지/사용자 정의) + 제품 선택 + 인쇄 수량 + 미리보기.
v1.4 — 묶음 바코드 추가 (/barcode/bundles).
"""
import json
from pathlib import Path
from flask import render_template, request
from sqlalchemy.orm import joinedload

from shared.db import SessionLocal
from lemouton.sourcing.models import Option, Model

from . import bp


BUNDLE_FILE = Path(__file__).resolve().parents[3] / 'data' / 'bundles.json'


def _load_bundles() -> list:
    if BUNDLE_FILE.exists():
        try:
            return json.loads(BUNDLE_FILE.read_text(encoding='utf-8'))
        except Exception:
            return []
    return []


# 라벨 용지 프리셋 (단위 mm, A4 = 210×297)
# - 📦 박스히어로 호환: 사용자 익숙도 우선 (박스히어로 SaaS 표기 그대로)
# - 🇰🇷 한국폼텍 공식: 한국폼텍 공식 사이트 + 다나와/홈플러스 크로스체크 ✅
# - 🇺🇸 Avery gLabels: github.com/j-evins/glabels-qt avery-iso-templates.xml ✅
# 진실 원천 추적: docs/label_paper_specs.md
LABEL_TEMPLATES = {
    # ─── 📦 박스히어로 호환 (사용자 익숙도)
    '3m_21314': {'name': '📦 3M Asia Pacific 21314 (A4) — 4×10 = 40칸', 'cols': 4, 'rows': 10,
                'label_w': 48.5, 'label_h': 29.7, 'paper_w': 210, 'paper_h': 297,
                'margin_top': 0, 'margin_left': 7.5, 'gap_x': 0, 'gap_y': 0,
                'per_page': 40},
    'formtec_3102': {'name': '📦 Formtec 3102 (박스히어로 표기) — 5×13 = 65칸', 'cols': 5, 'rows': 13,
                    'label_w': 38.1, 'label_h': 21.2, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 10.7, 'margin_left': 4.6, 'gap_x': 2.5, 'gap_y': 0,
                    'per_page': 65},
    'formtec_3103': {'name': '📦 Formtec 3103 (박스히어로 표기) — 4×12 = 48칸', 'cols': 4, 'rows': 12,
                    'label_w': 48.5, 'label_h': 25.4, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 8, 'margin_left': 8, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 48},
    'formtec_3107': {'name': '📦 Formtec 3107 (박스히어로 표기) — 3×8 = 24칸', 'cols': 3, 'rows': 8,
                    'label_w': 64, 'label_h': 33.9, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 13, 'margin_left': 7, 'gap_x': 2.5, 'gap_y': 0,
                    'per_page': 24},
    'formtec_3108': {'name': '📦 Formtec 3108 (박스히어로 표기) — 3×7 = 21칸', 'cols': 3, 'rows': 7,
                    'label_w': 64, 'label_h': 38.1, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 15.1, 'margin_left': 7, 'gap_x': 2.5, 'gap_y': 0,
                    'per_page': 21},
    # ─── 🇰🇷 한국폼텍 공식 검증 ✅ (다나와·홈플러스·코스트코 크로스체크)
    'kr_ls3100': {'name': '🇰🇷 폼텍 LS-3100 — 5×13 = 65칸 (38.1×21.2mm) 바코드용', 'cols': 5, 'rows': 13,
                    'label_w': 38.1, 'label_h': 21.2, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 10.7, 'margin_left': 9.75, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 65},
    'kr_ls3102': {'name': '🇰🇷 폼텍 LS-3102 — 4×10 = 40칸 (47×26.9mm) 바코드용 ★기본', 'cols': 4, 'rows': 10,
                    'label_w': 47.0, 'label_h': 26.9, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 14.0, 'margin_left': 11.0, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 40},
    'kr_ls3104': {'name': '🇰🇷 폼텍 LS-3104 — 3×9 = 27칸 (62.7×30.1mm) 바코드용', 'cols': 3, 'rows': 9,
                    'label_w': 62.7, 'label_h': 30.1, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 13.05, 'margin_left': 10.95, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 27},
    'kr_ls3106': {'name': '🇰🇷 폼텍 LS-3106 — 3×8 = 24칸 (64×34mm) 주소용', 'cols': 3, 'rows': 8,
                    'label_w': 64.0, 'label_h': 34.0, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 12.5, 'margin_left': 9.0, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 24},
    'kr_ls3107': {'name': '🇰🇷 폼텍 LS-3107 — 2×8 = 16칸 (99.1×33.9mm) 주소용', 'cols': 2, 'rows': 8,
                    'label_w': 99.1, 'label_h': 33.9, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 12.9, 'margin_left': 5.9, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 16},
    'kr_ls3108': {'name': '🇰🇷 폼텍 LS-3108 — 2×7 = 14칸 (99.1×38.1mm) 주소용', 'cols': 2, 'rows': 7,
                    'label_w': 99.1, 'label_h': 38.1, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 15.15, 'margin_left': 5.9, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 14},
    'kr_ls3114': {'name': '🇰🇷 폼텍 LS-3114 — 2×4 = 8칸 (99.1×67.7mm) 물류용', 'cols': 2, 'rows': 4,
                    'label_w': 99.1, 'label_h': 67.7, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 13.1, 'margin_left': 5.9, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 8},
    'kr_ls3118': {'name': '🇰🇷 폼텍 LS-3118 — 2×2 = 4칸 (99.1×140mm) 물류용', 'cols': 2, 'rows': 2,
                    'label_w': 99.1, 'label_h': 140.0, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 8.5, 'margin_left': 5.9, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 4},
    'kr_ls3120': {'name': '🇰🇷 폼텍 LS-3120 — 1×2 = 2칸 (200×140mm) 물류용', 'cols': 1, 'rows': 2,
                    'label_w': 200.0, 'label_h': 140.0, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 8.5, 'margin_left': 5.0, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 2},
    'kr_ls3130': {'name': '🇰🇷 폼텍 LS-3130 — 1×1 = 1칸 (210×297mm) 전면', 'cols': 1, 'rows': 1,
                    'label_w': 210.0, 'label_h': 297.0, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 0, 'margin_left': 0, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 1},
    # ─── 🇺🇸 Avery gLabels 검증 ✅ (avery-iso-templates.xml)
    'us_l7160': {'name': '🇺🇸 Avery L7160 — 3×7 = 21칸 (63.5×38.1mm)', 'cols': 3, 'rows': 7,
                    'label_w': 63.5, 'label_h': 38.1, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 15.49, 'margin_left': 7.48, 'gap_x': 2.05, 'gap_y': 0,
                    'per_page': 21},
    'us_l7161': {'name': '🇺🇸 Avery L7161 — 3×6 = 18칸 (63.5×46.6mm)', 'cols': 3, 'rows': 6,
                    'label_w': 63.5, 'label_h': 46.6, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 8.11, 'margin_left': 7.41, 'gap_x': 2.50, 'gap_y': 0,
                    'per_page': 18},
    'us_l7162': {'name': '🇺🇸 Avery L7162 — 2×8 = 16칸 (99.1×33.9mm)', 'cols': 2, 'rows': 8,
                    'label_w': 99.1, 'label_h': 33.9, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 12.98, 'margin_left': 3.99, 'gap_x': 3.39, 'gap_y': 0,
                    'per_page': 16},
    'us_l7163': {'name': '🇺🇸 Avery L7163 — 2×7 = 14칸 (99.1×38.1mm)', 'cols': 2, 'rows': 7,
                    'label_w': 99.1, 'label_h': 38.1, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 15.17, 'margin_left': 3.35, 'gap_x': 2.82, 'gap_y': 0,
                    'per_page': 14},
    'us_l7165': {'name': '🇺🇸 Avery L7165 — 2×4 = 8칸 (99.1×67.7mm)', 'cols': 2, 'rows': 4,
                    'label_w': 99.1, 'label_h': 67.7, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 13.04, 'margin_left': 4.67, 'gap_x': 2.50, 'gap_y': 0,
                    'per_page': 8},
    'us_l7651': {'name': '🇺🇸 Avery L7651 — 5×13 = 65칸 (38.1×21.2mm) 소형', 'cols': 5, 'rows': 13,
                    'label_w': 38.1, 'label_h': 21.2, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 10.90, 'margin_left': 4.70, 'gap_x': 2.54, 'gap_y': 0,
                    'per_page': 65},
    'us_l7654': {'name': '🇺🇸 Avery L7654 — 4×10 = 40칸 (45.7×25.4mm)', 'cols': 4, 'rows': 10,
                    'label_w': 45.7, 'label_h': 25.4, 'paper_w': 210, 'paper_h': 297,
                    'margin_top': 22.0, 'margin_left': 10.0, 'gap_x': 2.80, 'gap_y': 0,
                    'per_page': 40},
    # ─── ♨ 감열지 (열전사 프린터용 1장 1라벨)
    'thermal_60_35': {'name': '♨ 감열지 60×35mm', 'cols': 1, 'rows': 1,
                    'label_w': 60, 'label_h': 35, 'paper_w': 60, 'paper_h': 35,
                    'margin_top': 0, 'margin_left': 0, 'gap_x': 0, 'gap_y': 0,
                    'per_page': 1},
    'thermal_50_30': {'name': '♨ 감열지 50×30mm', 'cols': 1, 'rows': 1,
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
        template_key = request.args.get('template', 'kr_ls3102')  # 기본 4×10
        cutline = request.args.get('cutline') == '1'
        options = (
            s.query(Option)
            .options(joinedload(Option.model))
            .order_by(Option.model_code).limit(500).all()
        )
        # 사용자 정의 템플릿 우선
        custom = _build_custom_template(request.args) if template_key == 'custom' else None
        template = custom or LABEL_TEMPLATES.get(template_key, LABEL_TEMPLATES['kr_ls3102'])
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
    template_key = request.args.get('template', 'kr_ls3102')
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
    template_key = request.args.get('template', 'kr_ls3102')
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
    template_key = request.args.get('template', 'kr_ls3102')
    cutline = request.args.get('cutline') == '1'
    custom = _build_custom_template(request.args) if template_key == 'custom' else None
    tpl = custom or LABEL_TEMPLATES.get(template_key, LABEL_TEMPLATES['kr_ls3102'])
    s = SessionLocal()
    try:
        rows = []
        if skus:
            options = (
                s.query(Option)
                .options(joinedload(Option.model))
                .filter(Option.canonical_sku.in_(skus)).all()
            )
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
