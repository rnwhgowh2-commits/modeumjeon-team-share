"""[I] /inventory/purchase, /inventory/sale, /inventory/return — Sprint 3 3.1~3.3.

박스히어로 1:1 복제 — 발주/판매/반품 3개 메뉴.
v2.0 (2026-05-09): 자동 재고 연동 — SO 완료 → 출고 자동 차감 / RO 완료 → 입고 자동 환원.
"""
import json
from datetime import datetime, timezone

from flask import render_template, request, redirect, url_for, flash

from shared.db import SessionLocal
from lemouton.sourcing.models import Option
from lemouton.inventory.models import (
    PurchaseOrder, SalesOrder, ReturnOrder, NotificationLog,
    InventoryLocation,
)
from lemouton.inventory import inbound as tx_svc
from lemouton.audit import service as audit_service

from . import bp
from .webhooks import fire_webhook


def _default_location_id(s) -> int:
    """기본 위치 id — SO/RO 자동 처리 시 fallback."""
    loc = s.query(InventoryLocation).filter(InventoryLocation.is_default == True).first()
    if loc:
        return loc.id
    loc = s.query(InventoryLocation).filter(InventoryLocation.is_active == True).first()
    return loc.id if loc else 1


def _po_auto_inbound(s, po: PurchaseOrder) -> dict:
    """PO 완료 → 항목별 입고 InventoryTx 자동 생성 (재고 + 이동평균 갱신)."""
    items = json.loads(po.items_json or '[]')
    loc_id = _default_location_id(s)
    full_memo = (po.memo or '') + f"\n→ 자동 입고 (PO {po.po_number} 완료)"
    ok = err = 0
    for it in items:
        sku = (it.get('sku') or '').strip()
        try:
            qty = int(it.get('qty') or 0)
            price = int(it.get('unit_price') or 0)
        except (ValueError, TypeError):
            qty, price = 0, 0
        if not sku or qty <= 0:
            continue
        try:
            tx_svc.create_inbound(s, location_id=loc_id,
                                   option_canonical_sku=sku,
                                   qty=qty,
                                   unit_purchase_price=price,
                                   partner_label=po.partner_label or '',
                                   memo=full_memo,
                                   created_by=po.created_by or 'PO 자동')
            ok += 1
        except Exception:
            err += 1
    return {'ok': ok, 'err': err}


def _so_auto_outbound(s, so: SalesOrder) -> dict:
    """SO 완료 → 항목별 출고 InventoryTx 자동 생성 (재고 차감).

    Bundle SKU 입력 시 transactions._expand_bundle_lines 와 동일한 패턴으로 자동 expand.
    """
    from .transactions import _load_bundles_map, _expand_bundle_lines
    items = json.loads(so.items_json or '[]')
    raw_lines = [{'sku': it['sku'], 'qty': int(it.get('qty') or 0),
                  'price': int(it.get('unit_price') or 0)}
                 for it in items if it.get('sku') and int(it.get('qty') or 0) > 0]
    bundles = _load_bundles_map()
    expanded, expand_notes = _expand_bundle_lines(raw_lines, bundles)
    loc_id = _default_location_id(s)
    full_memo = (so.memo or '') + (('\n' if so.memo else '') + '\n'.join(expand_notes) if expand_notes else '') \
              + f"\n→ 자동 출고 (SO {so.so_number} 완료)"
    ok = err = bundle_count = 0
    for line in expanded:
        try:
            tx_svc.create_outbound(s, location_id=loc_id,
                                    option_canonical_sku=line['sku'],
                                    qty=line['qty'],
                                    unit_sale_price=line.get('price', 0),
                                    partner_label=so.partner_label or '',
                                    memo=full_memo,
                                    created_by=so.created_by or 'SO 자동')
            ok += 1
            if line.get('bundle_origin'):
                bundle_count += 1
        except Exception:
            err += 1
    return {'ok': ok, 'err': err, 'bundle_expanded': bundle_count}


