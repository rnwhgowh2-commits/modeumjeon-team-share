"""[E] 모음전 list + edit (단일 스크롤 + 우측 sticky nav).

T5는 GET 렌더만 — 저장/복제/삭제/등록 같은 변경 액션은 T10 AJAX에서 wiring.
"""
from datetime import datetime, timezone, timedelta
from flask import Blueprint, abort, jsonify, redirect, render_template, request

from shared.db import SessionLocal
from lemouton.sourcing.models import Model, Option, DiscoveryQueueItem, BundleSourceUrl, OptionSourceUrlLink, OptionInventoryLink
from lemouton.sourcing.source_registry import SOURCES as SOURCE_REGISTRY, get_keys as _src_keys, get_all_sources, get_all_keys
from lemouton.sourcing.models_v2 import UploadAccount
from lemouton.templates.models import (
    PriceTemplate, ColorTemplate, SizeTemplate, ComboSet,
)

bp = Blueprint('bundles', __name__)


def _humanize_ago(dt) -> str:
    """DateTime → '2시간 전' / '3일 전' / '12분 전' / '방금 전' / '—'."""
    if dt is None:
        return '—'
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    sec = int(delta.total_seconds())
    if sec < 60:
        return '방금 전'
    if sec < 3600:
        return f'{sec // 60}분 전'
    if sec < 86400:
        return f'{sec // 3600}시간 전'
    return f'{sec // 86400}일 전'


def _fmt_dt(dt) -> str:
    if dt is None:
        return ''
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    kst = dt + timedelta(hours=9)
    return kst.strftime('%Y-%m-%d %H:%M')


def _iso_utc(dt) -> str:
    """클라이언트 측 ticker 가 사용 — UTC ISO 문자열로 직렬화. None → ''."""
    if dt is None:
        return ''
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _crawl_kind(dt) -> str:
    if dt is None:
        return 'none'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - dt) > timedelta(hours=12):
        return 'stale'
    return 'ok'


def _upload_kind(dt, dlq_failed: int) -> str:
    if dlq_failed:
        return 'fail'
    if dt is None:
        return 'none'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - dt) > timedelta(hours=48):
        return 'stale'
    return 'ok'


_DEFAULT_CATEGORIES = ['신발', '의류', '가방']


def _all_categories() -> list[str]:
    """카테고리 드롭다운 옵션 — 기본 3종 + DB에 이미 쓰인 카테고리(중복 제거).

    별도 카테고리 테이블이 없어 Model.category 문자열을 단일 진실 원천으로 삼는다.
    기본 3종을 항상 맨 앞 고정(드롭다운 첫 항목 = '신발' 유지), 나머지는 가나다순.
    """
    s = SessionLocal()
    try:
        rows = s.query(Model.category).distinct().all()
    finally:
        s.close()
    used = {(r[0] or '').strip() for r in rows}
    extra = sorted(used - set(_DEFAULT_CATEGORIES) - {''})
    return _DEFAULT_CATEGORIES + extra


@bp.route('/bundles/_mockups/draft-sidebar', methods=['GET'])
def bundles_mockup_draft_sidebar():
    """[mockup] 임시저장 사이드바 3 시안 비교."""
    return render_template('bundles/_mockup_draft_sidebar.html', active='bundles')


@bp.route('/bundles/_mockups/sourcing', methods=['GET'])
def bundles_mockup_sourcing():
    """[mockup] 옵션×소싱처 매트릭스 3 시안 비교."""
    return render_template('bundles/_mockup_sourcing.html', active='bundles')


@bp.route('/bundles/migrate', methods=['GET'])
def bundle_migrate():
    """[v2] 마켓 등록된 상품 연동 — 스스 originProductNo 1개 입력 → 자동 모음전 생성."""
    return render_template('bundles/migrate.html', active='bundles_migrate',
                           error=None, form={}, categories=_all_categories())


@bp.route('/bundles/new', methods=['GET', 'POST'])
def bundle_new():
    if request.method == 'POST':
        code = (request.form.get('model_code') or '').strip()
        name = (request.form.get('model_name_raw') or '').strip()
        brand = (request.form.get('brand') or '르무통').strip()
        category = (request.form.get('category') or '신발').strip()
        if not code or not name:
            return render_template('bundles/new.html', active='bundles',
                                   error='모음전 코드와 모델명을 모두 입력하세요.',
                                   form=request.form, categories=_all_categories())
        if not brand:
            return render_template('bundles/new.html', active='bundles',
                                   error='브랜드를 입력하세요.',
                                   form=request.form, categories=_all_categories())
        s = SessionLocal()
        try:
            if s.query(Model).filter_by(model_code=code).first():
                return render_template('bundles/new.html', active='bundles',
                                       error=f"'{code}' 코드는 이미 존재해요.",
                                       form=request.form, categories=_all_categories())
            m = Model(model_code=code, model_name_raw=name,
                      model_name_display=name, brand=brand, category=category)
            s.add(m)
            s.commit()
        finally:
            s.close()
        return redirect(f'/bundles/{code}')
    return render_template('bundles/new.html', active='bundles_new', error=None,
                           form={}, categories=_all_categories())


def _classify_bundle_status(m: Model, opt_count: int, opts_with_naver: int,
                            opts_with_coupang: int) -> tuple[str, str, str]:
    """[v2] 모음전 상태 분류 — 정규 = 활성 마켓 모두에 product_id + 모든 옵션 ID 매칭.

    Returns: (status_key, status_label, status_color)
      'active' = 정규 등록 완료
      'migrate_wip' = 마켓 ID 있으나 옵션 매칭 미완 (또는 다른 마켓 ID 미등록)
      'new_wip' = 활성 마켓에 product_id 둘 다 없음 (신규 작업중)
    """
    has_ss = bool(m.naver_product_id)
    has_cp = bool(m.coupang_product_id)
    active_ss = bool(m.market_active_ss)
    active_cp = bool(m.market_active_coupang)

    # 활성 마켓이 0개면 = 어느 마켓에도 노출 안 함 (작업 미시작)
    if not active_ss and not active_cp:
        return ('new_wip', '⏳ 신규 작업중 (마켓 비활성)', 'warn')

    # 활성 마켓 중 product_id 미등록인 게 있으면 = 신규 작업중
    miss_markets = []
    if active_ss and not has_ss: miss_markets.append('스스')
    if active_cp and not has_cp: miss_markets.append('쿠팡')
    if miss_markets:
        return ('new_wip',
                f'⏳ 신규 작업중 ({"/".join(miss_markets)} 미등록)', 'warn')

    # 활성 마켓에 product_id 다 있음 → 옵션 매칭 체크
    if opt_count == 0:
        return ('migrate_wip', '⏳ 옵션 0개 (매트릭스 미작성)', 'warn')
    miss_opt = []
    if active_ss and opts_with_naver < opt_count:
        miss_opt.append(f'스스 {opts_with_naver}/{opt_count}')
    if active_cp and opts_with_coupang < opt_count:
        miss_opt.append(f'쿠팡 {opts_with_coupang}/{opt_count}')
    if miss_opt:
        return ('migrate_wip',
                f'⏳ 옵션 ID 매칭 미완 ({", ".join(miss_opt)})', 'warn')

    return ('active', '✅ 정규 등록 완료', 'ok')


def _build_bundle_prefetch(s, models: list) -> dict:
    """list 라우트용 batch prefetch — N+1 회피.

    모든 model_code 를 한 번에 IN 절로 가져와 인메모리 group. 결과를 _bundle_summary
    에 prefetch 인자로 넘기면 모델당 추가 쿼리 0개로 처리됨.
    동일 입력 → 동일 출력 보장 (단순 batch 화, 비즈니스 로직 변경 없음).
    """
    from collections import defaultdict
    import json as _json
    from lemouton.sourcing.models_pricing import OptionSourceUrl, SourceRegistry
    from lemouton.uploader.models import MarketRegistration
    from lemouton.sources.models import SourceProduct, SourceOption

    all_codes = [m.model_code for m in models]
    if not all_codes:
        return {
            'options_by_model': {}, 'src_dist_by_model': {},
            'dlq_count_by_model': {}, 'musinsa_count_by_model': {},
        }

    # ── ① Option batch ───────────────────────────────────────────
    all_opts = s.query(Option).filter(Option.model_code.in_(all_codes)).all()
    options_by_model: dict[str, list] = defaultdict(list)
    for o in all_opts:
        options_by_model[o.model_code].append(o)
    sku_to_model: dict[str, str] = {o.canonical_sku: o.model_code for o in all_opts}
    all_skus = list(sku_to_model.keys())

    # ── ② SourceRegistry × OptionSourceUrl batch (소싱처 분포) ────
    src_dist_by_model: dict[str, list] = {}
    if all_skus:
        src_rows = (
            s.query(OptionSourceUrl.canonical_sku,
                    SourceRegistry.name,
                    SourceRegistry.sort_order)
            .join(SourceRegistry, OptionSourceUrl.source_id == SourceRegistry.id)
            .filter(OptionSourceUrl.canonical_sku.in_(all_skus))
            .all()
        )
        _per_model: dict[str, dict] = defaultdict(lambda: defaultdict(int))
        for sku, name, sort_order in src_rows:
            mc = sku_to_model.get(sku)
            if mc is None:
                continue
            _per_model[mc][(name, sort_order)] += 1
        for mc, counts in _per_model.items():
            ordered = sorted(counts.items(), key=lambda kv: kv[0][1])  # by sort_order
            src_dist_by_model[mc] = [{'name': name, 'count': cnt}
                                      for (name, _so), cnt in ordered]

    # ── ③ MarketRegistration DLQ batch ──────────────────────────
    # 원본은 모델마다 canonical_sku LIKE 'model_code%' 독립 count.
    # 동일 동작 보장: 전체 failed 를 1쿼리로 가져온 뒤 인메모리에서 prefix 매칭.
    # (model_code 가 다른 model_code 의 prefix 가능하므로 break 없이 모든 매칭에 카운트.)
    dlq_count_by_model: dict[str, int] = defaultdict(int)
    mr_failed_rows = (
        s.query(MarketRegistration.canonical_sku)
        .filter(MarketRegistration.status == 'failed')
        .all()
    )
    for (sku,) in mr_failed_rows:
        if not sku:
            continue
        for mc in all_codes:
            if sku.startswith(mc):
                dlq_count_by_model[mc] += 1

    # ── ④ 무신사 비회원가 batch (Phase 8.8.4) ────────────────────
    musinsa_count_by_model: dict[str, int] = defaultdict(int)
    if all_skus:
        try:
            musinsa_rows = (
                s.query(OptionSourceUrl.canonical_sku, OptionSourceUrl.product_url)
                .filter(OptionSourceUrl.canonical_sku.in_(all_skus),
                        OptionSourceUrl.source_id == 3)
                .all()
            )
            all_musinsa_urls = list({url for _sku, url in musinsa_rows})
            sp_id_by_url: dict[str, int] = {}
            if all_musinsa_urls:
                sp_rows = (
                    s.query(SourceProduct.id, SourceProduct.url)
                    .filter(SourceProduct.site == 'musinsa',
                            SourceProduct.url.in_(all_musinsa_urls),
                            SourceProduct.deleted_at.is_(None))
                    .all()
                )
                for sp_id, url in sp_rows:
                    sp_id_by_url.setdefault(url, sp_id)
            dyn_by_sp: dict[int, dict] = {}
            if sp_id_by_url:
                so_rows = (
                    s.query(SourceOption.source_product_id,
                            SourceOption.dynamic_benefits_json)
                    .filter(SourceOption.source_product_id.in_(list(sp_id_by_url.values())),
                            SourceOption.deleted_at.is_(None))
                    .all()
                )
                for sp_id, dyn_json in so_rows:
                    if sp_id in dyn_by_sp:
                        continue
                    try:
                        dyn_by_sp[sp_id] = _json.loads(dyn_json or '{}') if dyn_json else {}
                    except Exception:
                        dyn_by_sp[sp_id] = {}
            non_member_urls = {url for url, sp_id in sp_id_by_url.items()
                                if not dyn_by_sp.get(sp_id, {}).get('is_member_price')}
            for sku, url in musinsa_rows:
                if url in non_member_urls:
                    mc = sku_to_model.get(sku)
                    if mc:
                        musinsa_count_by_model[mc] += 1
        except Exception:
            pass  # 비회원가 검출 실패해도 list 페이지는 그대로 노출

    return {
        'options_by_model': options_by_model,
        'src_dist_by_model': src_dist_by_model,
        'dlq_count_by_model': dlq_count_by_model,
        'musinsa_count_by_model': musinsa_count_by_model,
    }


