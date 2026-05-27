"""[I] /inventory/count, /alerts, /share — 재고조사·알림·공유링크.

ai-workflow STEP 7 Sprint 3 Task 3.4~3.6
"""
import json
import secrets
from datetime import datetime, timezone

from flask import render_template, request, redirect, url_for, flash

from shared.db import SessionLocal
from lemouton.sourcing.models import Option, Model
from lemouton.inventory.models import (
    InventoryCount, InventoryCountSheet, InventoryCountSheetItem,
    InventoryShareLink, InventorySafetyStock, InventoryLocation,
    InventoryTx,
)

from . import bp


# ============ Sprint 4 — 분석 6개 (Task 4.1~4.5) ============

@bp.get('/dashboard')
def reports_dashboard():
    """대시보드 — 핵심 KPI 4종 + 빠른 링크."""
    s = SessionLocal()
    try:
        from lemouton.inventory.models import InventoryTx
        from sqlalchemy import func
        total_options = s.query(Option).count()
        total_stock = s.query(func.sum(Option.boxhero_stock_total)).scalar() or 0
        in_count = s.query(InventoryTx).filter(InventoryTx.tx_type == 'in').count()
        out_count = s.query(InventoryTx).filter(InventoryTx.tx_type == 'out').count()
        return render_template('inventory/reports/dashboard.html',
                               active='dashboard',
                               total_options=total_options, total_stock=total_stock,
                               in_count=in_count, out_count=out_count)
    finally:
        s.close()


@bp.get('/reports/inventory')
def reports_inventory():
    """재고 현황 분석 — 모델·색상·사이즈별 집계."""
    s = SessionLocal()
    try:
        # [2026-05-27] 정렬: 브랜드 > 카테고리 > 모델명 > 색상 > 사이즈
        from lemouton.sourcing.models import Model as _M
        options = (s.query(Option).join(_M, Option.model_code == _M.model_code)
                   .order_by(_M.brand, _M.category, _M.model_name_display,
                             Option.color_display, Option.size_display)
                   .limit(500).all())
        # 모델별 집계
        by_model = {}
        for o in options:
            d = by_model.setdefault(o.model_code, {'options': 0, 'stock': 0, 'mapped': 0})
            d['options'] += 1
            d['stock'] += (o.boxhero_stock_total or 0)
            if o.boxhero_sku:
                d['mapped'] += 1
        return render_template('inventory/reports/inventory.html',
                               active='reports',
                               by_model=sorted(by_model.items()),
                               total_options=len(options))
    finally:
        s.close()


@bp.get('/reports/sales')
def reports_sales():
    """매출 분석 — 출고 Tx + COGS snapshot 기반 마진 계산."""
    s = SessionLocal()
    try:
        from lemouton.inventory.models import InventoryTx
        out_txs = (s.query(InventoryTx)
                   .filter(InventoryTx.tx_type == 'out')
                   .order_by(InventoryTx.created_at.desc()).limit(500).all())
        rows = []
        total_rev = total_cost = 0
        for tx in out_txs:
            rev = (tx.unit_sale_price or 0) * (tx.qty or 0)
            cost = (tx.unit_purchase_price_at_tx or 0) * (tx.qty or 0)
            margin = rev - cost
            total_rev += rev
            total_cost += cost
            rows.append({'tx': tx, 'revenue': rev, 'cost': cost,
                         'margin': margin, 'margin_rate': (margin/rev*100) if rev else 0})
        return render_template('inventory/reports/sales.html',
                               active='reports', rows=rows,
                               total_rev=total_rev, total_cost=total_cost,
                               total_margin=total_rev - total_cost)
    finally:
        s.close()


