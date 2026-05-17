"""[v17] 모음전 ↔ 재고관리 연동 API.

- GET /api/options/<sku>/stock-history?limit=N  → 최근 N건 입출고/조정 이력
- GET /api/options/stock-history-bulk           → 다수 SKU 한 번에 (?skus=a,b,c&limit=3)
- (Phase 5에서 추가): POST /api/options/<sku>/stock-mode, POST /api/options/<sku>/inventory-product 등

본 파일은 Phase 3 시점에 InventoryTx 테이블만 활용 (DB 변경 없음).
"""
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from sqlalchemy import desc

from shared.db import SessionLocal
from lemouton.inventory.models import InventoryTx, InventoryLocation, InventoryProduct
from lemouton.sourcing.models_pricing import OptionPriceConfig


bp = Blueprint('api_inventory_link', __name__, url_prefix='/api/options')


# ─── 팀공유 모드: admin 전용 (재고 연동 = 시스템 매핑, 회색지대 → admin). 기존 모드 통과. ───
@bp.before_request
def _admin_only():
    import os
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


_TX_TYPE_LABEL = {
    'in': '입고',
    'out': '출고',
    'adjust': '조정',
    'move': '이동',
}


def _fmt_rel_time(dt):
    """간단한 상대 시각 (예: '5분 전', '2h 전', '1d 전')."""
    if not dt:
        return ''
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    # naive datetime → assume UTC
    if dt.tzinfo is None:
        from datetime import timezone as _tz
        dt = dt.replace(tzinfo=_tz.utc)
    diff = now - dt
    s = int(diff.total_seconds())
    if s < 60:
        return f'{s}초 전'
    if s < 3600:
        return f'{s // 60}분 전'
    if s < 86400:
        return f'{s // 3600}h 전'
    return f'{s // 86400}d 전'


def _serialize_tx(tx):
    """InventoryTx → dict (B1 이력 표시용)."""
    return {
        'id': tx.id,
        'type': tx.tx_type,  # 'in'|'out'|'adjust'|'move'
        'type_label': _TX_TYPE_LABEL.get(tx.tx_type, tx.tx_type),
        'qty': tx.qty,
        'qty_signed': (-tx.qty if tx.tx_type == 'out' else tx.qty),
        'memo': tx.memo or '',
        'when_rel': _fmt_rel_time(tx.created_at),
        'when_iso': tx.created_at.isoformat() if tx.created_at else None,
        'created_by': tx.created_by or '',
    }


@bp.get('/<path:sku>/stock-history')
def get_stock_history(sku):
    """단일 옵션의 최근 N건 입출고/조정 이력."""
    limit = max(1, min(int(request.args.get('limit', 3)), 50))
    db = SessionLocal()
    try:
        rows = (db.query(InventoryTx)
                .filter(InventoryTx.option_canonical_sku == sku)
                .filter(InventoryTx.status == 'completed')
                .order_by(desc(InventoryTx.created_at))
                .limit(limit)
                .all())
        items = [_serialize_tx(r) for r in rows]
        # 총 카운트 (별도 쿼리)
        total = (db.query(InventoryTx)
                 .filter(InventoryTx.option_canonical_sku == sku)
                 .filter(InventoryTx.status == 'completed')
                 .count())
        return jsonify({'ok': True, 'sku': sku, 'items': items, 'total': total})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        db.close()