def _bundle_summary(s, m: Model, *, prefetch: dict | None = None) -> dict:
    """list 카드용 요약 — v3: 소싱처 N개 / URL Y개 분포 칩.

    URL 카운트 = 모음전의 모든 옵션 × 소싱처 매핑 행 합계.
    소싱처 카운트 = 그 모음전 옵션들이 사용 중인 distinct 소싱처 수.
    소싱처별 URL 수 = (소싱처 이름, 그 소싱처에 등록된 URL 갯수) 리스트.

    prefetch=None: 기존 N+1 동작 (백워드 호환).
    prefetch dict: _build_bundle_prefetch 결과 — 모델당 추가 쿼리 0개.
    """
    from sqlalchemy import func
    from lemouton.sourcing.models_pricing import OptionSourceUrl, SourceRegistry

    if prefetch is not None:
        opts = prefetch['options_by_model'].get(m.model_code, [])
    else:
        opts = s.query(Option).filter_by(model_code=m.model_code).all()
    opt_count = len(opts)
    opts_with_naver = sum(1 for o in opts if o.naver_option_id)
    opts_with_coupang = sum(1 for o in opts if o.coupang_option_id)

    # v3: 소싱처별 URL 카운트
    sku_list = [o.canonical_sku for o in opts]
    src_dist = []
    src_total = 0
    url_total = 0
    if prefetch is not None:
        src_dist = prefetch['src_dist_by_model'].get(m.model_code, [])
        src_total = len(src_dist)
        url_total = sum(r['count'] for r in src_dist)
    elif sku_list:
        rows = (
            s.query(SourceRegistry.name,
                    func.count(OptionSourceUrl.id).label('cnt'))
            .join(OptionSourceUrl, OptionSourceUrl.source_id == SourceRegistry.id)
            .filter(OptionSourceUrl.canonical_sku.in_(sku_list))
            # PostgreSQL 호환 — ORDER BY 컬럼은 GROUP BY 에 포함되어야 함
            # SQLite 는 (name) 만으로 sort_order 자동 추론 가능, PG 는 strict.
            .group_by(SourceRegistry.name, SourceRegistry.sort_order)
            .order_by(SourceRegistry.sort_order)
            .all()
        )
        src_dist = [{'name': name, 'count': cnt} for name, cnt in rows]
        src_total = len(src_dist)
        url_total = sum(r['count'] for r in src_dist)

    status_key, status_label, status_color = _classify_bundle_status(
        m, opt_count, opts_with_naver, opts_with_coupang,
    )

    # 업로드 실패 — DLQ 적재 여부
    if prefetch is not None:
        dlq_failed = prefetch['dlq_count_by_model'].get(m.model_code, 0)
    else:
        from lemouton.uploader.models import MarketRegistration
        dlq_failed = (
            s.query(MarketRegistration)
            .filter(
                MarketRegistration.canonical_sku.like(f'{m.model_code}%'),
                MarketRegistration.status == 'failed',
            )
            .count()
        )

    # ★ Phase 8.8.4 (2026-05-17) — 무신사 비회원가 검출
    #   이 모음전의 옵션 중 무신사 매핑 있고 + 매핑된 SourceOption 의 dyn 에
    #   is_member_price != True 면 비회원가 사고. 매트릭스 ⚠ 좌측 보더 표시 트리거.
    if prefetch is not None:
        musinsa_non_member_count = prefetch['musinsa_count_by_model'].get(m.model_code, 0)
    else:
        musinsa_non_member_count = 0
        try:
            import json as _json
            from lemouton.sources.models import SourceProduct, SourceOption
            musinsa_urls = (s.query(OptionSourceUrl.product_url)
                            .filter(OptionSourceUrl.canonical_sku.in_(sku_list),
                                    OptionSourceUrl.source_id == 3)
                            .distinct().all())
            url_set = {u[0] for u in musinsa_urls}
            for url in url_set:
                sp = s.query(SourceProduct).filter_by(site='musinsa', url=url, deleted_at=None).first()
                if not sp:
                    continue
                so = s.query(SourceOption).filter_by(source_product_id=sp.id, deleted_at=None).first()
                if not so:
                    continue
                try:
                    dyn = _json.loads(so.dynamic_benefits_json or '{}') if so.dynamic_benefits_json else {}
                except Exception:
                    dyn = {}
                if not dyn.get('is_member_price'):
                    cnt = (s.query(OptionSourceUrl)
                           .filter_by(source_id=3, product_url=url)
                           .filter(OptionSourceUrl.canonical_sku.in_(sku_list))
                           .count())
                    musinsa_non_member_count += cnt
        except Exception:
            pass  # 비회원가 검출 실패해도 list 페이지는 그대로 노출

    return {
        'model_code': m.model_code,
        'model_name_display': m.model_name_display or m.model_name_raw,
        'brand': m.brand or '—',
        'category': m.category or '신발',
        'option_count': opt_count,
        'opts_with_naver': opts_with_naver,
        'opts_with_coupang': opts_with_coupang,
        # v3: 소싱처 분포
        'src_total': src_total,
        'url_total': url_total,
        'src_dist': src_dist,
        # 레거시 호환 (기존 카드 매크로용)
        'sources_filled': src_total,
        'sources_total': max(src_total, 1),
        'inventory_count': opt_count,
        'naver_product_id': m.naver_product_id,
        'coupang_product_id': m.coupang_product_id,
        'status_key': status_key,
        'status_label': status_label,
        'status_color': status_color,
        'badge_kind': status_color,
        'badge_text': status_label,
        # 크롤·업로드 최신 일자
        'last_crawled_ago': _humanize_ago(m.last_crawled_at),
        'last_crawled_at': _fmt_dt(m.last_crawled_at),
        'last_uploaded_ago': _humanize_ago(m.last_uploaded_at),
        'last_uploaded_at': _fmt_dt(m.last_uploaded_at),
        'crawl_kind': _crawl_kind(m.last_crawled_at),
        'upload_kind': _upload_kind(m.last_uploaded_at, dlq_failed),
        'dlq_failed': dlq_failed,
        # ★ Phase 8.8.4 — 무신사 비회원가 카운트 (row 좌측 보더 ⚠ 트리거)
        'musinsa_non_member_count': musinsa_non_member_count,
    }


@bp.route('/bundles')
def bundle_list():
    from lemouton.sourcing.models import BundleGroup
    from shared.search import split_tokens, apply_and_filter
    q = (request.args.get('q') or '').strip()
    search_tokens = split_tokens(q)
    selected_brand = (request.args.get('brand') or '').strip() or None
    selected_status = (request.args.get('status') or 'draft').strip()
    if selected_status not in {'draft', 'active'}:
        selected_status = 'draft'
    s = SessionLocal()
    try:
        # [2026-05-28] Phase 2-2 — "단독_" prefix 모델은 모음전 list 제외 (사용자 룰)
        query = s.query(Model).filter(~Model.model_code.like('단독_%'))
        # ★ 박스히어로식 다중 키워드 AND 교집합
        query = apply_and_filter(
            query, search_tokens,
            Model.model_code, Model.model_name_raw, Model.model_name_display, Model.brand,
            op='ilike',
        )
        if selected_brand:
            query = query.filter(Model.brand == selected_brand)
        models = query.order_by(Model.updated_at.desc().nullslast()).all()
        # N+1 회피 — 모델 N개에 대한 의존 데이터를 한 번에 batch prefetch
        # (Option / OptionSourceUrl×SourceRegistry / MarketRegistration / 무신사 dyn).
        # 기존엔 모델당 ~4쿼리 + 무신사 URL당 3쿼리 → Supabase RTT 누적이 페이지 로드의 주범.
        _prefetch = _build_bundle_prefetch(s, models)
        bundles_all = [_bundle_summary(s, m, prefetch=_prefetch) for m in models]

        # [v3 시나리오 C] 그룹 단위 묶기 — 같은 bundle_group_id 의 Model 들을 1 카드로
        # 그룹 정보 조회
        gid_to_group = {g.id: g for g in s.query(BundleGroup).all()}
        # bundle 카드에 group 정보 주입
        for b in bundles_all:
            mc = b['model_code']
            mm = next((m for m in models if m.model_code == mc), None)
            gid = mm.bundle_group_id if mm else None
            grp = gid_to_group.get(gid) if gid else None
            b['group_id'] = gid
            b['group_code'] = grp.group_code if grp else mc
            b['group_name'] = grp.group_name if grp else b['model_name_display']
            # 한 그룹에 여러 모델이면 카드 link 는 group_code 기준
            b['link_code'] = b['group_code']
            # 같은 그룹 안 다른 모델 수
            if grp and len(grp.models) > 1:
                b['cluster_size'] = len(grp.models)
                b['cluster_models'] = [mm2.model_code for mm2 in grp.models]
            else:
                b['cluster_size'] = 1
                b['cluster_models'] = [mc]

        # 같은 group_id 의 Model 카드들을 1 카드로 dedup (cluster_size>=2 일 때만)
        seen_groups = set()
        deduped = []
        for b in bundles_all:
            if b['cluster_size'] >= 2:
                if b['group_id'] in seen_groups:
                    continue
                seen_groups.add(b['group_id'])
            deduped.append(b)
        bundles_all = deduped
        # [v2] 그룹별 카운트 (탭 배지용)
        groups = {
            'new_wip': [b for b in bundles_all if b['status_key'] == 'new_wip'],
            'migrate_wip': [b for b in bundles_all if b['status_key'] == 'migrate_wip'],
            'active': [b for b in bundles_all if b['status_key'] == 'active'],
        }
        counts = {
            'draft': len(groups['new_wip']) + len(groups['migrate_wip']),
            'active': len(groups['active']),
        }
        # [통합 목록] 임시저장/정규 탭 제거 — 모든 모음전을 한 목록에 (상태는 컬럼으로 구분)
        bundles = groups['new_wip'] + groups['migrate_wip'] + groups['active']
        # 브랜드 칩 — 전체 모음전 (필터 없이) 기준 카운트
        from sqlalchemy import func
        brand_rows = (s.query(Model.brand, func.count(Model.model_code))
                      .group_by(Model.brand)
                      .order_by(func.count(Model.model_code).desc())
                      .all())
        brand_chips = [{'name': (b or '—'), 'count': c}
                       for b, c in brand_rows if b]
        # V2 — 동적 마켓 column (UploadAccount 등록된 마켓 + 시스템 기본 SS+쿠팡)
        # 사용자가 판매처 계정 추가 시 자동으로 column 늘어남
        _MKT_LABEL = {
            'smartstore':'스마트스토어','coupang':'쿠팡','lotteon':'롯데온',
            'eleven11':'11번가','auction':'옥션','gmarket':'G마켓',
            'wemakeprice':'위메프','interpark':'인터파크','tmon':'티몬',
            'kakaogift':'카카오선물','cafe24':'카페24'
        }
        _MKT_ICON = {
            'smartstore':'N','coupang':'쿠','lotteon':'롯','eleven11':'11',
            'auction':'옥','gmarket':'G','wemakeprice':'위','interpark':'인',
            'tmon':'티','kakaogift':'카','cafe24':'C24'
        }
        upload_markets = (s.query(UploadAccount.market, func.count(UploadAccount.id))
                            .group_by(UploadAccount.market).all())
        _seen = set()
        markets_active = []
        # 시스템 기본 = SS + 쿠팡 (계정 0개여도 칼럼 노출)
        for k in ('smartstore', 'coupang'):
            markets_active.append({
                'key': k,
                'label': _MKT_LABEL.get(k, k),
                'glyph': _MKT_ICON.get(k, '?'),
                'account_count': 0,
            })
            _seen.add(k)
        for k, cnt in upload_markets:
            if k in _seen:
                # 이미 추가된 시스템 마켓 → 카운트만 갱신
                for m in markets_active:
                    if m['key'] == k:
                        m['account_count'] = cnt
                continue
            markets_active.append({
                'key': k,
                'label': _MKT_LABEL.get(k, k),
                'glyph': _MKT_ICON.get(k, k[0:1].upper()),
                'account_count': cnt,
            })
            _seen.add(k)
    finally:
        s.close()
    return render_template('bundles/list.html', active='bundles',
                           bundles=bundles, groups=groups, q=q, search_tokens=search_tokens,
                           brand_chips=brand_chips,
                           selected_brand=selected_brand,
                           selected_status=selected_status,
                           counts=counts,
                           markets_active=markets_active)