def _ro_auto_inbound(s, ro: ReturnOrder) -> dict:
    """RO 완료 → 항목별 입고 InventoryTx 자동 생성 (재고 환원).

    원본 SO 의 평균매입가 (0이면 옵션 평균) 으로 입고 — 매입원가 보존.
    ReturnOrder 모델에는 partner_label 이 없어 sales_order_id 로 lookup.
    """
    items = json.loads(ro.items_json or '[]')
    loc_id = _default_location_id(s)
    # ReturnOrder partner_label 은 SO 에서 lookup
    partner = '반품 환원'
    if ro.sales_order_id:
        so_ref = s.query(SalesOrder).filter(SalesOrder.id == ro.sales_order_id).first()
        if so_ref and so_ref.partner_label:
            partner = so_ref.partner_label + ' (반품 환원)'
    full_memo = (ro.memo or '') + f"\n→ 자동 입고 환원 (RO {ro.ro_number} 완료)"
    ok = err = 0
    last_err = None
    for it in items:
        sku = (it.get('sku') or '').strip()
        try:
            qty = int(it.get('qty') or 0)
        except (ValueError, TypeError):
            qty = 0
        if not sku or qty <= 0:
            continue
        opt = s.query(Option).filter(Option.canonical_sku == sku).first()
        unit_price = int(opt.boxhero_avg_purchase_price or 0) if opt else 0
        try:
            tx_svc.create_inbound(s, location_id=loc_id,
                                   option_canonical_sku=sku,
                                   qty=qty,
                                   unit_purchase_price=unit_price,
                                   partner_label=partner,
                                   memo=full_memo,
                                   created_by=ro.created_by or 'RO 자동')
            ok += 1
        except Exception as e:
            err += 1
            last_err = str(e)
    return {'ok': ok, 'err': err, 'last_err': last_err}


def _notify(s, *, category, severity, title, body=None, link_url=None):
    """인앱 알림 1건 추가 — PARITY_720 Tier 1 (I-6)."""
    s.add(NotificationLog(
        category=category, severity=severity, title=title,
        body=body, link_url=link_url,
    ))


def _audit(s, *, table, target_id, action, actor, state):
    """감사 로그 1건 — PARITY_720 Tier 1 (E-21, Q-7)."""
    try:
        if action == 'create':
            audit_service.record_create(
                s, target_table=table, target_id=target_id,
                state=state, actor=actor or 'system',
            )
    except Exception:
        # 감사 로그 실패가 주 작업을 막지 않도록 보호
        pass


def _opt_data_all(s):
    options = (s.query(Option).order_by(Option.model_code, Option.canonical_sku).limit(500).all())
    return [{
        'sku': o.canonical_sku, 'model': o.model_code,
        'color': o.color_display or o.color_code,
        'size': o.size_display or o.size_code,
        'bh': o.boxhero_sku or '', 'stock': o.boxhero_stock_total or 0,
        'avg': o.boxhero_avg_purchase_price or 0,
    } for o in options]


def _next_number(s, model_class, prefix, attr):
    """자동 번호 생성 — PO-000001 / SO-000001 / RO-000001.

    PARITY_720 Tier 1 (A4-46, F-23) — 박스히어로 1:1 자동 시퀀스.
    """
    from sqlalchemy import desc
    last = s.query(model_class).order_by(desc(model_class.id)).first()
    n = (last.id + 1) if last else 1
    return f'{prefix}-{n:06d}'


def _parse_date(value, default=None):
    """ISO datetime-local 입력 → datetime 또는 default."""
    if not value:
        return default
    try:
        s = value.strip().replace('T', ' ')[:19]
        return datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        return default


def _apply_sort(q, model, sort_key, direction, allowed):
    """동적 ORDER BY — PARITY_720 Tier 1 (A4-53).

    allowed: {'키': model_attr} 화이트리스트.
    """
    col = allowed.get(sort_key)
    if col is None:
        col = allowed['_default']
    return q.order_by(col.desc() if direction == 'desc' else col.asc())


# ============ 구매발주 (Task 3.1) ============

