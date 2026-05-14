"""[E] 미맵핑 큐 + 업로드 실패함 (DLQ) 라우트."""
from flask import Blueprint, render_template, request

from shared.db import SessionLocal
from lemouton.sourcing.models import DiscoveryQueueItem
from lemouton.uploader.models import MarketRegistration

bp = Blueprint('queue_dlq', __name__)


# ─── 팀공유 모드: admin 전용 (DLQ 조작 = 데이터 손상 위험). 기존 모드 통과. ───
@bp.before_request
def _admin_only():
    import os
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


VALID_CATS = {'신규 모델', '신규 색상', '옵션 매핑', 'URL 미등록'}


def _classify(item: DiscoveryQueueItem) -> str:
    """디스커버리 항목을 4개 분류로 매핑 (mockup의 카테고리와 매치)."""
    if not item.suggested_model_code:
        return '신규 모델'
    if not item.suggested_color_code:
        return '신규 색상'
    if not item.resolved_canonical_sku:
        return '옵션 매핑'
    return 'URL 미등록'


@bp.route('/queue')
def queue_view():
    """미맵핑 목록 — `?category=신규 모델` 등 단일 분류 필터 지원."""
    requested_cat = request.args.get('category', '').strip()
    if requested_cat and requested_cat not in VALID_CATS:
        requested_cat = ''  # 잘못된 값은 무시

    s = SessionLocal()
    try:
        items = (
            s.query(DiscoveryQueueItem)
            .filter_by(status='pending')
            .order_by(DiscoveryQueueItem.created_at.desc())
            .all()
        )
        rows = []
        cats = {'전체': 0, '신규 모델': 0, '신규 색상': 0, '옵션 매핑': 0, 'URL 미등록': 0}
        for it in items:
            cat = _classify(it)
            cats['전체'] += 1
            cats[cat] = cats.get(cat, 0) + 1
            # 분류 필터 적용 (헤더 카운트는 항상 전체 기준)
            if requested_cat and cat != requested_cat:
                continue
            rows.append({
                'id': it.id,
                'category': cat,
                'model': it.suggested_model_code or '—',
                'where': it.source,
                'what': it.raw_text,
            })
    finally:
        s.close()
    return render_template('queue/index.html', active='queue', rows=rows, cats=cats)


@bp.route('/dlq')
def dlq_view():
    s = SessionLocal()
    try:
        items = (
            s.query(MarketRegistration)
            .filter(MarketRegistration.status == 'failed')
            .order_by(MarketRegistration.last_attempt_at.desc().nullslast())
            .all()
        )
        # 최근 실패 그룹의 가장 흔한 에러 패턴 (간이)
        summary = None
        if items:
            errors = [it.sync_error for it in items if it.sync_error]
            if errors:
                # 가장 빈번한 에러
                most = max(set(errors), key=errors.count)
                summary = {
                    'count': len(items),
                    'message': most,
                }
            else:
                summary = {'count': len(items), 'message': '원인 미상'}
    finally:
        s.close()
    return render_template('dlq/index.html', active='dlq', items=items, summary=summary)