@bp.route('/bundles/<code>/option/<sku>')
def option_detail(code: str, sku: str):
    """[v2] 옵션 단위 마켓 ID·소싱 ID·박스히어로 SKU 입력 디테일.

    code 가 model_code 또는 group_code 모두 받음 (bundle_edit 와 동일 패턴).
    옵션이 다른 model_code 에 속해도 sku 로 찾아 fallback.
    """
    from lemouton.sourcing.models import BundleGroup
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            grp = s.query(BundleGroup).filter_by(group_code=code).first()
            if grp and grp.models:
                # 그룹의 모델 중 옵션 보유한 것을 대표로
                for gm in grp.models:
                    if s.query(Option).filter_by(canonical_sku=sku, model_code=gm.model_code).first():
                        m = gm
                        break
                if m is None:
                    m = grp.models[0]
        # 옵션 찾기 — model_code 일치 우선, 없으면 sku 단독 매칭 (옵션이 다른 모델 소속일 수 있음)
        o = None
        if m:
            o = s.query(Option).filter_by(canonical_sku=sku, model_code=m.model_code).first()
        if o is None:
            o = s.query(Option).filter_by(canonical_sku=sku).first()
            if o and m is None:
                m = s.query(Model).filter_by(model_code=o.model_code).first()
        if o is None or m is None:
            # 진짜 잘못된 URL — 친절한 안내 페이지
            return render_template('errors/option_not_found.html',
                                   active='bundles', requested_code=code, requested_sku=sku), 404
        account_rows = []
    finally:
        s.close()
    return render_template('bundles/option_detail.html', active='bundles',
                           bundle=m, option=o, account_rows=account_rows)


@bp.route('/bundles/<code>')
def bundle_edit(code: str):
    s = SessionLocal()
    try:
        # [v3 시나리오 C] code = model_code 우선, 없으면 group_code 로 fallback
        m = s.query(Model).filter_by(model_code=code).first()
        group_member_codes = None
        if m is None:
            from lemouton.sourcing.models import BundleGroup
            grp = s.query(BundleGroup).filter_by(group_code=code).first()
            if grp is None or not grp.models:
                abort(404)
            # 그룹의 첫 번째 모델을 대표로, 옵션은 그룹 전체 모델 통합
            m = grp.models[0]
            group_member_codes = [mm.model_code for mm in grp.models]
        if group_member_codes:
            options = (
                s.query(Option)
                .filter(Option.model_code.in_(group_member_codes))
                .order_by(Option.sort_order, Option.color_code, Option.size_code)
                .all()
            )
        else:
            options = (
                s.query(Option)
                .filter_by(model_code=code)
                .order_by(Option.sort_order, Option.color_code, Option.size_code)
                .all()
            )
        # 템플릿 옵션 (sdrop에 표시할 후보 + 적용 템플릿)
        price_templates = s.query(PriceTemplate).order_by(PriceTemplate.id).all()
        color_templates = s.query(ColorTemplate).order_by(ColorTemplate.id).all()
        size_templates = s.query(SizeTemplate).order_by(SizeTemplate.id).all()

        applied_price = next((t for t in price_templates if t.id == m.price_template_id), None)
        applied_color = next((t for t in color_templates if t.id == m.color_template_id), None)
        applied_size = next((t for t in size_templates if t.id == m.size_template_id), None)

        combos = (
            s.query(ComboSet)
            .filter_by(model_code=code)
            .order_by(ComboSet.sort_order, ComboSet.id)
            .all()
        )

        # 클러스터 모델 list (헤더 모델 칩) — 세션 닫히기 전 dict 로 추출
        cluster_models = []
        try:
            from lemouton.sourcing.models import BundleGroup
            if m.bundle_group_id:
                grp = s.query(BundleGroup).filter_by(id=m.bundle_group_id).first()
                if grp:
                    cluster_models = [{'model_code': mm.model_code, 'model_name_display': mm.model_name_display or mm.model_code}
                                      for mm in grp.models]
        except Exception:
            pass

        # 소싱처 레지스트리 — builtin 5 (긴급: SourcingSource 별도 connection 으로 격리 조회)
        # bundles.py edit 의 outside session 은 model/option 조회로 이미 transaction in-flight
        # SourcingSource 조회 시 어떤 이유로 PG transaction abort → 같은 connection 전체 영향
        # → 완전 별개 engine.connect() 로 자체 격리
        all_sources = list(SOURCE_REGISTRY)
        try:
            # [perf 2026-06-12] 커스텀 소싱처(sourcing_sources)는 관리자가 가끔만 추가하는
            #   설정 데이터(가격 아님) → plain dict 리스트를 60초 TTL 캐시(매 페이지 쿼리 제거).
            from shared.ref_cache import cached as _ref_cached
            from sqlalchemy import text as _sql_text
            from shared.db import engine as _engine

            def _load_custom_sources():
                _out = []
                with _engine.connect() as _conn:
                    rs = _conn.execute(_sql_text(
                        "SELECT source_key, label, logo_letter, logo_color, has_adapter, "
                        "favicon_url, domain, needs_login "
                        "FROM sourcing_sources WHERE is_active=true "
                        "ORDER BY sort_order, id"
                    ))
                    for r in rs.fetchall():
                        sk, lbl, lt, lc, ha, fv, dm, nl = r
                        _out.append({
                            'key': sk, 'label': lbl,
                            'brand': 'custom-' + sk,
                            'glyph': lt or (lbl[:1].upper() if lbl else 'X'),
                            'crawler': bool(ha), 'legacy': False,
                            'logo_color': lc or '#3182F6',
                            'favicon_url': fv, 'domain': dm,
                            'needs_login': bool(nl), 'builtin': False,
                        })
                return _out
            all_sources.extend(_ref_cached('page:custom_sources', 60.0, _load_custom_sources))
        except Exception:
            pass  # 테이블 미존재 / 기타 → builtin 만 (안전 fallback)
        share_counts = {}
        source_urls = {}
        # [perf 2026-06-12] share_count 를 소싱처마다(N+1) 대신 1회 배치로 — pre-pass 로
        #   (source_key, legacy_url) 쌍을 모아 한 번에 조회.
        _share_map = {}
        try:
            from lemouton.sources.service import get_share_counts_batch
            _share_pairs = [
                (src['key'], getattr(m, f"url_{src['key']}", None) or '')
                for src in all_sources
                if src.get('legacy') and (getattr(m, f"url_{src['key']}", None) or '')
            ]
            if _share_pairs:
                _share_map = get_share_counts_batch(s, _share_pairs)
        except Exception:
            _share_map = {}
        # [perf 2026-05-29] BundleSourceUrl 을 소스키마다 쿼리(N+1)하지 않고 1회 조회 후 group.
        _bsu_by_key = {}
        try:
            for _r in (s.query(BundleSourceUrl)
                       .filter_by(model_code=code)
                       .order_by(BundleSourceUrl.source_key,
                                 BundleSourceUrl.sort_order, BundleSourceUrl.id)
                       .all()):
                _bsu_by_key.setdefault(_r.source_key, []).append(_r)
        except Exception as _e:
            import logging
            logging.warning(f"BundleSourceUrl batch query fail (code={code}): {_e}")
            try:
                s.rollback()
            except Exception:
                pass
        for src in all_sources:
            sk = src['key']
            # legacy 단일 URL — builtin 만 Model 컬럼 보유 (custom 은 컬럼 없음)
            legacy_url = (getattr(m, f'url_{sk}', None) or '') if src.get('legacy') else ''
            # share_count — [perf 2026-06-12] 위 pre-pass 배치 결과(_share_map)에서 읽음(N+1 제거).
            share_counts[sk] = _share_map.get((sk, legacy_url), 0) if legacy_url else 0
            # 다중 URL (BundleSourceUrl) — 위에서 batch 조회한 것 사용
            rows = _bsu_by_key.get(sk, [])
            if rows:
                source_urls[sk] = [{'id': r.id, 'url': r.url} for r in rows]
            elif legacy_url:
                source_urls[sk] = [{'id': None, 'url': legacy_url}]
            else:
                source_urls[sk] = []

        # ★ status_cards 를 session 닫기 전에 계산 (m.* access 가 session 필요)
        # 한글 model_code 등 일부 케이스에서 transaction abort 후 m 컬럼 expire → DetachedInstanceError
        try:
            last_crawled_at = m.last_crawled_at
            last_uploaded_at = m.last_uploaded_at
        except Exception:
            try:
                s.rollback()
                m_re = s.query(Model).filter_by(model_code=code).first()
                last_crawled_at = m_re.last_crawled_at if m_re else None
                last_uploaded_at = m_re.last_uploaded_at if m_re else None
            except Exception:
                last_crawled_at = None
                last_uploaded_at = None
        status_cards = {
            'last_crawled_ago': _humanize_ago(last_crawled_at),
            'last_crawled_at': _fmt_dt(last_crawled_at),
            'last_crawled_at_iso': _iso_utc(last_crawled_at),
            'last_uploaded_ago': _humanize_ago(last_uploaded_at),
            'last_uploaded_at': _fmt_dt(last_uploaded_at),
            'last_uploaded_at_iso': _iso_utc(last_uploaded_at),
        }

        # [2026-05-24] 마켓 동적 로드 — 가격설정 → 크롤 영역 v2 C 시안
        # builtin (스토어/쿠팡) = 기존 ss_margin_*, coupang_margin_* 컬럼 마진 사용
        # custom (11번가/G마켓 등) = placeholder (마진 입력 disabled — Phase 2 일반화)
        try:
            # [perf 2026-06-12] 마켓 레지스트리도 관리자가 가끔만 바꾸는 설정 → 60초 TTL 캐시.
            from shared.ref_cache import cached as _ref_cached
            from lemouton.sourcing.models import MarketRegistry

            def _load_markets():
                _rows = (s.query(MarketRegistry)
                         .filter_by(is_active=True)
                         .order_by(MarketRegistry.sort_order, MarketRegistry.id).all())
                return [{
                    'id': mk.id, 'market_key': mk.market_key, 'label': mk.label,
                    'logo_color': mk.logo_color, 'logo_letter': mk.logo_letter,
                    'is_builtin': mk.is_builtin,
                } for mk in _rows]
            markets_payload = _ref_cached('page:markets_payload', 60.0, _load_markets)
        except Exception:
            markets_payload = []
    finally:
        s.close()
    # 실행 이력 (최근 20건) — 크롤(소싱처별) + 업로드(마켓별) 결과 포함
    try:
        from lemouton.sourcing.run_history import list_for_bundle
        run_history = list_for_bundle(code, limit=20)
    except Exception:
        run_history = []

    return render_template(
        'bundles/edit.html',
        active='bundles',
        bundle=m,
        categories=_all_categories(),
        options=options,
        price_templates=price_templates,
        color_templates=color_templates,
        size_templates=size_templates,
        applied_price=applied_price,
        applied_color=applied_color,
        applied_size=applied_size,
        combos=combos,
        share_counts=share_counts,
        source_urls=source_urls,
        source_registry=all_sources,  # builtin + DB (v6 P5.5 — custom 도 노출)
        cluster_models=cluster_models,
        run_history=run_history,
        status_cards=status_cards,
        markets=markets_payload,  # [2026-05-24] 가격설정 → 크롤 영역 동적 마켓
    )