@bp.get('/reports/past-quantity')
def reports_past_quantity():
    """과거 수량 추적 — 옵션별 시계열 (단순 Tx 누적)."""
    s = SessionLocal()
    try:
        from lemouton.inventory.models import InventoryTx
        sku = request.args.get('sku', '').strip()
        timeline = []
        if sku:
            txs = (s.query(InventoryTx)
                   .filter(InventoryTx.option_canonical_sku == sku)
                   .order_by(InventoryTx.created_at).all())
            cum = 0
            for tx in txs:
                delta = (tx.qty or 0) if tx.tx_type == 'in' else -(tx.qty or 0) if tx.tx_type == 'out' else (tx.qty or 0)
                if tx.tx_type == 'adjust':
                    cum = tx.qty or 0
                else:
                    cum += delta
                timeline.append({'tx': tx, 'cumulative': cum})
        return render_template('inventory/reports/past_quantity.html',
                               active='reports', sku=sku, timeline=timeline)
    finally:
        s.close()


@bp.get('/reports/summary')
def reports_summary():
    """요약 보고서 — 대시보드 확장판."""
    s = SessionLocal()
    try:
        from lemouton.inventory.models import InventoryTx, PurchaseOrder, SalesOrder
        from sqlalchemy import func
        kpis = {
            'options': s.query(Option).count(),
            'mapped': s.query(Option).filter(Option.boxhero_sku.isnot(None), Option.boxhero_sku != '').count(),
            'in_qty': s.query(func.sum(InventoryTx.qty)).filter(InventoryTx.tx_type == 'in').scalar() or 0,
            'out_qty': s.query(func.sum(InventoryTx.qty)).filter(InventoryTx.tx_type == 'out').scalar() or 0,
            'po_pending': s.query(PurchaseOrder).filter(PurchaseOrder.status == 'pending').count(),
            'so_pending': s.query(SalesOrder).filter(SalesOrder.status == 'pending').count(),
        }
        return render_template('inventory/reports/summary.html',
                               active='reports', kpis=kpis)
    finally:
        s.close()


_CUSTOM_REPORTS_FILE = None
def _custom_reports_path():
    from pathlib import Path
    return Path(__file__).resolve().parents[3] / 'data' / 'custom_reports.json'


def _load_custom_reports():
    import json
    p = _custom_reports_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            return []
    return []


def _save_custom_reports(items):
    import json
    p = _custom_reports_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')


@bp.get('/reports/custom')
def reports_custom():
    """커스텀 보고서 위저드 — 4 step (조건/컬럼/정렬/저장)."""
    return render_template('inventory/reports/custom.html',
                           active='reports',
                           saved_reports=_load_custom_reports())


@bp.post('/reports/custom/save')
def reports_custom_save():
    """리포트 설정 저장."""
    from datetime import datetime
    name = (request.form.get('report_name') or '').strip()
    if not name:
        flash('리포트 이름을 입력해주세요.', 'error')
        return redirect(url_for('inventory.reports_custom'))
    reports = _load_custom_reports()
    new_id = max([r.get('id', 0) for r in reports] + [0]) + 1
    reports.append({
        'id': new_id, 'name': name,
        'date_from': request.form.get('date_from'),
        'date_to': request.form.get('date_to'),
        'tx_types': request.form.getlist('tx_types'),
        'cols': request.form.getlist('cols'),
        'sort_by': request.form.get('sort_by'),
        'group_by': request.form.get('group_by'),
        'format': request.form.get('format', 'html'),
        'partner_filter': request.form.get('partner_filter'),
        'sku_filter': request.form.get('sku_filter'),
        'created_at': datetime.now().isoformat(),
    })
    _save_custom_reports(reports)
    flash(f'리포트 "{name}" 저장됨', 'success')
    return redirect(url_for('inventory.reports_custom'))


