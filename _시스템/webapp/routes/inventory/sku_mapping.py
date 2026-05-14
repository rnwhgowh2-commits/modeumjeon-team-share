"""[I] /inventory/sku-mapping — SKU 자동 매핑 큐 + 수동 승인.

Q3 결정 D 구현 (자동 + 수동 보완).
ai-workflow STEP 7 Sprint 1B Task 1.8
"""
from flask import render_template, request, redirect, url_for, flash

from shared.db import SessionLocal
from lemouton.sourcing.models import Option, Model

from . import bp


@bp.get('/sku-mapping')
def sku_mapping_view():
    s = SessionLocal()
    try:
        from sqlalchemy import func
        all_count = s.query(func.count(Option.canonical_sku)).scalar() or 0
        mapped_count = s.query(func.count(Option.canonical_sku)).filter(Option.boxhero_sku.isnot(None)).scalar() or 0
        unmapped_options = (
            s.query(Option, Model)
            .join(Model, Option.model_code == Model.model_code)
            .filter(Option.boxhero_sku.is_(None))
            .order_by(Model.model_name_raw, Option.color_code, Option.size_code)
            .limit(200)
            .all()
        )
        return render_template(
            'inventory/sku_mapping.html',
            active='sku-mapping',
            kpi={
                'all': all_count,
                'mapped': mapped_count,
                'unmapped': all_count - mapped_count,
                'pct': round(mapped_count / all_count * 100, 1) if all_count else 0,
            },
            unmapped_options=unmapped_options,
        )
    finally:
        s.close()


@bp.post('/sku-mapping/confirm')
def sku_mapping_confirm():
    canonical_sku = request.form.get('canonical_sku', '').strip()
    boxhero_sku = request.form.get('boxhero_sku', '').strip()
    if not canonical_sku or not boxhero_sku:
        flash("옵션과 박스히어로 SKU 모두 필요합니다.", 'error')
        return redirect(url_for('inventory.sku_mapping_view'))

    s = SessionLocal()
    try:
        opt = s.query(Option).filter(Option.canonical_sku == canonical_sku).first()
        if not opt:
            flash(f"옵션 없음: {canonical_sku}", 'error')
        else:
            opt.boxhero_sku = boxhero_sku
            s.commit()
            flash(f"매핑 완료: {canonical_sku} ↔ {boxhero_sku}", 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.sku_mapping_view'))


@bp.post('/sku-mapping/<canonical_sku>/unmap')
def sku_mapping_unmap(canonical_sku):
    s = SessionLocal()
    try:
        opt = s.query(Option).filter(Option.canonical_sku == canonical_sku).first()
        if opt:
            opt.boxhero_sku = None
            s.commit()
            flash("매핑 해제됨", 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.sku_mapping_view'))