# ═══════ 다중 URL API (2026-05-09) ═══════
# v6 P5.5 — builtin + DB SourcingSource 동적 검증 (사용자 추가 소싱처도 valid)
VALID_SOURCE_KEYS = set(_src_keys())  # builtin (시작 시점). 검증은 _is_valid_source_key() 사용 권장.

def _is_valid_source_key(key: str) -> bool:
    """builtin 또는 DB 등록된 source_key 인지 검증 (매 호출 시 DB 조회)."""
    if not key:
        return False
    if key in VALID_SOURCE_KEYS:
        return True
    # DB SourcingSource 조회
    s = SessionLocal()
    try:
        from lemouton.sourcing.models import SourcingSource
        return bool(s.query(SourcingSource).filter_by(source_key=key, is_active=True).first())
    finally:
        s.close()


def _sync_legacy_url_column(s, code, source_key):
    """다중 URL 의 첫 번째를 Model.url_<source_key> 에 sync (legacy 호환).

    builtin 5 소싱처만 url_<key> 컬럼 보유 — custom 소싱처는 skip (BundleSourceUrl 만 사용).
    """
    if source_key not in VALID_SOURCE_KEYS:
        return  # custom — legacy 컬럼 없음
    first = (s.query(BundleSourceUrl)
             .filter_by(model_code=code, source_key=source_key)
             .order_by(BundleSourceUrl.sort_order, BundleSourceUrl.id)
             .first())
    m = s.query(Model).filter_by(model_code=code).first()
    if not m:
        return
    setattr(m, f'url_{source_key}', first.url if first else None)


# v25 시안 C — 모델 단위 다중 URL 조회 (drawer 용)
@bp.route('/api/bundles/<code>/source-urls', methods=['GET'])
def api_list_source_urls(code):
    """모델 단위 BundleSourceUrl 전체 조회.
    응답: {
      ok: True,
      urls: {source_key: [{id, url, label, sort_order, option_ids: [sku,...]}, ...], ...},
      options: [{canonical_sku, color_code, color_display, size_code, size_display, axis_values}, ...],
      sources: [...]
    }
    legacy 단일 컬럼 (Model.url_<sk>) 도 다중 행이 없으면 자동 표현 (id=null).

    [2026-05-24] options 매트릭스 정보 + URL별 option_ids 매핑 포함.
    """
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if not m:
            return jsonify({'ok': False, 'error': 'bundle not found'}), 404

        # URL → option_ids 매핑 일괄 조회 (N+1 회피)
        all_url_ids = [r.id for r in s.query(BundleSourceUrl.id)
                       .filter_by(model_code=code).all()]
        link_map = {}  # url_id -> [canonical_sku, ...]
        if all_url_ids:
            links = (s.query(OptionSourceUrlLink)
                     .filter(OptionSourceUrlLink.bundle_source_url_id.in_(all_url_ids))
                     .all())
            for ln in links:
                link_map.setdefault(ln.bundle_source_url_id, []).append(ln.option_canonical_sku)

        urls = {}
        all_keys = set(get_all_keys(session=s))  # builtin + DB
        # [perf 2026-05-29] 소스키마다 쿼리(N회) 하지 않고 model_code 1회 조회 후 in-memory group.
        #   모달 임계경로(source-urls) 지연을 줄임 — 결과 동일.
        from collections import defaultdict as _dd
        _rows_by_key = _dd(list)
        for r in (s.query(BundleSourceUrl)
                  .filter_by(model_code=code)
                  .order_by(BundleSourceUrl.source_key,
                            BundleSourceUrl.sort_order, BundleSourceUrl.id)
                  .all()):
            _rows_by_key[r.source_key].append(r)
        # [2026-06-05] URL별 크롤 상태 — 실패 URL 빨강·재크롤(모달)용.
        #   성공 판정 = is_crawl_valid(가격>0 AND status!=error). 매트릭스 대시보드와 동일 게이트.
        from lemouton.sources.models import SourceProduct as _SP
        from lemouton.sources.service import normalize_url as _nu
        from lemouton.pricing.unified import is_crawl_valid as _is_crawl_valid
        _crawl_idx = {}
        try:
            for _sp in (s.query(_SP.url, _SP.last_price, _SP.last_status)
                        .filter(_SP.deleted_at.is_(None)).all()):
                if _sp.url:
                    _crawl_idx[_nu(_sp.url)] = (_sp.last_price, _sp.last_status)
        except Exception:
            _crawl_idx = {}
        def _crawl_state(u):
            # [2026-06-12] SSG 딜(dealItemView) = 색상별 단품 URL 로 가격·재고가 커버되는 허브.
            #   파이프라인이 크롤을 skip 하므로 '실패'가 아니라 'covered'(중립)로 표시한다.
            #   (URL 패턴으로 감지 — SourceProduct 의 옛 error 상태를 무시)
            if u and 'dealitemview' in u.lower():
                return True, 'covered', None
            rec = _crawl_idx.get(_nu(u)) if u else None
            # [2026-06-11] 대시보드(api_pricing)와 동일 게이트로 통일 — 가격>0 AND status!=error.
            #   기존엔 가격>0 만 보고 status 를 무시 → error+옛가격(stale) URL 을 '성공'으로
            #   둔갑시킴. 그 결과 대시보드 카드는 "URL N개 실패", 모달은 전부 정상(초록)으로
            #   서로 모순. is_crawl_valid 단일 게이트로 묶어 두 화면 판정을 일치시킨다.
            ok = bool(_is_crawl_valid(rec[0], rec[1])) if rec else False
            return ok, (rec[1] if rec else 'not_crawled'), (rec[0] if rec else None)
        for sk in all_keys:
            rows = _rows_by_key.get(sk, [])
            if rows:
                urls[sk] = []
                for r in rows:
                    _ok, _stt, _pr = _crawl_state(r.url)
                    urls[sk].append({
                        'id': r.id,
                        'url': r.url,
                        'label': r.label or '',
                        'sort_order': r.sort_order,
                        'option_ids': link_map.get(r.id, []),
                        'crawled': _ok,
                        'last_status': _stt,
                        'last_price': _pr,
                    })
            else:
                legacy = getattr(m, f'url_{sk}', None) if sk in VALID_SOURCE_KEYS else None
                if legacy:
                    _ok, _stt, _pr = _crawl_state(legacy)
                    urls[sk] = [{
                        'id': None, 'url': legacy, 'label': '',
                        'sort_order': 0, 'option_ids': [],
                        'crawled': _ok, 'last_status': _stt, 'last_price': _pr,
                    }]
                else:
                    urls[sk] = []

        # 옵션 매트릭스 정보 — 프론트가 빠른 선택 칩 + 매트릭스 그릴 때 사용
        import json as _json
        opts = (s.query(Option)
                .filter_by(model_code=code)
                .order_by(Option.sort_order, Option.canonical_sku)
                .all())
        options_payload = []
        for o in opts:
            axis_values = None
            if o.axis_values_json:
                try:
                    axis_values = _json.loads(o.axis_values_json)
                except Exception:
                    axis_values = None
            options_payload.append({
                'canonical_sku': o.canonical_sku,
                'color_code': o.color_code,
                'color_display': o.color_display or o.color_code,
                'size_code': o.size_code,
                'size_display': o.size_display or o.size_code,
                'axis_values': axis_values,
                # [2026-05-27 D1] 사용자 OFF 한 옵션 표시 (False=빗금, True=일반)
                'is_active': bool(getattr(o, 'is_active', True)),
            })

        # [2026-05-24 A-1 FIX] BundleOptionStep — 축 이름·값 단일 진실 원천
        # 옵션의 axis_values 는 단순 값 array 만 저장됨 → axis name 은 여기서 가져옴
        try:
            from lemouton.sourcing.models import BundleOptionStep
            steps = (s.query(BundleOptionStep)
                     .filter_by(model_code=code)
                     .order_by(BundleOptionStep.step_no)
                     .all())
            axis_steps_payload = []
            for st in steps:
                try:
                    vals = _json.loads(st.values_json or '[]')
                    if not isinstance(vals, list):
                        vals = []
                except Exception:
                    vals = []
                axis_steps_payload.append({
                    'step_no': st.step_no,
                    'axis_name': st.axis_name or '',
                    'values': [str(v) for v in vals],
                })
        except Exception:
            axis_steps_payload = []

        # [2026-05-24 A-1-FIX v3] 자동 axis_steps — BundleOptionStep 미생성 모음전(레거시) 대응
        #   · 단일 진실 원천을 백엔드로 일원화 — 프론트는 항상 axis_steps 만 신뢰
        #   · color_display / size_display 로부터 색상·사이즈 2축 자동 추정
        #   · options_payload[].axis_values 도 함께 채워서 매트릭스 선택 셀 매핑 가능하게
        #   · 자동 추정은 응답 직전에만 — DB 에 BundleOptionStep 새로 만들지 않음 (read-only)
        if not axis_steps_payload and options_payload:
            from collections import OrderedDict
            colors = list(OrderedDict.fromkeys(
                o['color_display'] for o in options_payload
                if o.get('color_display')
            ))
            sizes = list(OrderedDict.fromkeys(
                o['size_display'] for o in options_payload
                if o.get('size_display')
            ))
            auto = []
            if colors:
                auto.append({'step_no': len(auto) + 1, 'axis_name': '색상', 'values': colors})
            if sizes:
                auto.append({'step_no': len(auto) + 1, 'axis_name': '사이즈', 'values': sizes})
            if auto:
                axis_steps_payload = auto
                # 각 옵션에 axis_values 채워서 매트릭스 선택 셀 매핑 가능하게
                axis_names = [st['axis_name'] for st in auto]
                for o in options_payload:
                    vals = []
                    if '색상' in axis_names:
                        vals.append(o.get('color_display') or '')
                    if '사이즈' in axis_names:
                        vals.append(o.get('size_display') or '')
                    # 기존 axis_values 가 None 일 때만 덮어쓰기 — 정식 단계형 옵션은 보존
                    if o.get('axis_values') is None:
                        o['axis_values'] = vals

        # [2026-05-25 A-2-FIX] axis_steps 가 있어도 axis_values=null 인 옵션은 매핑 채워줌
        #   배경: 어제 모달 저장으로 BundleOptionStep 신규 생성됨 → 자동 fallback(위 블록) 미진입
        #   → 옛 옵션(axis_values_json=null) 89개가 모달 매트릭스에서 비활성 표시되는 위험
        #   → 사용자가 prune 저장 시 89개 모두 삭제될 수 있음 (데이터 파괴)
        #   해결: axis_steps 값 풀과 옵션의 color/size 가 매칭되면 axis_values 동적 채움
        if axis_steps_payload and options_payload:
            axis_val_sets = [set(st['values']) for st in axis_steps_payload]
            n_axes = len(axis_steps_payload)
            for o in options_payload:
                if o.get('axis_values') is not None:
                    continue
                color = o.get('color_display')
                size = o.get('size_display')
                # 2축: [color, size] 매칭 시도
                if n_axes == 2 and color in axis_val_sets[0] and size in axis_val_sets[1]:
                    o['axis_values'] = [color, size]
                elif n_axes == 1 and color in axis_val_sets[0]:
                    o['axis_values'] = [color]
                # 매칭 실패 옵션은 axis_values=null 유지 — 모달에서 비활성 표시되나
                # 사용자가 prune 저장 안 하면 안전. prune 저장 시 keep_skus 에
                # build_sku(model_code, None) 이 없어 삭제될 수 있음 — 별도 보호 필요

        return jsonify({
            'ok': True,
            'urls': urls,
            'options': options_payload,
            'axis_steps': axis_steps_payload,
            'sources': sorted(all_keys),
        })
    finally:
        s.close()