@bp.post('/reports/custom/run')
def reports_custom_run():
    """리포트 실행 미리보기 — 조건 적용."""
    from sqlalchemy import or_
    s = SessionLocal()
    try:
        query = s.query(InventoryTx)
        types = request.form.getlist('tx_types')
        if types:
            query = query.filter(InventoryTx.tx_type.in_(types))
        date_from = request.form.get('date_from')
        date_to = request.form.get('date_to')
        if date_from:
            from datetime import datetime
            query = query.filter(InventoryTx.created_at >= datetime.fromisoformat(date_from))
        if date_to:
            from datetime import datetime
            query = query.filter(InventoryTx.created_at <= datetime.fromisoformat(date_to + 'T23:59'))
        partner_f = (request.form.get('partner_filter') or '').strip()
        if partner_f:
            query = query.filter(InventoryTx.partner_label.like(f'%{partner_f}%'))
        sku_f = (request.form.get('sku_filter') or '').strip()
        if sku_f:
            query = query.filter(InventoryTx.option_canonical_sku.like(f'%{sku_f}%'))
        sort_by = request.form.get('sort_by', 'date_desc')
        if sort_by == 'date_asc':
            query = query.order_by(InventoryTx.created_at.asc())
        elif sort_by == 'qty_desc':
            query = query.order_by(InventoryTx.qty.desc())
        elif sort_by == 'sku':
            query = query.order_by(InventoryTx.option_canonical_sku.asc())
        else:
            query = query.order_by(InventoryTx.created_at.desc())
        items = query.limit(500).all()
        cols = request.form.getlist('cols')
        return render_template('inventory/reports/custom_run.html',
                               active='reports', items=items, cols=cols,
                               total=len(items))
    finally:
        s.close()


@bp.get('/reports/custom/<int:report_id>/load')
def reports_custom_load(report_id):
    """저장된 리포트 불러오기."""
    reports = _load_custom_reports()
    r = next((x for x in reports if x.get('id') == report_id), None)
    if not r:
        flash('리포트를 찾을 수 없습니다.', 'error')
        return redirect(url_for('inventory.reports_custom'))
    return render_template('inventory/reports/custom.html',
                           active='reports', loaded=r,
                           saved_reports=reports)


# ============ 재고조사 (Task 3.4) ============

@bp.get('/count')
def count_list():
    s = SessionLocal()
    try:
        counts = s.query(InventoryCount).order_by(InventoryCount.created_at.desc()).limit(100).all()
        return render_template('inventory/reports/count_list.html',
                               active='count', counts=counts)
    finally:
        s.close()


@bp.get('/count/new')
def count_new():
    s = SessionLocal()
    try:
        from lemouton.inventory.locations import list_active
        locations = list_active(s)
        return render_template('inventory/reports/count_form.html',
                               active='count', locations=locations)
    finally:
        s.close()


