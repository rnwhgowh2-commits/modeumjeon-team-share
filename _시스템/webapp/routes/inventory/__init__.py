"""[I] 재고관리 탭 — Blueprint 등록.

R1 박스히어로 1:1 복제 + ADR-004 상단 탭 swap + ADR-005 단독 운영.
URL prefix: /inventory/

ai-workflow STEP 7 Sprint 0 Task 0.4
sub-routes는 추후 task 에서 별도 모듈로 분리 (Sprint 1~4).
"""
from flask import Blueprint, render_template, request
from sqlalchemy import or_

bp = Blueprint('inventory', __name__, url_prefix='/inventory')


@bp.get('/')
def home():
    """제품목록 (메인) — 박스히어로 1:1 좌측 list + 우측 상세 패널 + 필터."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option, Model
    from lemouton.inventory.models import InventoryLocation, InventoryTx
    from sqlalchemy import func
    s = SessionLocal()
    try:
        in_stock_only = request.args.get('in_stock') == '1'
        group_by_model = request.args.get('group_by_model') == '1'
        search_q = (request.args.get('q') or '').strip()
        location_filter = request.args.get('location_id', '').strip()
        selected_sku = request.args.get('sku', '').strip()

        q = s.query(Option)
        if in_stock_only:
            q = q.filter(Option.boxhero_stock_total > 0)
        # ★ 박스히어로식 다중 키워드 AND 교집합 필터
        # ?q=르무통 메이트 그레이  → 각 토큰을 AND 로 묶음, 토큰 안에서는 canonical_sku 또는 boxhero_sku OR
        search_tokens = [t for t in (search_q.split() if search_q else []) if t]
        for tok in search_tokens:
            like = f'%{tok}%'
            q = q.filter(or_(Option.canonical_sku.like(like), Option.boxhero_sku.like(like)))

        # ★ stats 는 limit 적용 전 전체 카운트로 계산 (UI 표시 limit 500 과 분리)
        from sqlalchemy import case
        stats_row = q.with_entities(
            func.count(Option.canonical_sku),
            func.coalesce(func.sum(case((Option.boxhero_stock_total > 0, 1), else_=0)), 0),
            func.coalesce(func.sum(Option.boxhero_stock_total), 0),
            func.coalesce(func.sum(case((Option.boxhero_sku.isnot(None), 1), else_=0)), 0),
        ).one()
        stats_total, stats_in_stock, stats_total_stock, stats_mapped = stats_row

        options = q.order_by(Option.model_code, Option.sort_order, Option.canonical_sku).limit(500).all()

        # 묶어보기 — model_code별 그룹
        grouped = {}
        if group_by_model:
            for o in options:
                grouped.setdefault(o.model_code, []).append(o)

        # 우측 상세 패널 데이터 (선택된 SKU)
        selected_detail = None
        if selected_sku:
            opt = s.query(Option).filter(Option.canonical_sku == selected_sku).first()
            if opt:
                model = s.query(Model).filter(Model.model_code == opt.model_code).first()
                # 위치별 재고 (Tx 누적)
                locs = s.query(InventoryLocation).filter(InventoryLocation.deleted_at.is_(None)).all()
                loc_stock = {}
                for loc in locs:
                    in_q = s.query(func.sum(InventoryTx.qty)).filter(
                        InventoryTx.option_canonical_sku == selected_sku,
                        InventoryTx.location_id == loc.id,
                        InventoryTx.tx_type == 'in',
                    ).scalar() or 0
                    out_q = s.query(func.sum(InventoryTx.qty)).filter(
                        InventoryTx.option_canonical_sku == selected_sku,
                        InventoryTx.location_id == loc.id,
                        InventoryTx.tx_type == 'out',
                    ).scalar() or 0
                    move_in = s.query(func.sum(InventoryTx.qty)).filter(
                        InventoryTx.option_canonical_sku == selected_sku,
                        InventoryTx.location_to_id == loc.id,
                        InventoryTx.tx_type == 'move',
                    ).scalar() or 0
                    move_out = s.query(func.sum(InventoryTx.qty)).filter(
                        InventoryTx.option_canonical_sku == selected_sku,
                        InventoryTx.location_id == loc.id,
                        InventoryTx.tx_type == 'move',
                    ).scalar() or 0
                    loc_stock[loc.id] = {'name': loc.name, 'stock': in_q - out_q + move_in - move_out}
                selected_detail = {'opt': opt, 'model': model, 'loc_stock': loc_stock}

        # 위치 드롭다운
        all_locs = s.query(InventoryLocation).filter(InventoryLocation.deleted_at.is_(None)).all()

        # 통계 (DB 전체 카운트 — limit 500 영향 없음)
        stats = {
            'total': int(stats_total or 0),
            'in_stock_count': int(stats_in_stock or 0),
            'total_stock': int(stats_total_stock or 0),
            'mapped': int(stats_mapped or 0),
            'shown': len(options),
            'shown_limited': len(options) >= 500 and int(stats_total or 0) > 500,
        }

        return render_template(
            'inventory/home.html',
            active_app='inventory', active='items',
            options=options, grouped=grouped, group_by_model=group_by_model,
            in_stock_only=in_stock_only, search_q=search_q,
            search_tokens=search_tokens,
            selected_detail=selected_detail, all_locs=all_locs,
            location_filter=location_filter, stats=stats,
        )
    finally:
        s.close()


@bp.context_processor
def inject_active_app():
    """모든 /inventory/* 페이지에 active_app='inventory' 자동 주입."""
    return {'active_app': 'inventory'}


# ★ sub-route 모듈 import — bp에 라우트 데코레이터 등록 (Sprint 1A 이후 점진 추가)
from . import data  # noqa: E402  (Sprint 1A Task 1.2~1.6 — 데이터 마스터)
from . import boxhero_import  # noqa: E402  (Sprint 1B Task 1.9 — 박스히어로 import)
from . import sku_mapping  # noqa: E402  (Sprint 1B Task 1.8 — SKU 매핑 큐)
from . import transactions  # noqa: E402  (Sprint 2 Task 2.1~2.5 — 입출고·조정·이동·히스토리)
from . import matrix  # noqa: E402  (Sprint 2 Task 2.6 ★★★ — 옵션 매트릭스 R2 핵심)
from . import inspection  # noqa: E402  (Sprint 2 Task 2.7 — 입고 검사)
from . import purchase_sale  # noqa: E402  (Sprint 3 Task 3.1~3.3 — 발주·판매·반품)
from . import reports  # noqa: E402  (Sprint 3 Task 3.4~3.6 — 재고조사·알림·공유링크)
from . import barcode  # noqa: E402  (Sprint 3 Task 3.7 — 바코드)
from . import settings  # noqa: E402  (Sprint 3 Task 3.8 — 설정)
from . import notifications  # noqa: E402  (PARITY_720 Tier 1 — 알림 + 자동완성)
from . import webhooks  # noqa: E402  (PARITY_720 Tier 1 — Webhook + Alert)