def _sync_option_links(session, code, url_id, option_ids):
    """URL ↔ Option N:N 매핑 동기화.

    option_ids = None 이면 매핑 변경 없음.
    빈 list = 매핑 전부 해제.
    각 sku 가 그 model_code 의 옵션인지 검증 (보안 — 타 모델 옵션 매핑 차단).
    """
    if option_ids is None:
        return
    # 기존 매핑 모두 삭제
    (session.query(OptionSourceUrlLink)
     .filter_by(bundle_source_url_id=url_id)
     .delete(synchronize_session=False))
    if not option_ids:
        return
    # 유효성 검증 — 같은 model_code 의 옵션만 허용
    valid_skus = {
        r[0] for r in
        session.query(Option.canonical_sku)
        .filter(Option.model_code == code, Option.canonical_sku.in_(option_ids))
        .all()
    }
    for sku in option_ids:
        if sku not in valid_skus:
            continue  # 다른 모델 옵션·존재 X — 조용히 skip
        session.add(OptionSourceUrlLink(
            option_canonical_sku=sku,
            bundle_source_url_id=url_id,
        ))


@bp.route('/api/bundles/<code>/source-urls', methods=['POST'])
def api_add_source_url(code):
    body = request.get_json(silent=True) or {}
    source_key = (body.get('source_key') or '').strip()
    url = (body.get('url') or '').strip()
    label = (body.get('label') or '').strip() or None
    option_ids = body.get('option_ids')  # None | list[str]
    if option_ids is not None and not isinstance(option_ids, list):
        return jsonify({'ok': False, 'error': 'option_ids must be list'}), 400
    if not _is_valid_source_key(source_key):
        return jsonify({'ok': False, 'error': 'invalid source_key'}), 400
    if not url:
        return jsonify({'ok': False, 'error': 'url required'}), 400
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if not m:
            return jsonify({'ok': False, 'error': 'bundle not found'}), 404
        # legacy 단일 URL 이 있는데 다중 행이 0개면 먼저 1개 행으로 마이그레이트
        existing = s.query(BundleSourceUrl).filter_by(model_code=code, source_key=source_key).count()
        legacy = getattr(m, f'url_{source_key}', None) or ''
        if existing == 0 and legacy:
            s.add(BundleSourceUrl(model_code=code, source_key=source_key, url=legacy, sort_order=0))
            s.flush()
        max_order = (s.query(BundleSourceUrl.sort_order)
                     .filter_by(model_code=code, source_key=source_key)
                     .order_by(BundleSourceUrl.sort_order.desc())
                     .first())
        next_order = (max_order[0] + 1) if max_order else 0
        row = BundleSourceUrl(
            model_code=code,
            source_key=source_key,
            url=url,
            label=label,
            sort_order=next_order,
        )
        s.add(row)
        s.flush()
        _sync_legacy_url_column(s, code, source_key)
        _sync_option_links(s, code, row.id, option_ids)
        s.commit()
        return jsonify({
            'ok': True,
            'id': row.id,
            'url': row.url,
            'label': row.label or '',
            'sort_order': row.sort_order,
            'option_ids': option_ids or [],
        })
    finally:
        s.close()


@bp.route('/api/bundles/<code>/source-urls/<int:url_id>', methods=['PUT'])
def api_update_source_url(code, url_id):
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        row = s.query(BundleSourceUrl).filter_by(id=url_id, model_code=code).first()
        if not row:
            return jsonify({'ok': False, 'error': 'not found'}), 404

        # url — 명시적으로 키 있으면 적용 (빈 문자열 차단)
        if 'url' in body:
            new_url = (body.get('url') or '').strip()
            if not new_url:
                return jsonify({'ok': False, 'error': 'url required'}), 400
            row.url = new_url

        # label — 빈 문자열 = NULL
        if 'label' in body:
            lbl = (body.get('label') or '').strip()
            row.label = lbl or None

        # option_ids — None 이면 손대지 않음, list 면 동기화
        option_ids = body.get('option_ids')
        if option_ids is not None and not isinstance(option_ids, list):
            return jsonify({'ok': False, 'error': 'option_ids must be list'}), 400
        _sync_option_links(s, code, row.id, option_ids)

        # [2026-05-27] sort_order — 카드 순서 변경 지원
        if 'sort_order' in body:
            try:
                row.sort_order = int(body['sort_order'])
            except (TypeError, ValueError):
                pass

        _sync_legacy_url_column(s, code, row.source_key)
        s.commit()

        # 최종 option_ids 응답
        final_links = [ln.option_canonical_sku for ln in
                       s.query(OptionSourceUrlLink)
                       .filter_by(bundle_source_url_id=row.id).all()]
        return jsonify({
            'ok': True,
            'id': row.id,
            'url': row.url,
            'label': row.label or '',
            'option_ids': final_links,
        })
    finally:
        s.close()


@bp.route('/api/bundles/<code>/source-urls/<int:url_id>', methods=['DELETE'])
def api_delete_source_url(code, url_id):
    s = SessionLocal()
    try:
        row = s.query(BundleSourceUrl).filter_by(id=url_id, model_code=code).first()
        if not row:
            return jsonify({'ok': False, 'error': 'not found'}), 404
        sk = row.source_key
        s.delete(row)
        s.flush()
        _sync_legacy_url_column(s, code, sk)
        s.commit()
        return jsonify({'ok': True})
    finally:
        s.close()


# ═══════════════════════════════════════════════════════════════════
#  Phase 4 (2026-05-28) — 모음전 옵션 ↔ 재고관리 옵션 매핑 (페이지 + API)
# ═══════════════════════════════════════════════════════════════════

@bp.route('/bundles/<code>/inventory-mapping')
def bundle_inventory_mapping(code):
    """B3-3 in-place 매핑 표 + E2 누적 색·도트 페이지."""
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if not m:
            return ('bundle not found', 404)
        opts = (s.query(Option)
                .filter_by(model_code=code)
                .order_by(Option.sort_order, Option.canonical_sku)
                .all())
        return render_template(
            'bundles/inventory_mapping.html',
            active='bundles',
            bundle=m,
            bundle_options=opts,
        )
    finally:
        s.close()

# [2026-05-29] 표기 차이 alias — shared 단일 진실 원천 사용
#   기존 _normalize_label 은 normalize_label 의 alias (호환)
from shared.sku_format import (
    normalize_label as _normalize_label,
    color_matches as _color_matches,
    size_matches as _size_matches,
)