@bp.get('/purchase')
def purchase_list():
    """구매발주 — 박스히어로 1:1 5세부탭 (전체/임시/대기/부분/완료)."""
    s = SessionLocal()
    try:
        status = request.args.get('status', 'all').strip() or 'all'
        sort_key = (request.args.get('sort') or 'created_at').strip()
        sort_dir = (request.args.get('dir') or 'desc').strip()
        q = s.query(PurchaseOrder)
        if status != 'all':
            q = q.filter(PurchaseOrder.status == status)
        q = _apply_sort(q, PurchaseOrder, sort_key, sort_dir, {
            '_default': PurchaseOrder.created_at,
            'created_at': PurchaseOrder.created_at,
            'po_number': PurchaseOrder.po_number,
            'partner': PurchaseOrder.partner_label,
            'status': PurchaseOrder.status,
            'order_date': PurchaseOrder.order_date,
            'due_date': PurchaseOrder.due_date,
        })
        items = q.limit(200).all()
        rows = []
        for po in items:
            try:
                its = json.loads(po.items_json) if po.items_json else []
            except (ValueError, TypeError):
                its = []
            rows.append({'po': po, 'item_count': len(its),
                         'total_qty': sum(int(i.get('qty', 0) or 0) for i in its)})
        # 5세부탭별 카운트
        from sqlalchemy import func
        counts_raw = dict(s.query(PurchaseOrder.status, func.count(PurchaseOrder.id))
                          .group_by(PurchaseOrder.status).all())
        counts = {
            'all': sum(counts_raw.values()),
            'draft': counts_raw.get('draft', 0),
            'pending': counts_raw.get('pending', 0),
            'partial': counts_raw.get('partial', 0),
            'completed': counts_raw.get('completed', 0),
        }
        return render_template('inventory/purchase_sale/purchase_list.html',
                               active='purchase', rows=rows, status=status, counts=counts,
                               sort_key=sort_key, sort_dir=sort_dir)
    finally:
        s.close()


