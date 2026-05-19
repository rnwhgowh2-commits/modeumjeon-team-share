"""[I] /inventory/data/* — 데이터 마스터 6 페이지 라우트.

ai-workflow STEP 7 Sprint 1A Task 1.2~1.6 + 묶음제품 (v1.4)
"""
import os
import json
import shutil
from datetime import datetime
from pathlib import Path
from flask import render_template, request, redirect, url_for, flash, jsonify, send_from_directory, current_app
from sqlalchemy import text as sa_text

from shared.db import SessionLocal
from lemouton.inventory import locations as locations_svc
from lemouton.inventory import attributes as attrs_svc
from lemouton.inventory import partner as partner_svc
from lemouton.sourcing.models import Option, Model

from . import bp


# ============ 묶음제품 (Bundle) — JSON 파일 기반 (DB schema 변경 회피) ============
BUNDLE_FILE = Path(__file__).resolve().parents[3] / 'data' / 'bundles.json'


def _load_bundles() -> list:
    if BUNDLE_FILE.exists():
        try:
            return json.loads(BUNDLE_FILE.read_text(encoding='utf-8'))
        except Exception:
            return []
    return []


def _save_bundles(bundles: list) -> None:
    BUNDLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE_FILE.write_text(json.dumps(bundles, ensure_ascii=False, indent=2), encoding='utf-8')


# ============ 제품 이미지 업로드 (박스히어로 1:1) ============
UPLOAD_DIR = Path(__file__).resolve().parents[3] / 'data' / 'product_images'