@bp.route('/api/bundles/<code>/inventory-mapping', methods=['GET'])
def api_get_inventory_mapping(code):
    """모음전의 옵션 ↔ 재고 매핑 + 매핑 후보 (브랜드/모델 우선 + alias 매칭) 조회.

    Query Params:
      brand: 매칭 한정 브랜드 (선택). 없으면 모음전 자체 브랜드 자동 사용.
      model: 매칭 한정 모델명 (선택). 없으면 모음전 자체 모델 자동 사용.

    Returns:
      {
        ok: True,
        mappings: { bundle_sku: [inventory_sku, ...], ... },
        inventory_options: [{ sku, model_code, model_name, color, size,
                              stock_total, brand }, ...],
        candidates: { bundle_sku: [inv_sku, ...], ... }  # 점수 순 정렬
        bundle_meta: { brand, model_name, model_code }   # 자동 추론용
        brands: [{ name, model_count, option_count }, ...]   # 브랜드 검색용
        models_by_brand: { 브랜드: [{ model_name, option_count }, ...] }
      }
    """
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if not m:
            return jsonify({'ok': False, 'error': 'bundle not found'}), 404

        # [v20.6] 브랜드+모델 필터 — Query Param 명시한 경우만. 빈값이면 전체 풀에서 매칭.
        #   사용자 의도: 처음엔 공란 → 사용자가 직접 선택. bundle_meta 자동 추론 안 함.
        bundle_brand = (m.brand or '').strip()
        bundle_model_name = (m.model_name_display or m.model_name_raw or '').strip()
        filter_brand = (request.args.get('brand') or '').strip()
        filter_model = (request.args.get('model') or '').strip()

        # 1. 모음전 옵션
        bundle_opts = s.query(Option).filter_by(model_code=code).all()
        bundle_skus = [o.canonical_sku for o in bundle_opts]

        # 2. 기존 매핑
        links = s.query(OptionInventoryLink).filter(
            OptionInventoryLink.bundle_option_sku.in_(bundle_skus)
        ).all() if bundle_skus else []
        mappings: dict[str, list[str]] = {sk: [] for sk in bundle_skus}
        for ln in links:
            mappings.setdefault(ln.bundle_option_sku, []).append(ln.inventory_option_sku)

        # 3. 재고관리 옵션 — 전체 옵션 (필터 없음, 자기 자신 SKU 포함)
        #   [v20.11 2026-06-01] 모음전 옵션 = 재고관리 옵션 동일 row 케이스
        #   (르무통·잔스포츠·빔즈 — model_code 공유) 에서 자기 SKU 제외 시 자기 모델 통째로 빠짐.
        #   해결: 필터 자체 제거 → 모든 옵션 후보 풀 포함. dropdown 에 자기 모델 표시되어
        #   사용자가 동일 SKU 와 매핑 가능. [2026-06-02] POST 저장도 self 매핑 허용으로
        #   일치시킴 (이전엔 POST 가 self 를 차단해 102건→8건만 저장되던 모순 버그).
        inv_opts_q = s.query(Option, Model).join(
            Model, Option.model_code == Model.model_code
        )
        inv_opts = inv_opts_q.all()
        inventory_options = []
        for opt, mdl in inv_opts:
            inventory_options.append({
                'sku': opt.canonical_sku,
                'boxhero_sku': opt.boxhero_sku or '',
                'model_code': opt.model_code,
                'model_name': (mdl.model_name_display or mdl.model_name_raw or '').strip(),
                'brand': (mdl.brand or '').strip(),
                'color': (opt.color_display or opt.color_code or '').strip(),
                'size': (opt.size_display or opt.size_code or '').strip(),
                'stock_total': opt.boxhero_stock_total or 0,
                'is_standalone': opt.model_code.startswith('단독_'),
            })

        # [v20] 브랜드·모델 메타 (검색 dropdown 용)
        #   모음전 외 모든 모델을 브랜드별 그룹화.
        brand_counts: dict[str, dict] = {}
        models_by_brand: dict[str, dict[str, int]] = {}
        for inv in inventory_options:
            b = inv['brand'] or '미상'
            mn = inv['model_name'] or '미상'
            brand_counts.setdefault(b, {'name': b, 'model_set': set(), 'option_count': 0})
            brand_counts[b]['model_set'].add(mn)
            brand_counts[b]['option_count'] += 1
            models_by_brand.setdefault(b, {}).setdefault(mn, 0)
            models_by_brand[b][mn] += 1
        brands = [
            {'name': v['name'], 'model_count': len(v['model_set']), 'option_count': v['option_count']}
            for v in sorted(brand_counts.values(), key=lambda x: -x['option_count'])
        ]
        models_by_brand_serial = {
            b: sorted([{'model_name': mn, 'option_count': c} for mn, c in mdic.items()],
                      key=lambda x: -x['option_count'])
            for b, mdic in models_by_brand.items()
        }

        # 4. 자동 후보 — color/size alias 매칭 + 브랜드/모델 점수제
        from shared.sku_format import (
            normalize_label as _norm, color_groups as _cgroups, size_groups as _sgroups,
        )
        inv_norm = []  # [(sku, cn, cg, sn, sg, brand, model_name, model_code), ...]
        for inv in inventory_options:
            inv_norm.append((
                inv['sku'],
                _norm(inv['color']), _cgroups(inv['color']),
                _norm(inv['size']), _sgroups(inv['size']),
                inv['brand'], inv['model_name'], inv['model_code'],
            ))

        # 점수제 매칭 — 선택 브랜드+모델 (100) > 모음전 model_code 동일 (50) > color+size alias (각 10)
        candidates: dict[str, list[str]] = {}
        for b_opt in bundle_opts:
            b_color_raw = b_opt.color_display or b_opt.color_code
            b_size_raw = b_opt.size_display or b_opt.size_code
            bcn, bcg = _norm(b_color_raw), _cgroups(b_color_raw)
            bsn, bsg = _norm(b_size_raw), _sgroups(b_size_raw)
            if not bcn or not bsn:
                continue
            scored = []  # [(score, sku), ...]
            for sku, cn, cg, sn, sg, ibr, imn, imc in inv_norm:
                color_ok = cn and (cn == bcn or (cg and bcg and (cg & bcg)))
                if not color_ok:
                    continue
                size_ok = sn and (sn == bsn or (sg and bsg and (sg & bsg)))
                if not size_ok:
                    continue
                # 점수 계산
                score = 20  # base = color+size alias 매칭
                if filter_brand and filter_model and ibr == filter_brand and imn == filter_model:
                    score += 100
                elif imc == code:
                    score += 50  # (이론상 model_code != code 필터로 제외됐으나 안전)
                # 같은 브랜드만 일치도 부분 점수
                if filter_brand and ibr == filter_brand and score < 100:
                    score += 5
                scored.append((score, sku))
            if scored:
                # 점수 높은 순 정렬, 동점은 sku 사전순
                scored.sort(key=lambda x: (-x[0], x[1]))
                candidates[b_opt.canonical_sku] = [s for _, s in scored]

        return jsonify({
            'ok': True,
            'mappings': mappings,
            'inventory_options': inventory_options,
            'candidates': candidates,
            'bundle_meta': {
                'brand': bundle_brand,
                'model_name': bundle_model_name,
                'model_code': code,
            },
            'filter_applied': {
                'brand': filter_brand,
                'model': filter_model,
            },
            'brands': brands,
            'models_by_brand': models_by_brand_serial,
        })
    finally:
        s.close()


@bp.route('/api/bundles/<code>/inventory-mapping', methods=['POST'])
def api_save_inventory_mapping(code):
    """모음전 옵션 ↔ 재고 매핑 일괄 저장.

    body: { mappings: { bundle_sku: [inventory_sku, ...], ... } }
    동작:
      - 본 모음전 옵션들의 기존 매핑 모두 삭제 → 새로 INSERT (replace 패턴)
      - 본 모음전이 아닌 sku 는 무시
    """
    body = request.get_json(silent=True) or {}
    mappings = body.get('mappings') or {}
    if not isinstance(mappings, dict):
        return jsonify({'ok': False, 'error': 'mappings must be object'}), 400

    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if not m:
            return jsonify({'ok': False, 'error': 'bundle not found'}), 404

        bundle_skus = [o.canonical_sku for o in s.query(Option).filter_by(model_code=code).all()]
        bundle_sku_set = set(bundle_skus)

        # 기존 매핑 전부 삭제 (본 모음전 옵션들만)
        if bundle_skus:
            (s.query(OptionInventoryLink)
             .filter(OptionInventoryLink.bundle_option_sku.in_(bundle_skus))
             .delete(synchronize_session=False))

        # 새 매핑 추가 — 유효한 본 모음전 sku + 존재하는 inventory sku 만
        all_skus = {row[0] for row in s.query(Option.canonical_sku).all()}
        added = 0
        for b_sku, inv_list in mappings.items():
            if b_sku not in bundle_sku_set:
                continue
            if not isinstance(inv_list, list):
                continue
            seen = set()
            for inv_sku in inv_list:
                if not isinstance(inv_sku, str):
                    continue
                # [2026-06-02 BUG FIX] 자기 자신 매핑 허용.
                #   르무통·잔스포츠·빔즈 등 모음전 옵션 = 재고관리 옵션이 같은 row(model_code 공유)
                #   인 경우, 정상 매핑이 곧 동일 SKU(identity)다. 이전엔 여기서 차단해
                #   자동매칭 102건 중 self 매핑 94건이 조용히 버려지고 8건만 저장되는 버그였음.
                #   GET(api_get_inventory_mapping, line ~1271) 은 이미 self 후보를 의도적으로
                #   포함 → 저장도 일치시켜 허용. (UNIQUE(bundle,inventory) 로 중복은 차단됨.)
                if inv_sku in seen:            # 같은 매핑 중복 방지
                    continue
                if inv_sku not in all_skus:    # 존재하지 않는 sku 차단
                    continue
                seen.add(inv_sku)
                s.add(OptionInventoryLink(
                    bundle_option_sku=b_sku,
                    inventory_option_sku=inv_sku,
                ))
                added += 1
        s.commit()
        return jsonify({'ok': True, 'mapped': added})
    except Exception as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()


@bp.route('/api/options/<sku>/adjust-stock', methods=['POST'])
def api_adjust_option_stock(sku):
    """[2026-06-03] 가격 매트릭스 '재고' 배지 팝업 — 단일 옵션 재고 수정.

    기존 재고관리 '조정'(create_adjustment) 경로를 그대로 재사용 → 이력 남고
    boxhero_stock_total 한 칸만 절대값 set. 전체 화면 동기화 + 중복/모순 없음.

    body: { new_qty: int (>=0), memo?: str }
    """
    body = request.get_json(silent=True) or {}
    try:
        new_qty = int(body.get('new_qty'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'new_qty 정수 필요'}), 400
    if new_qty < 0:
        return jsonify({'ok': False, 'error': '재고는 0 이상이어야 합니다'}), 400
    memo = (body.get('memo') or '').strip()

    s = SessionLocal()
    try:
        opt = s.query(Option).filter_by(canonical_sku=sku).first()
        if not opt:
            return jsonify({'ok': False, 'error': '옵션 없음'}), 404
        from lemouton.inventory.locations import list_active
        from lemouton.inventory import inbound as tx_svc
        locs = list_active(s)
        if not locs:
            return jsonify({'ok': False, 'error': '재고 위치가 없습니다'}), 400
        # 기본 위치 (is_default) → 없으면 첫 위치
        loc = next((l for l in locs if getattr(l, 'is_default', False)), locs[0])
        tx_svc.create_adjustment(
            s, location_id=loc.id, option_canonical_sku=sku, new_qty=new_qty,
            memo=memo or '가격 매트릭스에서 재고 수정', created_by='운영자',
        )
        s.commit()
        return jsonify({'ok': True, 'new_qty': new_qty})
    except Exception as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()