@bp.post('/purchase/bulk')
def purchase_bulk():
    """일괄 액션 — PARITY_720 Tier 1 (D-15).

    action: 'delete' (status='cancelled' 로 soft) | 'complete' | 'pending'.
    """
    action = (request.form.get('action') or '').strip()
    ids = [int(x) for x in request.form.getlist('po_id') if x.strip().isdigit()]
    if not ids or action not in ('delete', 'complete', 'pending'):
        flash('선택 항목 또는 액션이 없습니다', 'error')
        return redirect(url_for('inventory.purchase_list'))
    s = SessionLocal()
    try:
        rows = s.query(PurchaseOrder).filter(PurchaseOrder.id.in_(ids)).all()
        restock_total = 0
        for po in rows:
            if action == 'delete':
                po.status = 'cancelled'
            elif action == 'complete':
                already_completed = (po.status == 'completed')
                po.status = 'completed'
                po.completed_at = datetime.now(timezone.utc)
                if not already_completed:
                    r = _po_auto_inbound(s, po)
                    restock_total += r.get('ok', 0)
            elif action == 'pending':
                po.status = 'pending'
            _audit(s, table='purchase_orders', target_id=po.id, action='create',
                   actor='bulk', state={'bulk_action': action})
        s.commit()
        msg = f'{len(rows)}건 {action} 처리'
        if action == 'complete' and restock_total:
            msg += f' (자동 입고 {restock_total} 라인)'
        flash(msg, 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.purchase_list'))


@bp.get('/purchase/<int:po_id>')
def purchase_detail(po_id):
    s = SessionLocal()
    try:
        po = s.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
        if not po:
            flash(f'발주 #{po_id} 없음', 'error')
            return redirect(url_for('inventory.purchase_list'))
        try:
            items = json.loads(po.items_json) if po.items_json else []
        except (ValueError, TypeError):
            items = []
        # 옵션 정보 prefetch
        skus = [i.get('sku') for i in items if i.get('sku')]
        opts = {o.canonical_sku: o for o in s.query(Option).filter(Option.canonical_sku.in_(skus)).all()} if skus else {}
        return render_template('inventory/purchase_sale/purchase_detail.html',
                               active='purchase', po=po, items=items, opts=opts)
    finally:
        s.close()


@bp.get('/purchase/new')
def purchase_new():
    s = SessionLocal()
    try:
        now_local = datetime.now().strftime('%Y-%m-%dT%H:%M')
        return render_template('inventory/purchase_sale/purchase_form.html',
                               active='purchase', opt_data=_opt_data_all(s),
                               now_local=now_local)
    finally:
        s.close()


@bp.post('/purchase/create')
def purchase_create():
    """발주 생성 — PARITY_720 Tier 1 보강 (자동번호·발주일·입고예정일·즉시처리·커스텀필드)."""
    s = SessionLocal()
    try:
        skus = request.form.getlist('sku')
        qtys = request.form.getlist('qty')
        prices = request.form.getlist('unit_price')
        items = []
        for i, sku in enumerate(skus):
            sku = sku.strip()
            if not sku:
                continue
            try:
                items.append({'sku': sku, 'qty': int(qtys[i] or 0),
                              'unit_price': int(prices[i] or 0)})
            except (ValueError, IndexError):
                continue
        if not items:
            flash('품목 1개 이상 필요', 'error')
            return redirect(url_for('inventory.purchase_new'))

        # 사용자 입력 PO 번호 우선, 없으면 자동 생성
        user_po_number = (request.form.get('po_number') or '').strip()
        po_number = user_po_number or _next_number(s, PurchaseOrder, 'PO', 'po_number')

        # 커스텀 필드 — key/value 쌍으로 들어옴
        cf_keys = request.form.getlist('cf_key')
        cf_vals = request.form.getlist('cf_value')
        custom_fields = {k.strip(): v.strip() for k, v in zip(cf_keys, cf_vals) if k.strip()}

        # 라인별 할인·세금 (박스히어로 1:1 — 라인 단위)
        line_discs = request.form.getlist('line_disc')
        line_taxes = request.form.getlist('line_tax')
        for idx, item in enumerate(items):
            try:
                item['line_disc'] = int(line_discs[idx] or 0)
                item['line_tax'] = int(line_taxes[idx] or 0)
            except (ValueError, IndexError):
                item['line_disc'] = 0
                item['line_tax'] = 0

        # 박스히어로식 액션 — [저장] / [임시 저장] 분기
        is_draft = request.form.get('save_as_draft') == '1'
        immediate = request.form.get('immediate_inbound') == 'on' and not is_draft

        po = PurchaseOrder(
            po_number=po_number,
            partner_label=request.form.get('partner_label', '').strip(),
            items_json=json.dumps(items, ensure_ascii=False),
            status='draft' if is_draft else ('completed' if immediate else 'pending'),
            tax_json=request.form.get('tax_data', '[]'),
            discount_json=request.form.get('discount_data', '[]'),
            memo=request.form.get('memo', '').strip(),
            custom_fields_json=json.dumps(custom_fields, ensure_ascii=False),
            attachment_json=request.form.get('attachment_data', '[]'),
            order_date=_parse_date(request.form.get('order_date'), datetime.now(timezone.utc)),
            due_date=_parse_date(request.form.get('due_date')),
            immediate_inbound=immediate,
            created_by=request.form.get('created_by', '운영자'),
        )
        s.add(po)
        s.flush()
        # ★ v2.1 — 즉시 입고 시 재고 자동 갱신
        restock_result = None
        if immediate:
            restock_result = _po_auto_inbound(s, po)
            po.completed_at = datetime.now(timezone.utc)
        _audit(s, table='purchase_orders', target_id=po.id, action='create',
               actor=po.created_by, state={'po_number': po.po_number,
                                            'partner': po.partner_label,
                                            'items': len(items),
                                            'immediate': immediate,
                                            'auto_restock': restock_result})
        notify_body = f"{po.partner_label or '거래처 미지정'} · {len(items)} 품목"
        if immediate and restock_result:
            notify_body += f" · 자동 입고 {restock_result['ok']} 라인"
        elif immediate:
            notify_body += ' · 즉시 입고 처리'
        _notify(s,
                category='po_completed' if immediate else 'system',
                severity='success' if immediate else 'info',
                title=f'발주 {po.po_number} 생성',
                body=notify_body,
                link_url=f'/inventory/purchase/{po.id}')
        s.commit()
        if not is_draft:
            fire_webhook('po.created', {'po_number': po.po_number, 'partner': po.partner_label, 'items': len(items), 'immediate': immediate})
        if is_draft:
            flash(f'발주 {po.po_number} 임시 저장됨', 'success')
        else:
            flash(f'발주 {po.po_number} 생성 ({len(items)} 품목)' + (' · 즉시 입고 처리됨' if immediate else ''), 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.purchase_list'))


# ============ 판매서 (Task 3.2) ============

@bp.get('/sale')
def sale_list():
    """판매 — 박스히어로 1:1 5세부탭."""
    s = SessionLocal()
    try:
        status = request.args.get('status', 'all').strip() or 'all'
        sort_key = (request.args.get('sort') or 'created_at').strip()
        sort_dir = (request.args.get('dir') or 'desc').strip()
        q = s.query(SalesOrder)
        if status != 'all':
            q = q.filter(SalesOrder.status == status)
        q = _apply_sort(q, SalesOrder, sort_key, sort_dir, {
            '_default': SalesOrder.created_at,
            'created_at': SalesOrder.created_at,
            'so_number': SalesOrder.so_number,
            'partner': SalesOrder.partner_label,
            'status': SalesOrder.status,
            'order_date': SalesOrder.order_date,
            'due_date': SalesOrder.due_date,
        })
        items = q.limit(200).all()
        rows = []
        for so in items:
            try:
                its = json.loads(so.items_json) if so.items_json else []
            except (ValueError, TypeError):
                its = []
            rows.append({'so': so, 'item_count': len(its),
                         'total_qty': sum(int(i.get('qty', 0) or 0) for i in its)})
        from sqlalchemy import func
        cr = dict(s.query(SalesOrder.status, func.count(SalesOrder.id))
                  .group_by(SalesOrder.status).all())
        counts = {'all': sum(cr.values()), 'draft': cr.get('draft', 0),
                  'pending': cr.get('pending', 0), 'partial': cr.get('partial', 0),
                  'completed': cr.get('completed', 0)}
        return render_template('inventory/purchase_sale/sale_list.html',
                               active='sale', rows=rows, status=status, counts=counts,
                               sort_key=sort_key, sort_dir=sort_dir)
    finally:
        s.close()


@bp.post('/sale/bulk')
def sale_bulk():
    action = (request.form.get('action') or '').strip()
    ids = [int(x) for x in request.form.getlist('so_id') if x.strip().isdigit()]
    if not ids or action not in ('delete', 'complete', 'pending'):
        flash('선택 항목 또는 액션이 없습니다', 'error')
        return redirect(url_for('inventory.sale_list'))
    s = SessionLocal()
    try:
        rows = s.query(SalesOrder).filter(SalesOrder.id.in_(ids)).all()
        deduct_total = 0
        for so in rows:
            if action == 'delete':
                so.status = 'cancelled'
            elif action == 'complete':
                # ★ v2.0 — 일괄 완료 처리 시 재고 자동 차감 (이미 완료된 SO 는 skip)
                already_completed = (so.status == 'completed')
                so.status = 'completed'
                so.completed_at = datetime.now(timezone.utc)
                if not already_completed:
                    r = _so_auto_outbound(s, so)
                    deduct_total += r.get('ok', 0)
            elif action == 'pending':
                so.status = 'pending'
            _audit(s, table='sales_orders', target_id=so.id, action='create',
                   actor='bulk', state={'bulk_action': action})
        s.commit()
        msg = f'{len(rows)}건 {action} 처리'
        if action == 'complete' and deduct_total:
            msg += f' (자동 출고 차감 {deduct_total} 라인)'
        flash(msg, 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.sale_list'))


@bp.get('/sale/<int:so_id>')
def sale_detail(so_id):
    s = SessionLocal()
    try:
        so = s.query(SalesOrder).filter(SalesOrder.id == so_id).first()
        if not so:
            flash(f'판매 #{so_id} 없음', 'error')
            return redirect(url_for('inventory.sale_list'))
        try:
            items = json.loads(so.items_json) if so.items_json else []
        except (ValueError, TypeError):
            items = []
        skus = [i.get('sku') for i in items if i.get('sku')]
        opts = {o.canonical_sku: o for o in s.query(Option).filter(Option.canonical_sku.in_(skus)).all()} if skus else {}
        return render_template('inventory/purchase_sale/sale_detail.html',
                               active='sale', so=so, items=items, opts=opts)
    finally:
        s.close()


@bp.get('/sale/new')
def sale_new():
    s = SessionLocal()
    try:
        now_local = datetime.now().strftime('%Y-%m-%dT%H:%M')
        return render_template('inventory/purchase_sale/sale_form.html',
                               active='sale', opt_data=_opt_data_all(s),
                               now_local=now_local)
    finally:
        s.close()


@bp.post('/sale/create')
def sale_create():
    """판매 생성 — PARITY_720 Tier 1 보강."""
    s = SessionLocal()
    try:
        skus = request.form.getlist('sku')
        qtys = request.form.getlist('qty')
        prices = request.form.getlist('unit_price')
        items = []
        for i, sku in enumerate(skus):
            sku = sku.strip()
            if not sku:
                continue
            try:
                items.append({'sku': sku, 'qty': int(qtys[i] or 0),
                              'unit_price': int(prices[i] or 0)})
            except (ValueError, IndexError):
                continue
        if not items:
            flash('품목 1개 이상 필요', 'error')
            return redirect(url_for('inventory.sale_new'))

        user_so_number = (request.form.get('so_number') or '').strip()
        so_number = user_so_number or _next_number(s, SalesOrder, 'SO', 'so_number')
        cf_keys = request.form.getlist('cf_key')
        cf_vals = request.form.getlist('cf_value')
        custom_fields = {k.strip(): v.strip() for k, v in zip(cf_keys, cf_vals) if k.strip()}
        # 라인별 할인·세금 (박스히어로 1:1)
        line_discs = request.form.getlist('line_disc')
        line_taxes = request.form.getlist('line_tax')
        for idx, item in enumerate(items):
            try:
                item['line_disc'] = int(line_discs[idx] or 0)
                item['line_tax'] = int(line_taxes[idx] or 0)
            except (ValueError, IndexError):
                item['line_disc'] = 0
                item['line_tax'] = 0
        is_draft = request.form.get('save_as_draft') == '1'
        immediate = request.form.get('immediate_outbound') == 'on' and not is_draft

        so = SalesOrder(
            so_number=so_number,
            partner_label=request.form.get('partner_label', '').strip(),
            items_json=json.dumps(items, ensure_ascii=False),
            status='draft' if is_draft else ('completed' if immediate else 'pending'),
            tax_json=request.form.get('tax_data', '[]'),
            discount_json=request.form.get('discount_data', '[]'),
            memo=request.form.get('memo', '').strip(),
            custom_fields_json=json.dumps(custom_fields, ensure_ascii=False),
            attachment_json=request.form.get('attachment_data', '[]'),
            order_date=_parse_date(request.form.get('order_date'), datetime.now(timezone.utc)),
            due_date=_parse_date(request.form.get('due_date')),
            immediate_outbound=immediate,
            created_by=request.form.get('created_by', '운영자'),
        )
        s.add(so)
        s.flush()
        # ★ v2.0 — 즉시 출고 시 재고 자동 차감
        deduct_result = None
        if immediate:
            deduct_result = _so_auto_outbound(s, so)
        _audit(s, table='sales_orders', target_id=so.id, action='create',
               actor=so.created_by, state={'so_number': so.so_number,
                                            'partner': so.partner_label,
                                            'items': len(items),
                                            'immediate': immediate,
                                            'auto_deduct': deduct_result})
        notify_body = f"{so.partner_label or '고객 미지정'} · {len(items)} 품목"
        if immediate and deduct_result:
            notify_body += f" · 자동 출고 차감 {deduct_result['ok']} 라인"
            if deduct_result.get('bundle_expanded'):
                notify_body += f" (묶음 {deduct_result['bundle_expanded']})"
        elif immediate:
            notify_body += ' · 즉시 출고 처리'
        _notify(s, category='system',
                severity='success' if immediate else 'info',
                title=f'판매 {so.so_number} 생성',
                body=notify_body,
                link_url=f'/inventory/sale/{so.id}')
        s.commit()
        if not is_draft:
            fire_webhook('so.created', {'so_number': so.so_number, 'partner': so.partner_label, 'items': len(items), 'immediate': immediate})
        flash(f'판매 {so.so_number} ' + ('임시 저장됨' if is_draft else '생성'), 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.sale_list'))


# ============ 반품 (Task 3.3) ============

@bp.get('/return')
def return_list():
    """반품 — 박스히어로 1:1 4세부탭."""
    s = SessionLocal()
    try:
        status = request.args.get('status', 'all').strip() or 'all'
        sort_key = (request.args.get('sort') or 'created_at').strip()
        sort_dir = (request.args.get('dir') or 'desc').strip()
        q = s.query(ReturnOrder)
        if status != 'all':
            q = q.filter(ReturnOrder.status == status)
        q = _apply_sort(q, ReturnOrder, sort_key, sort_dir, {
            '_default': ReturnOrder.created_at,
            'created_at': ReturnOrder.created_at,
            'ro_number': ReturnOrder.ro_number,
            'status': ReturnOrder.status,
            'return_date': ReturnOrder.return_date,
            'refund_amount': ReturnOrder.refund_amount,
        })
        items = q.limit(200).all()
        rows = []
        for ro in items:
            try:
                its = json.loads(ro.items_json) if ro.items_json else []
            except (ValueError, TypeError):
                its = []
            rows.append({'ro': ro, 'item_count': len(its),
                         'total_qty': sum(int(i.get('qty', 0) or 0) for i in its)})
        from sqlalchemy import func
        cr = dict(s.query(ReturnOrder.status, func.count(ReturnOrder.id))
                  .group_by(ReturnOrder.status).all())
        counts = {'all': sum(cr.values()), 'draft': cr.get('draft', 0),
                  'pending': cr.get('pending', 0), 'completed': cr.get('completed', 0)}
        return render_template('inventory/purchase_sale/return_list.html',
                               active='return', rows=rows, status=status, counts=counts,
                               sort_key=sort_key, sort_dir=sort_dir)
    finally:
        s.close()


@bp.post('/return/bulk')
def return_bulk():
    action = (request.form.get('action') or '').strip()
    ids = [int(x) for x in request.form.getlist('ro_id') if x.strip().isdigit()]
    if not ids or action not in ('delete', 'complete', 'pending'):
        flash('선택 항목 또는 액션이 없습니다', 'error')
        return redirect(url_for('inventory.return_list'))
    s = SessionLocal()
    try:
        rows = s.query(ReturnOrder).filter(ReturnOrder.id.in_(ids)).all()
        restock_total = 0
        for ro in rows:
            if action == 'delete':
                ro.status = 'cancelled'
            elif action == 'complete':
                # ★ v2.0 — 일괄 완료 시 재고 자동 환원 (반품 → 입고)
                already_completed = (ro.status == 'completed')
                ro.status = 'completed'
                ro.completed_at = datetime.now(timezone.utc)
                if not already_completed:
                    r = _ro_auto_inbound(s, ro)
                    restock_total += r.get('ok', 0)
            elif action == 'pending':
                ro.status = 'pending'
            _audit(s, table='return_orders', target_id=ro.id, action='create',
                   actor='bulk', state={'bulk_action': action})
        s.commit()
        msg = f'{len(rows)}건 {action} 처리'
        if action == 'complete' and restock_total:
            msg += f' (자동 입고 환원 {restock_total} 라인)'
        flash(msg, 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.return_list'))


@bp.get('/return/<int:ro_id>')
def return_detail(ro_id):
    s = SessionLocal()
    try:
        ro = s.query(ReturnOrder).filter(ReturnOrder.id == ro_id).first()
        if not ro:
            flash(f'반품 #{ro_id} 없음', 'error')
            return redirect(url_for('inventory.return_list'))
        try:
            items = json.loads(ro.items_json) if ro.items_json else []
        except (ValueError, TypeError):
            items = []
        skus = [i.get('sku') for i in items if i.get('sku')]
        opts = {o.canonical_sku: o for o in s.query(Option).filter(Option.canonical_sku.in_(skus)).all()} if skus else {}
        so = s.query(SalesOrder).filter(SalesOrder.id == ro.sales_order_id).first() if ro.sales_order_id else None
        return render_template('inventory/purchase_sale/return_detail.html',
                               active='return', ro=ro, items=items, opts=opts, so=so)
    finally:
        s.close()


@bp.get('/return/new')
def return_new():
    s = SessionLocal()
    try:
        sales = s.query(SalesOrder).order_by(SalesOrder.created_at.desc()).limit(50).all()
        now_local = datetime.now().strftime('%Y-%m-%dT%H:%M')
        return render_template('inventory/purchase_sale/return_form.html',
                               active='return', sales=sales, opt_data=_opt_data_all(s),
                               now_local=now_local)
    finally:
        s.close()


@bp.post('/return/create')
def return_create():
    """반품 생성 — PARITY_720 Tier 1 보강."""
    s = SessionLocal()
    try:
        sales_order_id_raw = request.form.get('sales_order_id', '').strip()
        sales_order_id = int(sales_order_id_raw) if sales_order_id_raw else None
        skus = request.form.getlist('sku')
        qtys = request.form.getlist('qty')
        items = []
        for i, sku in enumerate(skus):
            sku = sku.strip()
            if not sku:
                continue
            try:
                items.append({'sku': sku, 'qty': int(qtys[i] or 0)})
            except (ValueError, IndexError):
                continue

        user_ro_number = (request.form.get('ro_number') or '').strip()
        ro_number = user_ro_number or _next_number(s, ReturnOrder, 'RO', 'ro_number')
        try:
            refund_amount = int(request.form.get('refund_amount', 0) or 0)
        except ValueError:
            refund_amount = 0

        cf_keys = request.form.getlist('cf_key')
        cf_vals = request.form.getlist('cf_value')
        custom_fields = {k.strip(): v.strip() for k, v in zip(cf_keys, cf_vals) if k.strip()}
        is_draft = request.form.get('save_as_draft') == '1'
        immediate = request.form.get('immediate_inbound') == 'on' and not is_draft

        ro = ReturnOrder(
            ro_number=ro_number,
            sales_order_id=sales_order_id,
            items_json=json.dumps(items, ensure_ascii=False),
            status='draft' if is_draft else ('completed' if immediate else 'pending'),
            memo=request.form.get('memo', '').strip(),
            custom_fields_json=json.dumps(custom_fields, ensure_ascii=False),
            attachment_json=request.form.get('attachment_data', '[]'),
            return_date=_parse_date(request.form.get('return_date'), datetime.now(timezone.utc)),
            refund_amount=refund_amount,
            created_by=request.form.get('created_by', '운영자'),
        )
        s.add(ro)
        s.flush()
        # ★ v2.0 — 즉시 환원 입고 (반품 → 재고 자동 입고)
        restock_result = None
        if immediate:
            restock_result = _ro_auto_inbound(s, ro)
            ro.completed_at = datetime.now(timezone.utc)
        _audit(s, table='return_orders', target_id=ro.id, action='create',
               actor=ro.created_by, state={'ro_number': ro.ro_number,
                                            'sales_order_id': sales_order_id,
                                            'items': len(items),
                                            'refund_amount': refund_amount,
                                            'immediate_inbound': immediate,
                                            'auto_restock': restock_result})
        notify_body = f"{len(items)} 품목 · 환불 {refund_amount:,}원"
        if immediate and restock_result:
            notify_body += f" · 자동 입고 환원 {restock_result['ok']} 라인"
        _notify(s, category='system', severity='warning',
                title=f'반품 {ro.ro_number} 생성',
                body=notify_body,
                link_url=f'/inventory/return/{ro.id}')
        s.commit()
        if not is_draft:
            fire_webhook('ro.created', {'ro_number': ro.ro_number, 'sales_order_id': sales_order_id, 'items': len(items), 'refund_amount': refund_amount})
        flash(f'반품 {ro.ro_number} ' + ('임시 저장됨' if is_draft else '생성'), 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.return_list'))
