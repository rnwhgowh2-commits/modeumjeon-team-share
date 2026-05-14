"""[v2] 소싱처 글로벌 운영센터 — `/sources`.

핵심 가치 (사용자 표현):
  "URL 관리하는 글로벌 운영센터처럼 중복된건 하나만 정보 수집하게 만드는거지"

설계 문서: docs/architecture_v2.md
"""
from flask import Blueprint, render_template, jsonify, abort, request

from shared.db import SessionLocal
from lemouton.sources.models import SourceProduct, SourceOption
from lemouton.sources.service import (
    list_source_products_grouped, kpi_summary,
    get_models_sharing_source, get_price_history_for_sku,
)


bp = Blueprint('sources', __name__, url_prefix='/sources')


SITE_LABELS = {
    'lemouton': '르무통 공홈',
    'musinsa': '무신사',
    'ssf': 'SSF',
    'lotteon': '롯데몰',
    'ss_lemouton': '스마트스토어 르무통',
}

STATUS_BADGE = {
    'ok': ('🟢', '정상'),
    'error': ('🔴', '에러'),
    'timeout': ('🟡', '지연'),
    'no_crawler': ('⚪', '크롤러 미지원'),
    None: ('—', '미수집'),
}


@bp.route('/')
def index():
    """소싱처 운영센터 메인 — KPI + 사이트별 URL 그룹."""
    s = SessionLocal()
    try:
        kpi = kpi_summary(s)
        grouped_raw = list_source_products_grouped(s)
        # 사이트 라벨 + 표시용 정렬
        groups = []
        for site_key in list(SITE_LABELS.keys()) + sorted(
            set(grouped_raw.keys()) - set(SITE_LABELS.keys())
        ):
            items = grouped_raw.get(site_key, [])
            if not items:
                continue
            for it in items:
                badge = STATUS_BADGE.get(it.get('last_status'),
                                         STATUS_BADGE[None])
                it['status_emoji'] = badge[0]
                it['status_label'] = badge[1]
            groups.append({
                'site_key': site_key,
                'site_label': SITE_LABELS.get(site_key, site_key),
                'count': len(items),
                'entries': items,
            })
    finally:
        s.close()
    return render_template('sources/index.html', active='sources',
                           kpi=kpi, groups=groups,
                           site_labels=SITE_LABELS)


@bp.route('/<int:source_id>')
def detail(source_id: int):
    """SourceProduct 상세 — 시계열 + 공유 모음전 + 매핑 옵션."""
    s = SessionLocal()
    try:
        sp = s.get(SourceProduct, source_id)
        if sp is None or sp.deleted_at is not None:
            abort(404)
        site_label = SITE_LABELS.get(sp.site, sp.site)
        sharing_models = get_models_sharing_source(s, source_id)

        # 매핑 옵션 목록
        options = (s.query(SourceOption)
                   .filter_by(source_product_id=source_id, deleted_at=None)
                   .order_by(SourceOption.color_text, SourceOption.size_text)
                   .all())
        # 첫 옵션 기준 시계열 (대표값)
        history = []
        if options:
            from lemouton.sources.models import OptionSourceLink
            link = (s.query(OptionSourceLink)
                    .filter_by(source_option_id=options[0].id)
                    .first())
            if link:
                history = get_price_history_for_sku(s, link.canonical_sku, limit=30)

        badge = STATUS_BADGE.get(sp.last_status, STATUS_BADGE[None])
    finally:
        s.close()
    return render_template('sources/detail.html', active='sources',
                           sp=sp, site_label=site_label,
                           sharing_models=sharing_models, options=options,
                           history=history,
                           status_emoji=badge[0], status_label=badge[1])


@bp.post('/<int:source_id>/refetch')
def refetch(source_id: int):
    """수동 fetch — 단일 SourceProduct 의 크롤러 호출."""
    from lemouton.sources.service import fetch_one_source
    from lemouton.sourcing.crawlers import build_crawlers
    crawlers = build_crawlers()
    s = SessionLocal()
    try:
        result = fetch_one_source(s, source_product_id=source_id,
                                  crawlers=crawlers)
        s.commit()
        if result['status'] == 'not_found':
            return jsonify({'ok': False, 'error': 'not found'}), 404
        return jsonify({
            'ok': result['status'] == 'ok',
            'status': result['status'],
            'error': result.get('error'),
        })
    finally:
        s.close()


@bp.post('/<int:source_id>/delete')
def delete(source_id: int):
    """soft-delete — 운영센터에서 안전 삭제."""
    from datetime import datetime, timezone
    s = SessionLocal()
    try:
        sp = s.get(SourceProduct, source_id)
        if sp is None or sp.deleted_at is not None:
            return jsonify({'ok': False, 'error': 'not found'}), 404
        sp.deleted_at = datetime.now(timezone.utc)
        s.commit()
        return jsonify({'ok': True, 'deleted_id': source_id})
    finally:
        s.close()