@bp.post('/<path:sku>/stock-adjust')
def stock_adjust(sku):
    """재고 조정 — manual_stock 갱신 + InventoryTx (tx_type='adjust') 자동 생성.

    body: { qty_after: int, prev_qty: int, memo: str }
    """
    data = request.get_json(silent=True) or {}
    if 'qty_after' not in data:
        return jsonify({'ok': False, 'error': 'qty_after required'}), 400
    qty_after = int(data['qty_after'])
    prev_qty = int(data.get('prev_qty') or 0)
    memo = (data.get('memo') or '').strip()
    diff = qty_after - prev_qty

    db = SessionLocal()
    try:
        # 1) OptionPriceConfig 갱신 (manual_stock)
        cfg = db.query(OptionPriceConfig).filter_by(canonical_sku=sku).first()
        if cfg is None:
            cfg = OptionPriceConfig(canonical_sku=sku, manual_stock=qty_after)
            db.add(cfg)
        else:
            cfg.manual_stock = qty_after

        # 2) InventoryTx 생성 (adjust type)
        # 기본 위치 찾기 (없으면 첫 위치)
        loc = db.query(InventoryLocation).filter_by(is_default=True).first()
        if loc is None:
            loc = db.query(InventoryLocation).order_by(InventoryLocation.id).first()

        # auto memo prefix (사용자 메모 + 변경량 자동 첨부)
        date_str = datetime.now(timezone.utc).strftime('%y.%m.%d')
        auto_prefix = f"{date_str} 변경전 {prev_qty}개 → 변경후 {qty_after}개"
        full_memo = f"{auto_prefix}\n{memo}" if memo else auto_prefix

        tx = InventoryTx(
            tx_type='adjust',
            location_id=loc.id if loc else None,
            option_canonical_sku=sku,
            qty=diff,  # 조정량 (음수 가능)
            memo=full_memo,
            source='local',
            status='completed',
            created_at=datetime.now(timezone.utc),
        )
        db.add(tx)
        db.commit()
        return jsonify({
            'ok': True,
            'sku': sku,
            'manual_stock': qty_after,
            'tx_id': tx.id,
            'diff': diff,
        })
    except Exception as e:
        db.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        db.close()


# ============ v17 C1 — 재고관리 제품 (InventoryProduct) ============

_INV_PRODUCT_FIELDS = (
    'option_name', 'model_code', 'color_code', 'size_code', 'brand',
    'category', 'sub_category', 'barcode', 'supplier', 'purchase_date',
    'location_id', 'purchase_price', 'sale_price',
    'initial_stock', 'safety_stock', 'memo',
)


def _serialize_inv_product(p):
    return {
        'id': p.id,
        'canonical_sku': p.canonical_sku,
        'option_name': p.option_name,
        'model_code': p.model_code,
        'color_code': p.color_code,
        'size_code': p.size_code,
        'brand': p.brand,
        'category': p.category,
        'sub_category': p.sub_category,
        'barcode': p.barcode,
        'supplier': p.supplier,
        'purchase_date': p.purchase_date,
        'location_id': p.location_id,
        'purchase_price': p.purchase_price,
        'sale_price': p.sale_price,
        'initial_stock': p.initial_stock,
        'safety_stock': p.safety_stock,
        'memo': p.memo,
        'status': p.status,
        'created_at': p.created_at.isoformat() if p.created_at else None,
        'updated_at': p.updated_at.isoformat() if p.updated_at else None,
        'completed_at': p.completed_at.isoformat() if p.completed_at else None,
    }


@bp.get('/<path:sku>/inventory-product')
def get_inv_product(sku):
    """기존 InventoryProduct 조회 (draft 또는 completed)."""
    db = SessionLocal()
    try:
        p = db.query(InventoryProduct).filter_by(canonical_sku=sku).first()
        if not p:
            return jsonify({'ok': True, 'product': None, 'exists': False})
        return jsonify({'ok': True, 'product': _serialize_inv_product(p), 'exists': True})
    finally:
        db.close()


@bp.post('/<path:sku>/inventory-product/autosave')
def autosave_inv_product(sku):
    """폼 부분 자동 저장 — draft 생성 또는 기존 draft 업데이트.

    body: { field_name: value, ... } — 변경된 필드만 보내도 됨.
    """
    data = request.get_json(silent=True) or {}
    db = SessionLocal()
    try:
        p = db.query(InventoryProduct).filter_by(canonical_sku=sku).first()
        is_new = p is None
        if is_new:
            p = InventoryProduct(
                canonical_sku=sku,
                status='draft',
            )
            db.add(p)
            db.flush()
        # 자동 매핑 필드 (모음전 옵션에서) + 사용자 입력 필드
        for f in _INV_PRODUCT_FIELDS:
            if f in data:
                v = data[f]
                # 빈 문자열 → None
                if isinstance(v, str) and v == '':
                    v = None
                # 숫자 필드 자동 변환
                if f in ('location_id', 'purchase_price', 'sale_price', 'initial_stock', 'safety_stock'):
                    if v is not None and v != '':
                        try:
                            v = int(v)
                        except (ValueError, TypeError):
                            v = None
                setattr(p, f, v)
        p.updated_at = datetime.now(timezone.utc)
        db.commit()
        return jsonify({'ok': True, 'product': _serialize_inv_product(p), 'is_new': is_new})
    except Exception as e:
        db.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        db.close()


