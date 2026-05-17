"""[E] 모음전 list + edit (단일 스크롤 + 우측 sticky nav).

T5는 GET 렌더만 — 저장/복제/삭제/등록 같은 변경 액션은 T10 AJAX에서 wiring.
"""
from datetime import datetime, timezone, timedelta
from flask import Blueprint, abort, jsonify, redirect, render_template, request

from shared.db import SessionLocal
from lemouton.sourcing.models import Model, Option, DiscoveryQueueItem, BundleSourceUrl
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
                           error=None, form={})


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
                                   form=request.form)
        if not brand:
            return render_template('bundles/new.html', active='bundles',
                                   error='브랜드를 입력하세요.',
                                   form=request.form)
        s = SessionLocal()
        try:
            if s.query(Model).filter_by(model_code=code).first():
                return render_template('bundles/new.html', active='bundles',
                                       error=f"'{code}' 코드는 이미 존재해요.",
                                       form=request.form)
            m = Model(model_code=code, model_name_raw=name,
                      model_name_display=name, brand=brand, category=category)
            s.add(m)
            s.commit()
        finally:
            s.close()
        return redirect(f'/bundles/{code}')
    return render_template('bundles/new.html', active='bundles_new', error=None, form={})


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


def _bundle_summary(s, m: Model) -> dict:
    """list 카드용 요약 — v3: 소싱처 N개 / URL Y개 분포 칩.

    URL 카운트 = 모음전의 모든 옵션 × 소싱처 매핑 행 합계.
    소싱처 카운트 = 그 모음전 옵션들이 사용 중인 distinct 소싱처 수.
    소싱처별 URL 수 = (소싱처 이름, 그 소싱처에 등록된 URL 갯수) 리스트.
    """
    from sqlalchemy import func
    from lemouton.sourcing.models_pricing import OptionSourceUrl, SourceRegistry

    opts = s.query(Option).filter_by(model_code=m.model_code).all()
    opt_count = len(opts)
    opts_with_naver = sum(1 for o in opts if o.naver_option_id)
    opts_with_coupang = sum(1 for o in opts if o.coupang_option_id)

    # v3: 소싱처별 URL 카운트
    sku_list = [o.canonical_sku for o in opts]
    src_dist = []
    src_total = 0
    url_total = 0
    if sku_list:
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
    from lemouton.uploader.models import MarketRegistration
    dlq_failed = (
        s.query(MarketRegistration)
        .filter(
            MarketRegistration.canonical_sku.like(f'{m.model_code}%'),
            MarketRegistration.status == 'failed',
        )
        .count()
    )

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
        query = s.query(Model)
        # ★ 박스히어로식 다중 키워드 AND 교집합
        query = apply_and_filter(
            query, search_tokens,
            Model.model_code, Model.model_name_raw, Model.model_name_display, Model.brand,
            op='ilike',
        )
        if selected_brand:
            query = query.filter(Model.brand == selected_brand)
        models = query.order_by(Model.updated_at.desc().nullslast()).all()
        bundles_all = [_bundle_summary(s, m) for m in models]

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
        # 탭 필터 적용
        if selected_status == 'draft':
            bundles = groups['new_wip'] + groups['migrate_wip']
            groups = {'new_wip': groups['new_wip'],
                      'migrate_wip': groups['migrate_wip'], 'active': []}
        else:  # active
            bundles = groups['active']
            groups = {'new_wip': [], 'migrate_wip': [],
                      'active': groups['active']}
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

        # 소싱처 레지스트리 (builtin 5 + DB SourcingSource — v6 P5.5)
        # 명시적 try/rollback 으로 트랜잭션 격리 (PG InFailedSqlTransaction 방지)
        all_sources = list(SOURCE_REGISTRY)
        try:
            from lemouton.sourcing.models import SourcingSource
            for c in (s.query(SourcingSource)
                       .filter(SourcingSource.is_active.is_(True))
                       .order_by(SourcingSource.sort_order, SourcingSource.id).all()):
                all_sources.append({
                    'key': c.source_key, 'label': c.label,
                    'brand': 'custom-' + c.source_key,
                    'glyph': c.logo_letter or (c.label[:1].upper() if c.label else 'X'),
                    'crawler': c.has_adapter, 'legacy': False,
                    'logo_color': c.logo_color or '#3182F6',
                    'favicon_url': c.favicon_url, 'domain': c.domain,
                    'needs_login': c.needs_login, 'builtin': False,
                })
        except Exception:
            s.rollback()  # PG 트랜잭션 복구
        share_counts = {}
        source_urls = {}
        try:
            from lemouton.sources.service import get_share_count_by_url
        except Exception:
            get_share_count_by_url = None
        for src in all_sources:
            sk = src['key']
            # legacy 단일 URL — builtin 만 Model 컬럼 보유 (custom 은 컬럼 없음)
            legacy_url = (getattr(m, f'url_{sk}', None) or '') if src.get('legacy') else ''
            # share_count
            if get_share_count_by_url:
                try:
                    share_counts[sk] = get_share_count_by_url(s, sk, legacy_url)
                except Exception:
                    share_counts[sk] = 0
            else:
                share_counts[sk] = 0
            # 다중 URL (BundleSourceUrl) — builtin·custom 공통
            rows = (s.query(BundleSourceUrl)
                    .filter_by(model_code=code, source_key=sk)
                    .order_by(BundleSourceUrl.sort_order, BundleSourceUrl.id)
                    .all())
            if rows:
                source_urls[sk] = [{'id': r.id, 'url': r.url} for r in rows]
            elif legacy_url:
                source_urls[sk] = [{'id': None, 'url': legacy_url}]
            else:
                source_urls[sk] = []
    finally:
        s.close()
    # 실행 이력 (최근 20건) — 크롤(소싱처별) + 업로드(마켓별) 결과 포함
    try:
        from lemouton.sourcing.run_history import list_for_bundle
        run_history = list_for_bundle(code, limit=20)
    except Exception:
        run_history = []

    status_cards = {
        'last_crawled_ago': _humanize_ago(m.last_crawled_at),
        'last_crawled_at': _fmt_dt(m.last_crawled_at),
        'last_uploaded_ago': _humanize_ago(m.last_uploaded_at),
        'last_uploaded_at': _fmt_dt(m.last_uploaded_at),
    }

    return render_template(
        'bundles/edit.html',
        active='bundles',
        bundle=m,
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
    응답: {ok: True, urls: {source_key: [{id, url, sort_order}, ...], ...}}
    legacy 단일 컬럼 (Model.url_<sk>) 도 다중 행이 없으면 자동 표현 (id=null).
    """
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if not m:
            return jsonify({'ok': False, 'error': 'bundle not found'}), 404
        urls = {}
        all_keys = set(get_all_keys(session=s))  # builtin + DB
        for sk in all_keys:
            rows = (s.query(BundleSourceUrl)
                    .filter_by(model_code=code, source_key=sk)
                    .order_by(BundleSourceUrl.sort_order, BundleSourceUrl.id)
                    .all())
            if rows:
                urls[sk] = [{'id': r.id, 'url': r.url, 'sort_order': r.sort_order} for r in rows]
            else:
                legacy = getattr(m, f'url_{sk}', None) if sk in VALID_SOURCE_KEYS else None
                urls[sk] = [{'id': None, 'url': legacy, 'sort_order': 0}] if legacy else []
        return jsonify({'ok': True, 'urls': urls, 'sources': sorted(all_keys)})
    finally:
        s.close()


@bp.route('/api/bundles/<code>/source-urls', methods=['POST'])
def api_add_source_url(code):
    body = request.get_json(silent=True) or {}
    source_key = (body.get('source_key') or '').strip()
    url = (body.get('url') or '').strip()
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
        row = BundleSourceUrl(model_code=code, source_key=source_key, url=url, sort_order=next_order)
        s.add(row)
        s.flush()
        _sync_legacy_url_column(s, code, source_key)
        s.commit()
        return jsonify({'ok': True, 'id': row.id, 'url': row.url, 'sort_order': row.sort_order})
    finally:
        s.close()


@bp.route('/api/bundles/<code>/source-urls/<int:url_id>', methods=['PUT'])
def api_update_source_url(code, url_id):
    body = request.get_json(silent=True) or {}
    new_url = (body.get('url') or '').strip()
    if not new_url:
        return jsonify({'ok': False, 'error': 'url required'}), 400
    s = SessionLocal()
    try:
        row = s.query(BundleSourceUrl).filter_by(id=url_id, model_code=code).first()
        if not row:
            return jsonify({'ok': False, 'error': 'not found'}), 404
        row.url = new_url
        _sync_legacy_url_column(s, code, row.source_key)
        s.commit()
        return jsonify({'ok': True, 'id': row.id, 'url': row.url})
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