# ───────── v26 [2026-06-01] color_code 잔존 모델명 prefix 정리 ─────────

@bp.route('/api/admin/color-code-audit', methods=['GET'])
def api_color_code_audit():
    """전수 진단 — Option.color_code != color_display 인 옵션 모음전별 그룹.

    Returns:
      {
        ok: True,
        total_dirty: N,
        by_bundle: {
          model_code: [
            {sku, color_code, color_display, size_display, is_active,
             dup_with_sku (같은 color_display+size 인 정상 sku), url_links, inv_links},
            ...
          ]
        }
      }
    """
    s = SessionLocal()
    try:
        from sqlalchemy import func
        # color_display 비어있지 않으면서 color_code != color_display 인 옵션
        dirty = s.query(Option).filter(
            Option.color_display.isnot(None),
            Option.color_display != '',
            Option.color_code != Option.color_display,
        ).all()

        # 매핑 카운트 (url, inv) 집계
        skus = [o.canonical_sku for o in dirty]
        url_link_count = {}
        inv_link_count = {}
        if skus:
            url_rows = s.query(
                OptionSourceUrlLink.option_canonical_sku, func.count(OptionSourceUrlLink.id)
            ).filter(OptionSourceUrlLink.option_canonical_sku.in_(skus)
            ).group_by(OptionSourceUrlLink.option_canonical_sku).all()
            url_link_count = {sku: cnt for sku, cnt in url_rows}
            inv_rows = s.query(
                OptionInventoryLink.bundle_option_sku, func.count(OptionInventoryLink.id)
            ).filter(OptionInventoryLink.bundle_option_sku.in_(skus)
            ).group_by(OptionInventoryLink.bundle_option_sku).all()
            inv_link_count = {sku: cnt for sku, cnt in inv_rows}

        # 같은 (color_display, size_display) 정상 sku 가 있는지 — 중복 후보
        # 모델별로 lookup table
        by_bundle = {}
        for o in dirty:
            row = {
                'sku': o.canonical_sku,
                'color_code': o.color_code,
                'color_display': o.color_display,
                'size_code': o.size_code,
                'size_display': o.size_display,
                'is_active': bool(o.is_active),
                'stock': o.boxhero_stock_total or 0,
                'url_links': int(url_link_count.get(o.canonical_sku, 0)),
                'inv_links': int(inv_link_count.get(o.canonical_sku, 0)),
            }
            # 같은 모델 내 정상 sku 찾기 — size_code + size_display 양쪽 매칭 (NULL 대응)
            from sqlalchemy import or_, and_
            size_filters = []
            if o.size_code:
                size_filters.append(Option.size_code == o.size_code)
            if o.size_display:
                size_filters.append(Option.size_display == o.size_display)
            if not size_filters:
                size_filters.append(Option.size_code.is_(None))
            twin = s.query(Option).filter(
                Option.model_code == o.model_code,
                Option.color_code == o.color_display,  # 정상 color_code = display 와 일치
                or_(*size_filters),
                Option.canonical_sku != o.canonical_sku,
            ).first()
            row['dup_with_sku'] = twin.canonical_sku if twin else None
            by_bundle.setdefault(o.model_code, []).append(row)

        # 정렬 — 모음전 코드 알파벳
        sorted_bundles = dict(sorted(by_bundle.items()))
        return jsonify({
            'ok': True,
            'total_dirty': len(dirty),
            'bundle_count': len(sorted_bundles),
            'by_bundle': sorted_bundles,
        })
    finally:
        s.close()


# 중복 병합 시 보존행으로 이전할 시장/매입 식별자 (잉여행에만 있고 보존행이 비면 복사).
_MARKET_ID_FIELDS = [
    'naver_option_id', 'coupang_option_id', 'option_id_lemouton', 'option_id_musinsa',
    'option_id_ssf', 'option_id_lotteon', 'option_id_ss_lemouton', 'boxhero_sku', 'barcode',
]


def _dedup_merge(s, dry_run=True):
    """(model,color,size) 중복 옵션을 '보존행 1개'로 안전 병합.

    잉여행의 URL/재고 매핑을 보존행으로 이전(보존행이 이미 가진 매핑은 중복제거),
    시장ID(naver/coupang 등)는 보존행이 비었을 때만 복사(등록 손실 방지), 그 뒤 잉여행 삭제.
    dry_run=True 면 무엇을 할지 카운트만 하고 변경하지 않는다. 데이터 손실 없는 병합.
    """
    from sqlalchemy import func
    rep = {'groups': 0, 'redundant': 0, 'url_moved': 0, 'url_deduped': 0,
           'inv_moved': 0, 'inv_deduped': 0, 'ids_copied': 0, 'deleted': 0,
           'deleted_skus': []}
    dup_keys = (s.query(Option.model_code, Option.color_code, Option.size_code,
                        func.count(Option.canonical_sku))
                .group_by(Option.model_code, Option.color_code, Option.size_code)
                .having(func.count(Option.canonical_sku) > 1).all())
    for mc, cc, sz, _cnt in dup_keys:
        rows = (s.query(Option).filter(Option.model_code == mc,
                                       Option.color_code == cc,
                                       Option.size_code == sz).all())
        skus = [o.canonical_sku for o in rows]
        url_cnt = dict(s.query(OptionSourceUrlLink.option_canonical_sku,
                               func.count(OptionSourceUrlLink.id))
                       .filter(OptionSourceUrlLink.option_canonical_sku.in_(skus))
                       .group_by(OptionSourceUrlLink.option_canonical_sku).all())
        inv_cnt = dict(s.query(OptionInventoryLink.bundle_option_sku,
                               func.count(OptionInventoryLink.id))
                       .filter(OptionInventoryLink.bundle_option_sku.in_(skus))
                       .group_by(OptionInventoryLink.bundle_option_sku).all())

        def _score(o):
            return (1 if o.is_active else 0,
                    int(url_cnt.get(o.canonical_sku, 0)) + int(inv_cnt.get(o.canonical_sku, 0)),
                    -(o.created_at.timestamp() if o.created_at else 0))
        ordered = sorted(rows, key=_score, reverse=True)
        keeper = ordered[0]
        rep['groups'] += 1
        for r in ordered[1:]:
            rep['redundant'] += 1
            # URL 매핑 이전 (보존행이 같은 bundle_source_url 이미 있으면 중복제거)
            for lk in (s.query(OptionSourceUrlLink)
                       .filter(OptionSourceUrlLink.option_canonical_sku == r.canonical_sku).all()):
                dup = (s.query(OptionSourceUrlLink)
                       .filter(OptionSourceUrlLink.option_canonical_sku == keeper.canonical_sku,
                               OptionSourceUrlLink.bundle_source_url_id == lk.bundle_source_url_id)
                       .first())
                if dup is not None:
                    rep['url_deduped'] += 1
                    if not dry_run:
                        s.delete(lk)
                else:
                    rep['url_moved'] += 1
                    if not dry_run:
                        lk.option_canonical_sku = keeper.canonical_sku
            # 재고 매핑 이전
            for lk in (s.query(OptionInventoryLink)
                       .filter(OptionInventoryLink.bundle_option_sku == r.canonical_sku).all()):
                dup = (s.query(OptionInventoryLink)
                       .filter(OptionInventoryLink.bundle_option_sku == keeper.canonical_sku,
                               OptionInventoryLink.inventory_option_sku == lk.inventory_option_sku)
                       .first())
                if dup is not None:
                    rep['inv_deduped'] += 1
                    if not dry_run:
                        s.delete(lk)
                else:
                    rep['inv_moved'] += 1
                    if not dry_run:
                        lk.bundle_option_sku = keeper.canonical_sku
            # 시장/매입 ID 보존 (등록 손실 방지)
            for f in _MARKET_ID_FIELDS:
                if getattr(r, f, None) and not getattr(keeper, f, None):
                    rep['ids_copied'] += 1
                    if not dry_run:
                        setattr(keeper, f, getattr(r, f))
            rep['deleted'] += 1
            rep['deleted_skus'].append(r.canonical_sku)
            if not dry_run:
                s.flush()  # 매핑 이전(update/delete) 먼저 반영 후 잉여행 삭제
                s.delete(r)
    if not dry_run:
        s.commit()
    return rep


@bp.route('/api/admin/options/merge-dupes', methods=['POST'])
def api_merge_dupes():
    """(model,color,size) 중복 옵션 안전 병합. body: {dry_run: bool(기본 True)}

    잉여행 매핑을 보존행으로 이전 후 잉여행 삭제(데이터 손실 없음). dry_run=True 면 미리보기.
    """
    body = request.get_json(silent=True) or {}
    dry_run = bool(body.get('dry_run', True))
    s = SessionLocal()
    try:
        rep = _dedup_merge(s, dry_run=dry_run)
        rep['ok'] = True
        rep['dry_run'] = dry_run
        return jsonify(rep)
    except Exception as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()


@bp.route('/api/admin/options/cleanup-dupes', methods=['POST'])
def api_cleanup_dup_options():
    """잉여 옵션 일괄 삭제. body: {skus: [...], dry_run: bool}

    매핑 카운트 0 인 옵션만 삭제 (안전 가드). dry_run=True 면 삭제 안 하고 결과만.
    """
    body = request.get_json(silent=True) or {}
    skus = body.get('skus') or []
    dry_run = bool(body.get('dry_run', True))
    if not isinstance(skus, list) or not skus:
        return jsonify({'ok': False, 'error': 'skus required'}), 400
    s = SessionLocal()
    try:
        from sqlalchemy import func
        url_cnt = dict(s.query(OptionSourceUrlLink.option_canonical_sku, func.count(OptionSourceUrlLink.id))
                       .filter(OptionSourceUrlLink.option_canonical_sku.in_(skus))
                       .group_by(OptionSourceUrlLink.option_canonical_sku).all())
        inv_cnt = dict(s.query(OptionInventoryLink.bundle_option_sku, func.count(OptionInventoryLink.id))
                       .filter(OptionInventoryLink.bundle_option_sku.in_(skus))
                       .group_by(OptionInventoryLink.bundle_option_sku).all())
        safe, unsafe = [], []
        for sku in skus:
            u = int(url_cnt.get(sku, 0)); i = int(inv_cnt.get(sku, 0))
            if u == 0 and i == 0:
                safe.append(sku)
            else:
                unsafe.append({'sku': sku, 'url_links': u, 'inv_links': i})
        deleted = 0
        if not dry_run and safe:
            opts = s.query(Option).filter(Option.canonical_sku.in_(safe)).all()
            for o in opts:
                s.delete(o)
            s.commit()
            deleted = len(opts)
        return jsonify({
            'ok': True, 'dry_run': dry_run,
            'safe_count': len(safe), 'safe_skus': safe,
            'unsafe_count': len(unsafe), 'unsafe_skus': unsafe,
            'deleted': deleted,
        })
    except Exception as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()


