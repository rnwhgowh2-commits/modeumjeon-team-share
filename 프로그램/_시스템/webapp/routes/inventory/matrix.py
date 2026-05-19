"""[I] /inventory/matrix — 옵션 매트릭스 (R2 ★★★ 핵심).

ai-workflow STEP 7 Sprint 2 Task 2.6

옵션별 평균매입가 + 박스히어로 재고 + 사입 마진 3계층 (옵션>모델>템플릿).
인라인 편집 — 옵션 단위 마진 오버라이드 mode/value.
"""
from flask import render_template, request, redirect, url_for, flash, jsonify

from shared.db import SessionLocal
from lemouton.sourcing.models import Option, Model
from lemouton.templates.models import PriceTemplate
from lemouton.pricing.boxhero_margin import compute_sale_price

from . import bp


@bp.get('/matrix')
def matrix_view():
    """옵션 매트릭스 — 모음전 162 옵션 행, 사입 마진 3계층 표시."""
    s = SessionLocal()
    try:
        model_filter = request.args.get('model_code', '').strip()
        unmapped_only = request.args.get('unmapped') == '1'

        q = s.query(Option).join(Model, Option.model_code == Model.model_code)
        if model_filter:
            q = q.filter(Option.model_code == model_filter)
        if unmapped_only:
            q = q.filter((Option.boxhero_sku.is_(None)) | (Option.boxhero_sku == ''))

        options = q.order_by(Option.model_code, Option.sort_order, Option.canonical_sku).all()

        # 모델·템플릿 prefetch (N+1 회피)
        model_codes = list({o.model_code for o in options})
        models_by_code = {m.model_code: m for m in
                          s.query(Model).filter(Model.model_code.in_(model_codes)).all()}
        tpl_ids = list({m.price_template_id for m in models_by_code.values() if m.price_template_id})
        templates_by_id = {t.id: t for t in
                           s.query(PriceTemplate).filter(PriceTemplate.id.in_(tpl_ids)).all()}

        # 색상·제품명 정리 — shared.product_display 헬퍼 (전 시스템 통일)
        # matrix 의 opt.model 이 lazy load 안 될 수 있어 models_by_code 로 명시 전달
        from shared.product_display import compute_display_maps
        cleaned_color, display_pname = compute_display_maps(
            options,
            get_brand=lambda o: (models_by_code.get(o.model_code).brand if models_by_code.get(o.model_code) else '') or '',
            get_model_name=lambda o: ((models_by_code.get(o.model_code).model_name_display or models_by_code.get(o.model_code).model_name_raw) if models_by_code.get(o.model_code) else '') or '',
        )

        # 행 계산
        rows = []
        for opt in options:
            model = models_by_code.get(opt.model_code)
            tpl_id = opt.price_template_id_override or (model.price_template_id if model else None)
            tpl = templates_by_id.get(tpl_id) if tpl_id else None

            self_calc = compute_sale_price(opt, model, tpl, 'self')
            ext_calc = compute_sale_price(opt, model, tpl, 'external')

            rows.append({
                'opt': opt,
                'model_name': display_pname.get(opt.canonical_sku, opt.canonical_sku),  # ★ LCP+brand-strip 적용
                'cleaned_color': cleaned_color.get(opt.canonical_sku, 'ONE Color'),  # ★
                'template_name': tpl.name if tpl else '-',
                'self': self_calc,
                'external': ext_calc,
            })

        # 모델 드롭다운용
        all_models = s.query(Model).order_by(Model.model_code).all()

        # ★ SSOT 실시간 재고 batch
        from shared.inventory_stock import get_stock_batch
        all_skus = [r['opt'].canonical_sku for r in rows]
        stock_map = get_stock_batch(s, all_skus)
        for r in rows:
            r['realtime_stock'] = stock_map.get(r['opt'].canonical_sku, 0)

        # 요약 통계 (실시간)
        total = len(rows)
        mapped = sum(1 for r in rows if r['opt'].boxhero_sku)
        with_stock = sum(1 for r in rows if r['realtime_stock'] > 0)
        with_avg = sum(1 for r in rows if (r['opt'].boxhero_avg_purchase_price or 0) > 0)

        return render_template(
            'inventory/matrix.html',
            active='matrix',
            rows=rows,
            all_models=all_models,
            model_filter=model_filter,
            unmapped_only=unmapped_only,
            stats={'total': total, 'mapped': mapped, 'with_stock': with_stock, 'with_avg': with_avg},
            stock_map=stock_map,
            cleaned_color=cleaned_color,
            display_pname=display_pname,
        )
    finally:
        s.close()


@bp.post('/matrix/toggle-purchase')
def matrix_toggle_purchase():
    """사입재고 활성화 토글 — ON 이면 매트릭스에서 자체 판매가가 활성 가격."""
    sku = request.form.get('canonical_sku', '').strip()
    enable = request.form.get('enable', '').strip() == '1'
    s = SessionLocal()
    try:
        opt = s.query(Option).filter(Option.canonical_sku == sku).first()
        if not opt:
            return jsonify({'ok': False, 'error': f'option not found: {sku}'}), 404
        opt.use_purchase_inventory = enable
        s.commit()
        return jsonify({'ok': True, 'use_purchase_inventory': enable, 'sku': sku})
    finally:
        s.close()


@bp.post('/matrix/edit')
def matrix_edit():
    """옵션 단위 사입 마진 오버라이드 — option > model > template 3계층 중 최우선."""
    sku = request.form.get('canonical_sku', '').strip()
    source_type = request.form.get('source_type', 'self')  # self|external
    mode = request.form.get('mode', '').strip()  # ''|'rate'|'amount'
    value_raw = request.form.get('value', '').strip()
    clear = request.form.get('clear') == '1'

    if source_type not in ('self', 'external'):
        return jsonify({'ok': False, 'error': 'invalid source_type'}), 400

    s = SessionLocal()
    try:
        opt = s.query(Option).filter(Option.canonical_sku == sku).first()
        if not opt:
            return jsonify({'ok': False, 'error': f'option not found: {sku}'}), 404

        if clear:
            # 옵션 오버라이드 제거 → 상위 계층(모델/템플릿) 으로 fallback
            if source_type == 'self':
                opt.option_boxhero_margin_mode = None
                opt.option_boxhero_margin_value = None
            else:
                opt.option_external_margin_mode = None
                opt.option_external_margin_value = None
            s.commit()
            return jsonify({'ok': True, 'cleared': True})

        if mode not in ('rate', 'amount'):
            return jsonify({'ok': False, 'error': 'invalid mode'}), 400
        try:
            value = int(value_raw)
        except (ValueError, TypeError):
            return jsonify({'ok': False, 'error': 'invalid value'}), 400
        if value < 0:
            return jsonify({'ok': False, 'error': 'value must be ≥ 0'}), 400

        if source_type == 'self':
            opt.option_boxhero_margin_mode = mode
            opt.option_boxhero_margin_value = value
        else:
            opt.option_external_margin_mode = mode
            opt.option_external_margin_value = value
        s.commit()

        # 재계산 후 반환
        model = s.query(Model).filter(Model.model_code == opt.model_code).first()
        tpl_id = opt.price_template_id_override or (model.price_template_id if model else None)
        tpl = s.query(PriceTemplate).filter(PriceTemplate.id == tpl_id).first() if tpl_id else None
        recalc = compute_sale_price(opt, model, tpl, source_type)
        return jsonify({'ok': True, 'recalc': recalc})
    except Exception as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