@bp.post('/<path:sku>/inventory-product/complete')
def complete_inv_product(sku):
    """draft → completed 전환 + 초기 재고 InventoryTx (tx_type='in') 생성."""
    db = SessionLocal()
    try:
        p = db.query(InventoryProduct).filter_by(canonical_sku=sku).first()
        if not p:
            return jsonify({'ok': False, 'error': '제품이 없습니다. 먼저 자동저장 폼을 작성하세요.'}), 404
        # 필수 필드 검증
        if not p.category:
            return jsonify({'ok': False, 'error': '카테고리는 필수입니다.'}), 400
        # 초기 재고 InventoryTx 생성 (qty > 0 시)
        tx_id = None
        if p.initial_stock and p.initial_stock > 0:
            tx = InventoryTx(
                tx_type='in',
                location_id=p.location_id,
                option_canonical_sku=sku,
                qty=p.initial_stock,
                memo=f'재고관리 제품 신규 생성 · 초기 입고\n매입처: {p.supplier or "-"}',
                source='local',
                status='completed',
                created_at=datetime.now(timezone.utc),
                partner_label=p.supplier,
            )
            db.add(tx)
            db.flush()
            tx_id = tx.id
            # OptionPriceConfig.manual_stock 도 갱신
            cfg = db.query(OptionPriceConfig).filter_by(canonical_sku=sku).first()
            if cfg is None:
                cfg = OptionPriceConfig(canonical_sku=sku, manual_stock=p.initial_stock)
                db.add(cfg)
            else:
                cfg.manual_stock = p.initial_stock
        # 상태 전환
        p.status = 'completed'
        p.completed_at = datetime.now(timezone.utc)
        db.commit()
        return jsonify({
            'ok': True, 'product': _serialize_inv_product(p),
            'initial_tx_id': tx_id,
        })
    except Exception as e:
        db.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        db.close()


@bp.get('/inventory-locations')
def list_inv_locations():
    """재고관리 위치 목록 (드롭다운용)."""
    db = SessionLocal()
    try:
        rows = (db.query(InventoryLocation)
                .filter(InventoryLocation.deleted_at.is_(None))
                .order_by(InventoryLocation.sort_order, InventoryLocation.id)
                .all())
        items = [{'id': r.id, 'name': r.name, 'is_default': r.is_default} for r in rows]
        return jsonify({'ok': True, 'locations': items})
    finally:
        db.close()


@bp.post('/stock-history-bulk')
def get_stock_history_bulk():
    """여러 SKU 의 최근 이력 한 번에. body = {skus: [...], limit: 3}."""
    data = request.get_json(silent=True) or {}
    skus = data.get('skus') or []
    limit = max(1, min(int(data.get('limit', 3)), 10))
    if not isinstance(skus, list) or not skus:
        return jsonify({'ok': False, 'error': 'skus required'}), 400

    db = SessionLocal()
    try:
        result = {}
        # 단순 구현 — N+1 쿼리. 옵션 수 ~50 미만이면 OK
        for sku in skus:
            rows = (db.query(InventoryTx)
                    .filter(InventoryTx.option_canonical_sku == sku)
                    .filter(InventoryTx.status == 'completed')
                    .order_by(desc(InventoryTx.created_at))
                    .limit(limit)
                    .all())
            total = (db.query(InventoryTx)
                     .filter(InventoryTx.option_canonical_sku == sku)
                     .filter(InventoryTx.status == 'completed')
                     .count())
            result[sku] = {
                'items': [_serialize_tx(r) for r in rows],
                'total': total,
            }
        return jsonify({'ok': True, 'results': result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        db.close()