@bp.post('/count/create')
def count_create():
    s = SessionLocal()
    try:
        name = request.form.get('name', '').strip() or f'재고조사 {datetime.now().strftime("%Y%m%d-%H%M")}'
        loc_ids = request.form.getlist('location_id')
        c = InventoryCount(
            name=name,
            target_locations_json=json.dumps([int(x) for x in loc_ids if x]),
            status='in_progress',
        )
        s.add(c)
        s.commit()
        flash(f'재고조사 "{c.name}" 시작 (#{c.id})', 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.count_list'))


@bp.post('/count/<int:count_id>/close')
def count_close(count_id):
    s = SessionLocal()
    try:
        c = s.query(InventoryCount).filter(InventoryCount.id == count_id).first()
        if c:
            c.status = 'closed'
            c.closed_at = datetime.now(timezone.utc)
            s.commit()
            flash(f'재고조사 #{count_id} 마감', 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.count_list'))


# ============ 재고 알림 (Task 3.5) ============

@bp.get('/alerts')
def alerts_view():
    """안전재고 임계값 + 미달 옵션 자동 알림."""
    s = SessionLocal()
    try:
        thresholds = s.query(InventorySafetyStock).limit(500).all()
        threshold_map = {(t.option_canonical_sku, t.location_id): t for t in thresholds}

        # 임계값 설정된 옵션 fetch
        skus = list({t.option_canonical_sku for t in thresholds})
        options_by_sku = {}
        if skus:
            options_by_sku = {o.canonical_sku: o for o in
                              s.query(Option).filter(Option.canonical_sku.in_(skus)).all()}

        # 알림 행 — 현재 재고 < 임계값
        alerts = []
        for t in thresholds:
            opt = options_by_sku.get(t.option_canonical_sku)
            stock = (opt.boxhero_stock_total or 0) if opt else 0
            if stock < t.threshold:
                alerts.append({'sku': t.option_canonical_sku, 'threshold': t.threshold,
                               'stock': stock, 'gap': t.threshold - stock,
                               'location_id': t.location_id})

        return render_template('inventory/reports/alerts.html',
                               active='alerts',
                               thresholds=thresholds, alerts=alerts,
                               total_thresholds=len(thresholds))
    finally:
        s.close()


@bp.post('/alerts/upsert')
def alerts_upsert():
    sku = request.form.get('option_canonical_sku', '').strip()
    loc_id_raw = request.form.get('location_id', '').strip()
    location_id = int(loc_id_raw) if loc_id_raw else None
    try:
        threshold = int(request.form.get('threshold', 0))
    except ValueError:
        flash('임계값 숫자 아님', 'error')
        return redirect(url_for('inventory.alerts_view'))
    if not sku or threshold < 0:
        flash('SKU 필수, 임계값 ≥ 0', 'error')
        return redirect(url_for('inventory.alerts_view'))

    s = SessionLocal()
    try:
        existing = (s.query(InventorySafetyStock)
                    .filter(InventorySafetyStock.option_canonical_sku == sku,
                            InventorySafetyStock.location_id == location_id).first())
        if existing:
            existing.threshold = threshold
        else:
            s.add(InventorySafetyStock(
                option_canonical_sku=sku, location_id=location_id, threshold=threshold))
        s.commit()
        flash(f'안전재고 설정 — {sku} ≥ {threshold}', 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.alerts_view'))


@bp.post('/alerts/<int:alert_id>/delete')
def alerts_delete(alert_id):
    s = SessionLocal()
    try:
        a = s.query(InventorySafetyStock).filter(InventorySafetyStock.id == alert_id).first()
        if a:
            s.delete(a)
            s.commit()
            flash('알림 임계값 제거됨', 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.alerts_view'))


# ============ 재고 공유 링크 (Task 3.6) ============

@bp.get('/share')
def share_list():
    s = SessionLocal()
    try:
        links = s.query(InventoryShareLink).order_by(InventoryShareLink.created_at.desc()).limit(100).all()
        return render_template('inventory/reports/share_list.html',
                               active='share', links=links)
    finally:
        s.close()


@bp.post('/share/create')
def share_create():
    s = SessionLocal()
    try:
        name = request.form.get('name', '').strip() or '공유 링크'
        token = secrets.token_urlsafe(24)
        link = InventoryShareLink(
            name=name, token=token,
            created_by=request.form.get('created_by', '운영자'),
        )
        s.add(link)
        s.commit()
        flash(f'공유 링크 생성됨 — 토큰: {token[:12]}...', 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.share_list'))


@bp.post('/share/<int:link_id>/revoke')
def share_revoke(link_id):
    s = SessionLocal()
    try:
        link = s.query(InventoryShareLink).filter(InventoryShareLink.id == link_id).first()
        if link:
            link.revoked_at = datetime.now(timezone.utc)
            s.commit()
            flash(f'링크 #{link_id} 폐기됨', 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.share_list'))


@bp.get('/share/public/<token>')
def share_public(token):
    """외부 공개 — 토큰 검증 후 read-only 재고 조회."""
    s = SessionLocal()
    try:
        link = s.query(InventoryShareLink).filter(
            InventoryShareLink.token == token,
            InventoryShareLink.revoked_at.is_(None),
        ).first()
        if not link:
            return '<h1>링크 만료 또는 폐기됨</h1>', 404
        # filter_json 적용 (간단히 전체 재고 read-only 표시)
        # [2026-05-27] 정렬: 브랜드 > 카테고리 > 모델명 > 색상 > 사이즈
        from lemouton.sourcing.models import Model as _M
        options = (s.query(Option).join(_M, Option.model_code == _M.model_code)
                   .order_by(_M.brand, _M.category, _M.model_name_display,
                             Option.color_display, Option.size_display)
                   .limit(500).all())
        # ★ LCP 색상 정리 + 제품명 brand-strip (전 시스템 통일)
        from shared.product_display import compute_display_maps
        cleaned_color, display_pname = compute_display_maps(options)
        return render_template('inventory/reports/share_public.html',
                               link=link, options=options,
                               cleaned_color=cleaned_color, display_pname=display_pname)
    finally:
        s.close()
