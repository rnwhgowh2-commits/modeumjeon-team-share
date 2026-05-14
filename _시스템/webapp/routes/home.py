"""[E] 홈 화면 — KPI 4개 + 다음 자동 실행 + 가격 차트 + 빠른 진입."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template

from shared.db import SessionLocal
from lemouton.sourcing.models import Model, DiscoveryQueueItem
from lemouton.uploader.models import MarketRegistration
from lemouton.templates.models import PriceTrackHistory

bp = Blueprint('home', __name__)


def _get_kpis():
    """홈 KPI 카드용 카운트.
    v6 Phase 3 (2026-05-07): auto_on_count 추가. Model.auto_enabled 필드 도입 전까지는
    bundles 전체를 ON 으로 가정 (placeholder)."""
    s = SessionLocal()
    try:
        bundles = s.query(Model).count()
        unmapped = s.query(DiscoveryQueueItem).filter_by(status='pending').count()
        upload_failed = s.query(MarketRegistration).filter_by(status='failed').count()

        # 최근 24시간 내 가격이 변한 옵션 수 (PriceTrackHistory 기반)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_changes = (
            s.query(PriceTrackHistory.canonical_sku)
            .filter(PriceTrackHistory.captured_at >= cutoff)
            .distinct()
            .count()
        )

        # 자동화 ON / OFF 실 카운트 (v6 Phase 3.5 — 2026-05-07)
        auto_on = s.query(Model).filter_by(auto_enabled=True).count()
        auto_off = bundles - auto_on

        return {
            'bundles': bundles,
            'unmapped': unmapped,
            'price_changes': recent_changes,
            'upload_failed': upload_failed,
            'auto_on': auto_on,
            'auto_off': auto_off,
        }
    finally:
        s.close()


def _get_bundle_toggle_rows(limit: int = 5):
    """자동화 토글 리스트 — 홈에 노출할 상위 N건. 최근 갱신 순.
    v6 Phase 3 (2026-05-07): auto_enabled placeholder=True 로 일괄 전달.
    Model.auto_enabled 필드 도입 후 실 값으로 교체."""
    s = SessionLocal()
    try:
        rows = (
            s.query(Model)
            .order_by(Model.updated_at.desc().nullslast())
            .limit(limit)
            .all()
        )
        return [
            {
                'code': r.model_code,
                'name': getattr(r, 'product_name', None) or r.model_code,
                'updated_at': r.updated_at.strftime('%m-%d %H:%M') if r.updated_at else '—',
                'auto_enabled': bool(r.auto_enabled),
            }
            for r in rows
        ]
    finally:
        s.close()


def _get_recent_bundles(limit: int = 8):
    """최근 편집된 모음전 코드 리스트."""
    s = SessionLocal()
    try:
        rows = (
            s.query(Model.model_code)
            .order_by(Model.updated_at.desc().nullslast())
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows]
    finally:
        s.close()


def _get_next_run_info():
    """다음 자동 실행 정보 — 스케줄러는 T11에서 등록되므로 현재는 placeholder."""
    return {
        'countdown': '02:48:13',
        'next_at': '2026-04-25 18:00 예정',
    }


@bp.route('/')
def index():
    return render_template(
        'home.html',
        active='home',
        kpis=_get_kpis(),
        recent_bundles=_get_recent_bundles(),
        next_run=_get_next_run_info(),
        bundle_toggle_rows=_get_bundle_toggle_rows(limit=5),
    )
