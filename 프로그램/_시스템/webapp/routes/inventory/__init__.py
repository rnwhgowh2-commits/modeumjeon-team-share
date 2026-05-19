"""[I] 재고관리 탭 — Blueprint 등록.

R1 박스히어로 1:1 복제 + ADR-004 상단 탭 swap + ADR-005 단독 운영.
URL prefix: /inventory/

ai-workflow STEP 7 Sprint 0 Task 0.4
sub-routes는 추후 task 에서 별도 모듈로 분리 (Sprint 1~4).
"""
from flask import Blueprint, render_template, request
from sqlalchemy import or_
from shared.search import split_tokens, apply_and_filter
from shared.inventory_stock import get_stock_batch, get_stock_summary, get_loc_stock_map

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
        # ★ 박스히어로식 다중 키워드 AND 교집합 필터 (shared.search 헬퍼)
        search_tokens = split_tokens(search_q)
        q = apply_and_filter(q, search_tokens, Option.canonical_sku, Option.boxhero_sku)

        # 모든 SKU 후보 한 번에 (limit 적용 전)
        all_skus_q = q.with_entities(Option.canonical_sku, Option.model_code)
        all_rows = all_skus_q.all()
        all_skus = [r[0] for r in all_rows]
        model_set = {r[1] for r in all_rows}

        # ★ SSOT 재고 batch 조회 (InventoryTx 기반 실시간)
        stock_map = get_stock_batch(s, all_skus)

        # in_stock_only 필터 — 재고 > 0 인 SKU 만 (정적 컬럼 X, 실시간 stock_map 기준)
        if in_stock_only:
            in_stock_skus = {sk for sk, st in stock_map.items() if st > 0}
            q = q.filter(Option.canonical_sku.in_(in_stock_skus) if in_stock_skus else False)
            all_skus = [sk for sk in all_skus if sk in in_stock_skus]

        # ★ stats (실시간 재고 기반)
        stats_total = len(all_skus)
        stats_in_stock = sum(1 for sk in all_skus if stock_map.get(sk, 0) > 0)
        stats_total_stock = sum(stock_map.get(sk, 0) for sk in all_skus)
        stats_model_count = len(model_set if not in_stock_only else
                                {m for m, sk in zip([r[1] for r in all_rows], [r[0] for r in all_rows])
                                 if sk in all_skus})

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
                # 위치별 재고 — SSOT 헬퍼 사용 (실시간 InventoryTx 기반)
                locs = s.query(InventoryLocation).filter(InventoryLocation.deleted_at.is_(None)).all()
                loc_stock = get_loc_stock_map(s, selected_sku, locs)
                # SKU 의 실시간 총 재고 (Option.boxhero_stock_total 대신)
                from shared.inventory_stock import get_stock_by_sku
                selected_realtime_stock = get_stock_by_sku(s, selected_sku)
                selected_detail = {'opt': opt, 'model': model, 'loc_stock': loc_stock,
                                   'realtime_stock': selected_realtime_stock}

        # 위치 드롭다운
        all_locs = s.query(InventoryLocation).filter(InventoryLocation.deleted_at.is_(None)).all()

        # 통계 (실시간 SSOT 재고)
        total_i = int(stats_total or 0)
        in_stock_i = int(stats_in_stock or 0)
        total_stock_i = int(stats_total_stock or 0)
        model_count_i = int(stats_model_count or 0)
        zero_count_i = total_i - in_stock_i
        pct_in_stock = round((in_stock_i / total_i * 100), 1) if total_i else 0.0
        avg_per_held = round((total_stock_i / in_stock_i), 1) if in_stock_i else 0.0
        stats = {
            'total': total_i,
            'in_stock_count': in_stock_i,
            'total_stock': total_stock_i,
            'model_count': model_count_i,
            'zero_count': zero_count_i,
            'pct_in_stock': pct_in_stock,
            'avg_per_held': avg_per_held,
            'shown': len(options),
            'shown_limited': len(options) >= 500 and total_i > 500,
        }

        # 색상·제품명 정리 — 같은 model_code 그룹의 color_display LCP 로 모델명 도출
        # 색상에서 모델명 prefix strip + 제품명 = 브랜드 + 모델명 (색상 제외)
        from collections import defaultdict
        color_by_model: dict[str, list[str]] = defaultdict(list)
        for opt in options:
            raw_c = (opt.color_display or opt.color_code or '').strip()
            if raw_c and opt.model_code:
                color_by_model[opt.model_code].append(raw_c)

        def _lcp_words(strs):
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

        model_lcp_local: dict[str, str] = {}
        for mc, colors in color_by_model.items():
            cp = _lcp_words(colors)
            if cp and len(cp) >= 2:
                model_lcp_local[mc] = cp

        # 정리된 색상 + 제품명 dict (template 에 전달)
        cleaned_color: dict[str, str] = {}
        display_pname: dict[str, str] = {}
        for opt in options:
            raw_c = (opt.color_display or opt.color_code or '').strip()
            prefix = model_lcp_local.get(opt.model_code, '') if opt.model_code else ''
            if prefix and raw_c.startswith(prefix):
                cleaned = raw_c[len(prefix):].strip() or 'one'
            else:
                cleaned = raw_c or 'one'
            cleaned_color[opt.canonical_sku] = cleaned
            # 제품명 = brand + 모델명 (색상 제외)
            brand_v = (opt.model.brand or '').strip() if opt.model else ''
            raw_pname = (opt.model.model_name_display or opt.model.model_name_raw) if opt.model else opt.canonical_sku
            disp_model = (opt.model.model_name_display or '').strip() if opt.model else ''
            if not disp_model:
                disp_model = prefix
            if not disp_model and brand_v and raw_pname.startswith(brand_v):
                disp_model = raw_pname[len(brand_v):].strip()
            # brand strip — disp_model 안의 brand 토큰 모두 제거 (startswith 만으론 부족: 중간 박힌 케이스 대응)
            if disp_model and brand_v:
                tokens = disp_model.split()
                tokens = [t for t in tokens if t != brand_v]
                disp_model = ' '.join(tokens).strip()
                while '  ' in disp_model:
                    disp_model = disp_model.replace('  ', ' ')
            if disp_model:
                # 색상이 끝에 붙어있으면 strip
                if cleaned and cleaned != 'one' and disp_model.endswith(cleaned):
                    disp_model = disp_model[:-len(cleaned)].strip()
                display_pname[opt.canonical_sku] = (f'{brand_v} {disp_model}'.strip() if brand_v else disp_model)
            else:
                display_pname[opt.canonical_sku] = raw_pname or opt.canonical_sku

        return render_template(
            'inventory/home.html',
            active_app='inventory', active='items',
            options=options, grouped=grouped, group_by_model=group_by_model,
            in_stock_only=in_stock_only, search_q=search_q,
            search_tokens=search_tokens,
            selected_detail=selected_detail, all_locs=all_locs,
            location_filter=location_filter, stats=stats,
            stock_map=stock_map,  # ★ list 의 재고 컬럼용 (실시간 SSOT)
            cleaned_color=cleaned_color,  # {sku: 색상} — LCP strip 적용
            display_pname=display_pname,  # {sku: 제품명} — 브랜드+모델명 (색상 X)
        )
    finally:
        s.close()


@bp.get('/_mockups/stats')
def mockup_stats():
    """[mockup] 인벤토리 통계 카드 5 시안 비교 (1920×1080 가로 탭)."""
    return render_template('inventory/_mockup_stats.html', active_app='inventory', active='items')


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
