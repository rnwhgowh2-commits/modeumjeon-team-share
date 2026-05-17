"""[I] /inventory/inspection — 입고 검사 (박스히어로 R1 복제).

ai-workflow STEP 7 Sprint 2 Task 2.7

흐름:
  PurchaseOrder (status=pending|partial) → 입고 검사 페이지 → 실제 입고 수량 입력
  → 차이 발생 시 차이만큼 조정 메모 + 입고 Tx 생성 + PO status 업데이트
"""
import json
from datetime import datetime, timezone

from flask import render_template, request, redirect, url_for, flash, jsonify

from shared.db import SessionLocal
from lemouton.inventory.models import PurchaseOrder, InventoryLocation
from lemouton.inventory import inbound as tx_svc

from . import bp


@bp.get('/inspection')
def inspection_list():
    """입고 검사 — 검수 대기 PO 리스트."""
    s = SessionLocal()
    try:
        pos = (s.query(PurchaseOrder)
               .filter(PurchaseOrder.status.in_(['pending', 'partial']))
               .order_by(PurchaseOrder.created_at.desc())
               .limit(100).all())

        # 완료/취소도 최근 20개 하단 표시
        recent_done = (s.query(PurchaseOrder)
                       .filter(PurchaseOrder.status.in_(['completed', 'draft']))
                       .order_by(PurchaseOrder.completed_at.desc().nullslast(),
                                 PurchaseOrder.created_at.desc())
                       .limit(20).all())

        # items_json parse
        def parse(po):
            try:
                items = json.loads(po.items_json) if po.items_json else []
            except (ValueError, TypeError):
                items = []
            return {'po': po, 'items': items, 'item_count': len(items),
                    'total_qty': sum(int(i.get('qty', 0) or 0) for i in items)}

        return render_template(
            'inventory/inspection.html',
            active='inspection',
            pending=[parse(p) for p in pos],
            recent=[parse(p) for p in recent_done],
        )
    finally:
        s.close()


@bp.get('/inspection/<int:po_id>')
def inspection_detail(po_id):
    """검사 상세 — 라인별 예상 vs 실제 입력."""
    s = SessionLocal()
    try:
        po = s.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
        if not po:
            flash(f'발주 {po_id} 없음', 'error')
            return redirect(url_for('inventory.inspection_list'))
        try:
            items = json.loads(po.items_json) if po.items_json else []
        except (ValueError, TypeError):
            items = []

        from lemouton.inventory.locations import list_active
        locations = list_active(s)

        return render_template(
            'inventory/inspection_detail.html',
            active='inspection', po=po, items=items, locations=locations,
        )
    finally:
        s.close()


@bp.post('/inspection/<int:po_id>/process')
def inspection_process(po_id):
    """검사 처리 — 라인별 received_qty 입력 → 입고 Tx 생성 + PO 상태 업데이트."""
    s = SessionLocal()
    try:
        po = s.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
        if not po:
            flash(f'발주 {po_id} 없음', 'error')
            return redirect(url_for('inventory.inspection_list'))

        try:
            items = json.loads(po.items_json) if po.items_json else []
        except (ValueError, TypeError):
            items = []

        location_id = int(request.form['location_id'])
        memo_base = request.form.get('memo', '').strip() or f'PO #{po.id} 입고 검사'
        all_full = True
        any_received = False
        errors = []

        for idx, item in enumerate(items):
            sku = item.get('sku')
            expected = int(item.get('qty', 0) or 0)
            received_raw = request.form.get(f'received_{idx}', '').strip()
            if not received_raw:
                continue
            try:
                received = int(received_raw)
            except ValueError:
                errors.append(f'{sku}: 잘못된 수량')
                continue
            if received < 0:
                errors.append(f'{sku}: 음수 불가')
                continue
            if received != expected:
                all_full = False
            if received > 0:
                any_received = True
                diff_memo = (f'{memo_base} (예상 {expected} → 실제 {received}'
                             + (', 차이 ⚠' if received != expected else '') + ')')
                try:
                    tx_svc.create_inbound(
                        s, location_id=location_id,
                        option_canonical_sku=sku, qty=received,
                        unit_purchase_price=int(item.get('unit_price', 0) or 0),
                        partner_label=po.partner_label or '',
                        memo=diff_memo,
                        created_by=request.form.get('created_by', '검사'),
                    )
                except (ValueError, KeyError) as e:
                    errors.append(f'{sku}: {e}')

        if errors:
            s.rollback()
            flash('검사 실패: ' + '; '.join(errors), 'error')
            return redirect(url_for('inventory.inspection_detail', po_id=po_id))

        # PO 상태 업데이트
        if any_received:
            po.status = 'completed' if all_full else 'partial'
            if po.status == 'completed':
                po.completed_at = datetime.now(timezone.utc)
        s.commit()
        flash(f'검사 처리 — PO #{po.id} {po.status}', 'success')
        return redirect(url_for('inventory.inspection_list'))
    finally:
        s.close()