@bp.route('/api/admin/option-dupes', methods=['GET'])
def api_option_dupes():
    """[2026-06-13] (model_code, color_code, size_code) 정확 중복 옵션 전수 진단 — 읽기 전용.

    스카이블루 처럼 같은 모델·색·사이즈가 2행 이상인 중복(options UNIQUE 제약 부재).
    각 중복군에서 '보존할 1행(keeper)'과 '잉여행'을 정하고, 잉여행 중 URL·재고 매핑이
    0 인 것을 '안전 삭제 후보'로 표시. 삭제는 기존 /api/admin/options/cleanup-dupes
    (dry-run + 매핑0 가드)로 수행. 이 엔드포인트는 SELECT 만 — 데이터 변경 없음.

    keeper 우선순위: ① 활성(is_active) ② 매핑(url+inv) 많은 것 ③ 먼저 생성된 것.
    ?format=json 이면 JSON, 기본은 사람이 읽는 HTML.
    """
    import html as _html
    from sqlalchemy import func
    s = SessionLocal()
    try:
        # 1) 중복 (model,color,size) 키
        dup_keys = (s.query(Option.model_code, Option.color_code, Option.size_code,
                            func.count(Option.canonical_sku))
                    .group_by(Option.model_code, Option.color_code, Option.size_code)
                    .having(func.count(Option.canonical_sku) > 1).all())
        groups = []
        safe_delete_skus = []
        total_rows = 0
        total_redundant = 0
        for model_code, color_code, size_code, _cnt in dup_keys:
            rows = (s.query(Option)
                    .filter(Option.model_code == model_code,
                            Option.color_code == color_code,
                            Option.size_code == size_code).all())
            skus = [o.canonical_sku for o in rows]
            url_cnt = dict(s.query(OptionSourceUrlLink.option_canonical_sku,
                                   func.count(OptionSourceUrlLink.id))
                           .filter(OptionSourceUrlLink.option_canonical_sku.in_(skus))
                           .group_by(OptionSourceUrlLink.option_canonical_sku).all())
            inv_cnt = dict(s.query(OptionInventoryLink.bundle_option_sku,
                                   func.count(OptionInventoryLink.id))
                           .filter(OptionInventoryLink.bundle_option_sku.in_(skus))
                           .group_by(OptionInventoryLink.bundle_option_sku).all())

            def _score(o):
                u = int(url_cnt.get(o.canonical_sku, 0))
                i = int(inv_cnt.get(o.canonical_sku, 0))
                return (1 if o.is_active else 0, u + i,
                        -(o.created_at.timestamp() if o.created_at else 0))
            ordered = sorted(rows, key=_score, reverse=True)
            keeper = ordered[0]
            row_infos = []
            for o in ordered:
                u = int(url_cnt.get(o.canonical_sku, 0))
                i = int(inv_cnt.get(o.canonical_sku, 0))
                is_keeper = (o.canonical_sku == keeper.canonical_sku)
                deletable = (not is_keeper) and u == 0 and i == 0
                if deletable:
                    safe_delete_skus.append(o.canonical_sku)
                if not is_keeper:
                    total_redundant += 1
                row_infos.append({
                    'sku': o.canonical_sku, 'is_active': bool(o.is_active),
                    'url_links': u, 'inv_links': i,
                    'boxhero_stock': o.boxhero_stock_total or 0,
                    'created_at': o.created_at.isoformat() if o.created_at else None,
                    'keeper': is_keeper, 'deletable': deletable,
                })
            total_rows += len(rows)
            groups.append({'model_code': model_code, 'color_code': color_code,
                           'size_code': size_code, 'rows': row_infos})

        if (request.args.get('format') or '').lower() == 'json':
            return jsonify({'ok': True, 'dup_group_count': len(groups),
                            'total_rows': total_rows, 'redundant_rows': total_redundant,
                            'safe_delete_count': len(safe_delete_skus),
                            'safe_delete_skus': safe_delete_skus, 'groups': groups})

        # HTML (비개발자용)
        trs = []
        for g in groups:
            head = (f"{_html.escape(g['model_code'])} · "
                    f"{_html.escape(g['color_code'])} · {_html.escape(g['size_code'])}")
            trs.append(f"<tr class=grp><td colspan=6><b>{head}</b> "
                       f"({len(g['rows'])}행)</td></tr>")
            for r in g['rows']:
                tag = ('<span class=keep>보존</span>' if r['keeper']
                       else ('<span class=del>삭제후보</span>' if r['deletable']
                             else '<span class=warn>잉여(매핑有·수동)</span>'))
                act = '활성' if r['is_active'] else '비활성'
                trs.append(
                    f"<tr><td class=mono>{_html.escape(r['sku'])}</td><td>{tag}</td>"
                    f"<td>{act}</td><td class=num>{r['url_links']}</td>"
                    f"<td class=num>{r['inv_links']}</td>"
                    f"<td class=num>{r['boxhero_stock']}</td></tr>")
        _controls = """
<div style='margin:14px 0;display:flex;gap:8px;align-items:center;flex-wrap:wrap'>
  <button id=mPreview style='padding:8px 14px;border:1px solid #d0d7de;border-radius:6px;background:#fff;cursor:pointer'>① 미리보기(dry-run)</button>
  <button id=mExec style='padding:8px 14px;border:0;border-radius:6px;background:#cf222e;color:#fff;cursor:pointer;display:none'>② 실제 병합·삭제 실행</button>
  <span id=mMsg style='color:#656d76;font-size:13px'></span>
</div>
<pre id=mOut style='background:#f6f8fa;padding:10px;border-radius:6px;font-size:12px;white-space:pre-wrap;display:none'></pre>
<script>
(function(){
  var out=document.getElementById('mOut'), msg=document.getElementById('mMsg');
  function call(dry){return fetch('/api/admin/options/merge-dupes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dry_run:dry})}).then(function(r){return r.json()});}
  document.getElementById('mPreview').onclick=function(){
    msg.textContent='미리보기 중...';
    call(true).then(function(d){
      if(!d.ok){msg.textContent='오류: '+(d.error||'');return;}
      out.style.display='block';
      out.textContent='[미리보기] 삭제될 잉여행 '+d.deleted+'개 · URL이전 '+d.url_moved+'/중복제거 '+d.url_deduped+' · 재고이전 '+d.inv_moved+'/중복제거 '+d.inv_deduped+' · 시장ID복사 '+d.ids_copied+'\\n삭제 SKU: '+((d.deleted_skus||[]).join(', ')||'(없음)');
      msg.textContent='확인했으면 ② 실제 실행을 누르세요.';
      document.getElementById('mExec').style.display=d.deleted>0?'inline-block':'none';
    });
  };
  document.getElementById('mExec').onclick=function(){
    if(!confirm('잉여 중복행을 보존행으로 병합(매핑 이전·시장ID 보존)하고 삭제합니다. 진행할까요?'))return;
    msg.textContent='병합 중...';
    call(false).then(function(d){
      if(!d.ok){msg.textContent='오류: '+(d.error||'');return;}
      out.textContent='[완료] 삭제 '+d.deleted+'개 · URL이전 '+d.url_moved+' · 재고이전 '+d.inv_moved+'. 새로고침합니다.';
      msg.textContent='완료!';
      setTimeout(function(){location.reload();},1300);
    });
  };
})();
</script>
"""
        page = f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>옵션 중복 진단</title><style>
body{{font-family:-apple-system,'Malgun Gothic',sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1f2328}}
h1{{font-size:20px}} .sub{{color:#656d76;font-size:13px;margin-bottom:14px}}
.ban{{padding:12px 16px;border-radius:8px;font-weight:600;margin:12px 0;background:#fff8c5}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
td{{border-top:1px solid #d0d7de;padding:7px 8px}}
tr.grp td{{background:#f6f8fa;border-top:2px solid #afb8c1}}
.mono{{font-family:monospace;font-size:12px}} .num{{text-align:right;font-variant-numeric:tabular-nums}}
.keep{{color:#1a7f37;font-weight:700}} .del{{color:#cf222e;font-weight:700}} .warn{{color:#9a6700}}
code{{background:#f6f8fa;padding:2px 6px;border-radius:4px}}
</style></head><body>
<h1>옵션 중복 진단 (model·color·size)</h1>
<div class=sub>읽기 전용 · 데이터 변경 없음. '보존'=남길 1행, '삭제후보'=잉여+매핑0(안전), '잉여(매핑有)'=수동 확인 필요.</div>
<div class=ban>중복군 {len(groups)}개 · 총 {total_rows}행 · 잉여 {total_redundant}행 · <b>안전 삭제후보 {len(safe_delete_skus)}개</b></div>
{_controls}
<table><tbody>{''.join(trs) or '<tr><td>중복 없음 ✅</td></tr>'}</tbody></table>
</body></html>"""
        return page, 200, {'Content-Type': 'text/html; charset=utf-8'}
    finally:
        s.close()


@bp.route('/api/admin/color-code-normalize', methods=['POST'])
def api_color_code_normalize():
    """color_code = color_display 로 자동 정정. body: {dry_run: bool}

    color_display 비어있지 않으면서 color_code != color_display 인 옵션 대상.
    같은 모음전 내 충돌 (color_code, size_display) UNIQUE 가능성 검증 후 정정.
    """
    body = request.get_json(silent=True) or {}
    dry_run = bool(body.get('dry_run', True))
    s = SessionLocal()
    try:
        dirty = s.query(Option).filter(
            Option.color_display.isnot(None),
            Option.color_display != '',
            Option.color_code != Option.color_display,
        ).all()
        to_normalize = []
        conflict = []
        from sqlalchemy import or_
        for o in dirty:
            # 같은 모델·color_display 와 같은 color_code 로 변경 시 충돌 검사 (size NULL 대응)
            size_filters = []
            if o.size_code:
                size_filters.append(Option.size_code == o.size_code)
            if o.size_display:
                size_filters.append(Option.size_display == o.size_display)
            if not size_filters:
                size_filters.append(Option.size_code.is_(None))
            twin = s.query(Option).filter(
                Option.model_code == o.model_code,
                Option.color_code == o.color_display,
                or_(*size_filters),
                Option.canonical_sku != o.canonical_sku,
            ).first()
            if twin:
                conflict.append({'sku': o.canonical_sku, 'twin': twin.canonical_sku,
                                 'reason': 'duplicate after normalize — delete dirty first'})
            else:
                to_normalize.append({'sku': o.canonical_sku, 'old': o.color_code, 'new': o.color_display})
        updated = 0
        if not dry_run and to_normalize:
            skus = [r['sku'] for r in to_normalize]
            opts = s.query(Option).filter(Option.canonical_sku.in_(skus)).all()
            for o in opts:
                o.color_code = o.color_display
                updated += 1
            s.commit()
        return jsonify({
            'ok': True, 'dry_run': dry_run,
            'normalize_count': len(to_normalize),
            'normalize_preview': to_normalize[:50],
            'conflict_count': len(conflict),
            'conflicts': conflict,
            'updated': updated,
        })
    except Exception as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