@bp.post('/data/items/<path:sku>/upload-image')
def data_item_upload_image(sku):
    """옵션별 이미지 업로드. 파일은 data/product_images/<sku>.<ext>로 저장."""
    file = request.files.get('image')
    if not file or not file.filename:
        flash('이미지 파일을 선택하세요', 'error')
        return redirect(url_for('inventory.data_items'))
    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in ('jpg', 'jpeg', 'png', 'webp', 'gif'):
        flash('이미지 형식 jpg/png/webp/gif 만 가능', 'error')
        return redirect(url_for('inventory.data_items'))
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe = sku.replace('/', '_').replace(' ', '_')
    fname = f'{safe}.{ext}'
    file.save(str(UPLOAD_DIR / fname))
    s = SessionLocal()
    try:
        opt = s.query(Option).filter(Option.canonical_sku == sku).first()
        if opt:
            opt.image_url = f'/inventory/data/product-image/{fname}'
            s.commit()
            flash(f'이미지 업로드 완료 — {sku}', 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.data_items'))


@bp.get('/data/product-image/<path:filename>')
def data_product_image(filename):
    """업로드된 이미지 서빙."""
    return send_from_directory(str(UPLOAD_DIR), filename)


@bp.post('/data/items/<path:sku>/update')
def data_item_update(sku):
    """박스히어로 1:1 인라인 popover 편집 — 제품명·박스히어로 SKU·컬러·사이즈·이미지 동시 저장."""
    from lemouton.sourcing.models import Model as ModelM
    s = SessionLocal()
    try:
        opt = s.query(Option).filter(Option.canonical_sku == sku).first()
        if not opt:
            flash(f'옵션을 찾을 수 없습니다: {sku}', 'error')
            return redirect(url_for('inventory.data_items'))

        new_color = (request.form.get('color_display') or '').strip()
        new_size = (request.form.get('size_display') or '').strip()
        new_bh = (request.form.get('boxhero_sku') or '').strip()
        if hasattr(opt, 'color_display'):
            opt.color_display = new_color or opt.color_display
        if hasattr(opt, 'size_display'):
            opt.size_display = new_size or opt.size_display
        if new_bh:
            opt.boxhero_sku = new_bh

        if opt.model_code:
            model = s.query(ModelM).filter(ModelM.model_code == opt.model_code).first()
            if model:
                new_name = (request.form.get('model_name') or '').strip()
                new_brand = (request.form.get('brand') or '').strip()
                if new_name:
                    model.model_name_display = new_name
                if new_brand:
                    model.brand = new_brand

        file = request.files.get('image')
        if file and file.filename:
            ext = file.filename.rsplit('.', 1)[-1].lower()
            if ext in ('jpg', 'jpeg', 'png', 'webp', 'gif'):
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                safe = sku.replace('/', '_').replace(' ', '_')
                fname = f'{safe}.{ext}'
                file.save(str(UPLOAD_DIR / fname))
                if hasattr(opt, 'image_url'):
                    opt.image_url = f'/inventory/data/product-image/{fname}'

        s.commit()
        flash(f'{sku} 저장됨', 'success')
    except Exception as e:
        s.rollback()
        flash(f'저장 실패: {e}', 'error')
    finally:
        s.close()
    return redirect(url_for('inventory.data_items'))


# ============ 위치 (Q1) ============

@bp.get('/data/locations')
def data_locations():
    s = SessionLocal()
    try:
        locs = locations_svc.list_active(s)
        return render_template(
            'inventory/data/locations.html',
            active='data-locations',
            locations=locs,
        )
    finally:
        s.close()


@bp.post('/data/locations/create')
def data_locations_create():
    name = request.form.get('name', '').strip()
    is_default = request.form.get('is_default') == 'on'
    s = SessionLocal()
    try:
        try:
            loc = locations_svc.create(s, name, is_default)
            s.commit()
            flash(f"위치 '{loc.name}' 추가됨", 'success')
        except ValueError as e:
            s.rollback()
            flash(str(e), 'error')
    finally:
        s.close()
    return redirect(url_for('inventory.data_locations'))


@bp.post('/data/locations/<int:loc_id>/update')
def data_locations_update(loc_id):
    s = SessionLocal()
    try:
        try:
            locations_svc.update(
                s, loc_id,
                name=request.form.get('name'),
                sort_order=int(request.form['sort_order']) if request.form.get('sort_order') else None,
                is_default=(request.form.get('is_default') == 'on') if 'is_default' in request.form else None,
            )
            s.commit()
            flash("수정됨", 'success')
        except ValueError as e:
            s.rollback()
            flash(str(e), 'error')
    finally:
        s.close()
    return redirect(url_for('inventory.data_locations'))


@bp.post('/data/locations/<int:loc_id>/delete')
def data_locations_delete(loc_id):
    s = SessionLocal()
    try:
        try:
            locations_svc.delete(s, loc_id)
            s.commit()
            flash("삭제됨", 'success')
        except ValueError as e:
            s.rollback()
            flash(str(e), 'error')
    finally:
        s.close()
    return redirect(url_for('inventory.data_locations'))


@bp.post('/data/locations/seed-defaults')
def data_locations_seed():
    """박스히어로 기본 3 위치 시드 (그로스/기본 위치/판매불가)."""
    s = SessionLocal()
    try:
        created = locations_svc.seed_defaults(s)
        s.commit()
        flash(f"기본 위치 {len(created)}개 추가됨", 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.data_locations'))


# ============ 제품 (Task 1.3) — 모음전 Option = 박스히어로 SKU 1:1 ============

@bp.get('/data/items')
def data_items():
    """제품 마스터 — 옵션 표 형식.

    형식 분기 — `?format=json` 또는 `Accept: application/json` 헤더 시 JSON 응답.
    JSON 모드는 칩 UI 의 AJAX 라이브 검색용 (새로고침 없이 표·KPI 갱신).
    """
    from lemouton.sourcing.models import Option, Model
    from shared.search import split_tokens, apply_and_filter
    from shared.inventory_stock import get_stock_batch
    from sqlalchemy import func

    page = max(1, int(request.args.get('page', 1)))
    page_size = min(200, int(request.args.get('page_size', 50)))
    q = (request.args.get('q') or '').strip()
    brand = (request.args.get('brand') or '').strip()
    in_stock_only = request.args.get('in_stock_only') == '1'
    search_tokens = split_tokens(q)
    want_json = (
        request.args.get('format') == 'json'
        or 'application/json' in (request.headers.get('Accept') or '')
    )

    s = SessionLocal()
    try:
        query = s.query(Option).join(Model, Option.model_code == Model.model_code)
        # 다중 키워드 AND 교집합 — 토큰별 OR (SKU·바코드·브랜드·제품명·모델명·컬러·사이즈)
        query = apply_and_filter(
            query, search_tokens,
            Option.canonical_sku, Option.boxhero_sku, Option.barcode,
            Model.brand, Model.model_name_display, Model.model_name_raw, Model.model_code,
            Option.color_display, Option.color_code,
            Option.size_display, Option.size_code,
        )
        if brand:
            query = query.filter(Model.brand == brand)

        all_skus_for_stock = [r[0] for r in query.with_entities(Option.canonical_sku).all()]
        stock_map = get_stock_batch(s, all_skus_for_stock)
        if in_stock_only:
            in_skus = {sk for sk, st in stock_map.items() if st > 0}
            query = query.filter(Option.canonical_sku.in_(in_skus) if in_skus else False)

        total = query.count()
        items = (
            query.order_by(Model.model_name_raw, Option.color_code, Option.size_code)
            .offset((page - 1) * page_size).limit(page_size).all()
        )

        all_options_count = s.query(func.count(Option.canonical_sku)).scalar() or 0
        in_stock_count = sum(1 for st in stock_map.values() if st > 0)
        total_qty = sum(stock_map.values())
        kpi = {
            'all_options': all_options_count,
            'in_stock': in_stock_count,
            'total_qty': int(total_qty),
        }

        if want_json:
            from flask import jsonify
            def _color(o):
                return (o.color_display or o.color_code or '').strip() or 'ONE Color'
            def _size(o):
                return (o.size_display or o.size_code or '').strip() or 'FREE'
            rows = [
                {
                    'sku': o.canonical_sku,
                    'bh': o.boxhero_sku or '',
                    'barcode': o.barcode or '',
                    'name': (o.model.model_name_display or o.model.model_name_raw or '') if o.model else '',
                    'model_code': (o.model.model_code or '') if o.model else '',
                    'brand': (o.model.brand or '') if o.model else '',
                    'color': _color(o),
                    'color_raw': o.color_display or o.color_code or '',
                    'size': _size(o),
                    'size_raw': o.size_display or o.size_code or '',
                    'avg': int(o.boxhero_avg_purchase_price or 0),
                    'stock': int(stock_map.get(o.canonical_sku, 0)),
                }
                for o in items
            ]
            return jsonify({
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': (total + page_size - 1) // page_size,
                'items': rows,
                'kpi': kpi,
            })

        brands = [b for (b,) in s.query(Model.brand).distinct().filter(Model.brand.isnot(None)).all()]
        return render_template(
            'inventory/data/items.html',
            active='data-items',
            items=items,
            total=total, page=page, page_size=page_size, total_pages=(total + page_size - 1) // page_size,
            q=q, brand=brand, in_stock_only=in_stock_only,
            search_tokens=search_tokens,
            brands=sorted(brands),
            stock_map=stock_map,
            kpi=kpi,
        )
    finally:
        s.close()


# ============ 제품 마스터 전체 삭제 (TEST 리셋) ============

DATA_DIR = Path(__file__).resolve().parents[3] / 'data'
# BACKUP_ROOT: 로컬은 OneDrive 폴더 5단계 위, 컨테이너(Fly.io 등) 는 깊이 부족 → env 또는 안전 폴백
import os as _os
_parents = Path(__file__).resolve().parents
if _os.environ.get("BACKUP_ROOT"):
    BACKUP_ROOT = Path(_os.environ["BACKUP_ROOT"])
elif len(_parents) > 5:
    BACKUP_ROOT = _parents[5] / '백업'
else:
    # 컨테이너 환경 — 임시 디렉토리 사용 (Supabase 가 별도 백업 처리)
    BACKUP_ROOT = Path('/tmp/모음전_백업') if _os.name != 'nt' else _parents[len(_parents) - 1] / 'tmp_backup'

# wipe 대상 — FK 의존 순서로 (자식 → 부모)
# Model/Option 을 참조하는 모든 테이블. 누락 시 FK 위반 → 백업으로 복원 가능.
_WIPE_TABLES_IN_ORDER = [
    'option_source_urls',           # FK options (CASCADE)
    'option_price_config',          # FK options (CASCADE)
    'option_source_links',          # FK options
    'option_account_registrations', # FK options
    'option_benefit_overrides',     # FK options (가정)
    'price_track_history',          # FK options
    'model_source_links',           # FK models
    'bundle_account_registrations', # FK models
    'bundle_source_urls',           # FK models
    'combo_sets',                   # FK models
    # 재고/거래 — canonical_sku 기반이지만 FK 없을 수 있음 (안전상 비움)
    'inventory_txs',
    'inventory_pending',
    'inventory_counts',
    'inventory_count_sheet_items',
    'inventory_count_sheets',
    'inventory_safety_stock',
    'inventory_products',
    'item_attribute_values',
    'purchase_orders',
    'sales_orders',
    'return_orders',
    # 디스커버리 큐
    'discovery_queue',
    # 마지막: options → models
    'options',
    'models',
]


def _backup_data_dir() -> Path:
    """data 폴더를 백업/data_YYYYMMDD_HHMMSS/ 로 복사. 잠긴 파일은 robocopy 로 skip."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    dst = BACKUP_ROOT / f'data_{ts}_pre_wipe'
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    dst.mkdir(parents=True, exist_ok=True)

    # robocopy 로 잠긴 파일 skip + 브라우저 캐시 폴더 제외
    import subprocess
    args = [
        'robocopy', str(DATA_DIR), str(dst),
        '/E', '/R:0', '/W:0', '/MT:8', '/NFL', '/NDL',
        '/XD', 'Sessions', 'Network', 'Safe Browsing Network',
        'GPUCache', 'ShaderCache', 'GraphiteDawnCache',
    ]
    try:
        proc = subprocess.run(args, capture_output=True, timeout=300)
        # robocopy exit 0~7 = 정상, 8+ = 실패
        if proc.returncode >= 8:
            raise RuntimeError(f'robocopy exit={proc.returncode}: {proc.stderr.decode(errors="replace")[:500]}')
    except FileNotFoundError:
        # robocopy 없는 환경 (테스트) → 그냥 shutil
        shutil.copytree(str(DATA_DIR), str(dst), dirs_exist_ok=True)
    return dst


@bp.post('/data/items/wipe')
def data_items_wipe():
    """제품 마스터 전체 삭제 — TEST 리셋용. 자동 백업 후 진행.

    안전장치:
    1. POST 만 허용 (CSRF token 검증은 Flask-WTF 없으므로 confirm 키워드로 대체)
    2. 자동으로 data 폴더 통째 백업 (백업/data_YYYYMMDD_HHMMSS_pre_wipe/)
    3. 사용자가 'DELETE ALL' 정확히 입력해야 진행
    """
    confirm = (request.form.get('confirm') or '').strip()
    if confirm != 'DELETE ALL':
        flash("확인 키워드 불일치 — 'DELETE ALL' 입력 시에만 삭제 진행됩니다.", 'error')
        return redirect(url_for('inventory.data_items'))

    # 1. 자동 백업
    try:
        backup_path = _backup_data_dir()
    except Exception as e:
        flash(f'자동 백업 실패 — 삭제 중단: {e}', 'error')
        return redirect(url_for('inventory.data_items'))

    # 2. DB wipe — dialect 별 분기 (SQLite: PRAGMA + DELETE, Postgres: TRUNCATE CASCADE)
    s = SessionLocal()
    deleted_counts = {}
    dialect = s.bind.dialect.name  # 'sqlite' | 'postgresql'
    try:
        # 카운트 (before)
        before_models = s.execute(sa_text('SELECT COUNT(*) FROM models')).scalar() or 0
        before_options = s.execute(sa_text('SELECT COUNT(*) FROM options')).scalar() or 0

        # 테이블 존재 확인용 쿼리 (dialect 별)
        def _table_exists(tbl: str) -> bool:
            if dialect == 'sqlite':
                return s.execute(sa_text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
                ), {'n': tbl}).first() is not None
            # Postgres
            return s.execute(sa_text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :n"
            ), {'n': tbl}).first() is not None

        if dialect == 'sqlite':
            # FK 잠시 OFF (자식→부모 의존 순서 DELETE 안전망)
            s.execute(sa_text('PRAGMA foreign_keys = OFF'))
            for tbl in _WIPE_TABLES_IN_ORDER:
                try:
                    if _table_exists(tbl):
                        res = s.execute(sa_text(f'DELETE FROM {tbl}'))
                        deleted_counts[tbl] = res.rowcount or 0
                except Exception as e:
                    deleted_counts[tbl] = f'ERR: {e}'
            s.execute(sa_text('PRAGMA foreign_keys = ON'))
        else:
            # Postgres: 존재하는 테이블만 모아 TRUNCATE ... RESTART IDENTITY CASCADE 1발 처리
            tbls_present = [t for t in _WIPE_TABLES_IN_ORDER if _table_exists(t)]
            if tbls_present:
                tbl_list = ', '.join(f'"{t}"' for t in tbls_present)
                s.execute(sa_text(f'TRUNCATE TABLE {tbl_list} RESTART IDENTITY CASCADE'))
                for t in tbls_present:
                    deleted_counts[t] = '(truncated)'

        s.commit()

        after_models = s.execute(sa_text('SELECT COUNT(*) FROM models')).scalar() or 0
        after_options = s.execute(sa_text('SELECT COUNT(*) FROM options')).scalar() or 0

        flash(
            f"✅ 제품 마스터 전체 삭제 완료\n"
            f"  - 모델: {before_models} → {after_models}\n"
            f"  - 옵션: {before_options} → {after_options}\n"
            f"  - 자동 백업: {backup_path}\n"
            f"  → 이제 [📥 박스히어로 엑셀 업로드] 에서 재로드 가능합니다.",
            'success'
        )
    except Exception as e:
        s.rollback()
        flash(f'삭제 중 오류 (롤백됨, 백업은 남아있음 {backup_path}): {e}', 'error')
    finally:
        s.close()

    return redirect(url_for('inventory.data_items'))


# ============ 속성 (Task 1.4) ============

@bp.get('/data/attributes')
def data_attributes():
    s = SessionLocal()
    try:
        attrs = attrs_svc.list_active(s)
        return render_template(
            'inventory/data/attributes.html',
            active='data-attrs',
            attrs=attrs,
            valid_types=attrs_svc.VALID_TYPES,
        )
    finally:
        s.close()


@bp.post('/data/attributes/create')
def data_attributes_create():
    s = SessionLocal()
    try:
        try:
            attrs_svc.create(s, request.form.get('name', ''), request.form.get('type', 'text'))
            s.commit()
            flash("속성 추가됨", 'success')
        except ValueError as e:
            s.rollback()
            flash(str(e), 'error')
    finally:
        s.close()
    return redirect(url_for('inventory.data_attributes'))


@bp.post('/data/attributes/<int:attr_id>/delete')
def data_attributes_delete(attr_id):
    s = SessionLocal()
    try:
        try:
            attrs_svc.delete(s, attr_id)
            s.commit()
            flash("삭제됨", 'success')
        except ValueError as e:
            s.rollback()
            flash(str(e), 'error')
    finally:
        s.close()
    return redirect(url_for('inventory.data_attributes'))


# ============ 묶음제품 (Bundle) CRUD ============

@bp.get('/data/bundles')
def data_bundles():
    bundles = _load_bundles()
    return render_template('inventory/data/bundles.html',
                           active='data-bundles', bundles=bundles)


def _option_price_map(s) -> dict:
    """SKU → {model_code, color, size, avg_purchase, sale_price} 맵.

    옵션이 모델 다르면 가격 전혀 다를 수 있어 — Bundle 폼에서 참조 가격 표시용.
    """
    opts = s.query(Option).order_by(Option.canonical_sku).limit(2000).all()
    return {
        o.canonical_sku: {
            'sku': o.canonical_sku,
            'model': o.model_code or '',
            'color': o.color_display or o.color_code or '',
            'size': o.size_display or o.size_code or '',
            'avg_purchase': int(o.boxhero_avg_purchase_price or 0),
            'price': int(getattr(o, 'price_default', 0) or 0),
        }
        for o in opts
    }


@bp.get('/data/bundles/new')
def data_bundle_new():
    s = SessionLocal()
    try:
        opt_map = _option_price_map(s)
    finally:
        s.close()
    return render_template('inventory/data/bundle_form.html',
                           active='data-bundles', bundle=None,
                           available_skus=list(opt_map.keys()),
                           opt_price_map=opt_map)


@bp.get('/data/bundles/<bundle_id>/edit')
def data_bundle_edit(bundle_id):
    bundles = _load_bundles()
    b = next((b for b in bundles if str(b.get('id')) == str(bundle_id)), None)
    if not b:
        flash('묶음을 찾을 수 없습니다.', 'error')
        return redirect(url_for('inventory.data_bundles'))
    s = SessionLocal()
    try:
        opt_map = _option_price_map(s)
    finally:
        s.close()
    return render_template('inventory/data/bundle_form.html',
                           active='data-bundles', bundle=b,
                           available_skus=list(opt_map.keys()),
                           opt_price_map=opt_map)


@bp.post('/data/bundles/save', defaults={'bundle_id': None})
@bp.post('/data/bundles/<bundle_id>/save')
def data_bundle_save(bundle_id):
    bundles = _load_bundles()
    sku = (request.form.get('sku') or '').strip()
    name = (request.form.get('name') or '').strip()
    if not sku or not name:
        flash('묶음 SKU·이름은 필수입니다.', 'error')
        return redirect(url_for('inventory.data_bundles'))

    comp_skus = request.form.getlist('comp_sku')
    comp_qtys = request.form.getlist('comp_qty')
    components = []
    for csk, cq in zip(comp_skus, comp_qtys):
        csk = (csk or '').strip()
        try:
            cq_i = int(cq or 1)
        except ValueError:
            cq_i = 1
        if csk and cq_i > 0:
            components.append({'sku': csk, 'qty': cq_i})

    try:
        price = int(request.form.get('price') or 0)
    except ValueError:
        price = 0

    if bundle_id:
        existing = next((b for b in bundles if str(b.get('id')) == str(bundle_id)), None)
        if existing:
            existing.update({'sku': sku, 'name': name, 'components': components,
                             'price': price, 'memo': request.form.get('memo') or '',
                             'updated_at': datetime.now().isoformat()})
    else:
        # SKU duplicate check
        if any(b.get('sku') == sku for b in bundles):
            flash(f'묶음 SKU 중복: {sku}', 'error')
            return redirect(url_for('inventory.data_bundle_new'))
        new_id = max([b.get('id', 0) for b in bundles] + [0]) + 1
        bundles.append({
            'id': new_id, 'sku': sku, 'name': name,
            'components': components, 'price': price,
            'memo': request.form.get('memo') or '',
            'created_at': datetime.now().isoformat(),
        })
    _save_bundles(bundles)
    flash('묶음 저장됨', 'success')
    return redirect(url_for('inventory.data_bundles'))


@bp.post('/data/bundles/<bundle_id>/delete')
def data_bundle_delete(bundle_id):
    bundles = _load_bundles()
    bundles = [b for b in bundles if str(b.get('id')) != str(bundle_id)]
    _save_bundles(bundles)
    flash('묶음 삭제됨', 'success')
    return redirect(url_for('inventory.data_bundles'))


# ============ 거래처 (Task 1.5) — ADR-003 텍스트만 ============

@bp.get('/data/partners')
def data_partners():
    s = SessionLocal()
    try:
        recent = partner_svc.recent_labels(s, limit=100)
        return render_template(
            'inventory/data/partners.html',
            active='data-partners',
            recent=recent,
        )
    finally:
        s.close()


# ============ 가격 템플릿 (Task 1.6) — 기존 PriceTemplate 활용 ============

@bp.get('/data/price-templates')
def data_price_templates():
    from lemouton.templates.models import PriceTemplate
    s = SessionLocal()
    try:
        templates = s.query(PriceTemplate).order_by(PriceTemplate.id).all()
        return render_template(
            'inventory/data/price_templates.html',
            active='data-pt',
            templates=templates,
        )
    finally:
        s.close()


@bp.post('/data/price-templates/<int:tpl_id>/update-margin')
def data_price_templates_update_margin(tpl_id):
    """박스히어로 마진 4컬럼 수정 (R2 핵심)."""
    from lemouton.templates.models import PriceTemplate
    s = SessionLocal()
    try:
        tpl = s.query(PriceTemplate).filter(PriceTemplate.id == tpl_id).first()
        if not tpl:
            flash("템플릿 없음", 'error')
            return redirect(url_for('inventory.data_price_templates'))
        tpl.boxhero_margin_mode_self = request.form.get('mode_self', 'rate')
        tpl.boxhero_margin_value_self = int(request.form.get('value_self', 2500) or 2500)
        tpl.boxhero_margin_mode_external = request.form.get('mode_external', 'rate')
        tpl.boxhero_margin_value_external = int(request.form.get('value_external', 2000) or 2000)
        s.commit()
        flash(f"'{tpl.name}' 사입 마진 업데이트됨", 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.data_price_templates'))


@bp.get('/data/items/export.xlsx')
def data_items_export():
    """우리 양식 8 base 컬럼 + 동적 위치별 재고 컬럼 엑셀 다운로드.

    헤더 (사용자 spec): SKU / 바코드 / 브랜드 / 제품명 / 색상 / 사이즈 / 평균매입가 / 총재고 / {위치명1} 재고 / {위치명2} 재고 / ...
    빈 색상 → 'one' / 빈 사이즈 → 'free'
    """
    from io import BytesIO
    from datetime import datetime
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from sqlalchemy.orm import joinedload
    from lemouton.sourcing.models import Option, Model
    from lemouton.inventory.models import InventoryLocation
    from shared.inventory_stock import get_stock_batch

    s = SessionLocal()
    try:
        options = (
            s.query(Option)
            .options(joinedload(Option.model))
            .order_by(Option.model_code, Option.sort_order, Option.canonical_sku)
            .all()
        )
        all_skus = [o.canonical_sku for o in options]

        total_stock_map = get_stock_batch(s, all_skus)
        locs = (
            s.query(InventoryLocation)
            .filter(InventoryLocation.deleted_at.is_(None))
            .order_by(InventoryLocation.sort_order, InventoryLocation.id)
            .all()
        )
        per_loc_stock = {}
        for loc in locs:
            loc_map = get_stock_batch(s, all_skus, location_id=loc.id)
            for sku, st in loc_map.items():
                per_loc_stock.setdefault(sku, {})[loc.id] = st

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '재고관리'

        headers = ['SKU', '바코드', '브랜드', '제품명', '색상', '사이즈', '평균매입가', '총재고']
        for loc in locs:
            headers.append(f'{loc.name} 재고')
        ws.append(headers)

        for o in options:
            barcode = o.barcode or o.boxhero_sku or ''
            brand = (o.model.brand or '') if o.model else ''
            pname = ((o.model.model_name_display or o.model.model_name_raw) if o.model else o.canonical_sku) or ''
            color = (o.color_display or o.color_code or 'one')
            size = (o.size_display or o.size_code or 'free')
            if color == pname or (len(color) > 12 and pname.startswith(color[:8])):
                color = 'one'
            avg = int(o.boxhero_avg_purchase_price or 0)
            total = int(total_stock_map.get(o.canonical_sku, 0))
            row = [o.canonical_sku, barcode, brand, pname, color, size, avg, total]
            for loc in locs:
                row.append(int(per_loc_stock.get(o.canonical_sku, {}).get(loc.id, 0)))
            ws.append(row)

        header_font = Font(bold=True, color='FFFFFF', size=11)
        header_fill = PatternFill(start_color='4F67FF', end_color='4F67FF', fill_type='solid')
        for col_idx in range(1, len(headers) + 1):
            c = ws.cell(row=1, column=col_idx)
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 24
        ws.freeze_panes = 'A2'

        widths = [16, 16, 14, 36, 14, 10, 12, 10] + [12] * len(locs)
        for i, w in enumerate(widths):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)

        ts = datetime.now().strftime('%Y%m%d-%H%M%S')
        from flask import send_file
        return send_file(buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'재고관리_{ts}.xlsx',
        )
    finally:
        s.close()
