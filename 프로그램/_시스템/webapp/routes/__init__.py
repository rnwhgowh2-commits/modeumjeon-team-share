"""[E] Flask blueprint registration.

각 페이지별 라우트는 webapp/routes/<page>.py 에 Blueprint로 정의되며,
register_routes()가 모두 등록한다.
"""
from flask import Flask

# 아이콘 picker 색상 키 → hex (icon_picker.js 의 COLORS 와 동기)
_MODE_COLOR_HEX = {
    'default': '', 'blue': '#3182F6', 'green': '#03C75A', 'orange': '#F59E0B',
    'red': '#EF4444', 'purple': '#7C3AED', 'teal': '#14B8A6', 'pink': '#EC4899',
    'indigo': '#6366F1', 'cyan': '#06B6D4',
}
# 모드 전환 아이콘 기본값 (sidebar.html 하드코딩과 일치)
_MODE_DEFAULTS = {'bundles': '📦', 'inventory': '🏷'}


def _sidebar_mode_icons() -> dict:
    """저장된 모드 전환 아이콘(모음전/재고관리) 조회 — 없으면 기본 이모지 폴백.

    [perf 2026-05-29] 매 페이지 get_icon 2회 쿼리 → 캐시된 list_icons() 1회 참조로 대체.
    """
    from webapp.icon_store import list_icons
    mode_icons = list_icons().get('mode', {})  # TTL 캐시 → 쿼리 0
    result = {}
    for key, default_emoji in _MODE_DEFAULTS.items():
        rec = mode_icons.get(key)
        if rec and rec.get('icon'):
            result[key] = {
                'emoji': rec['icon'],
                'color': _MODE_COLOR_HEX.get(rec.get('color') or 'default', ''),
            }
        else:
            result[key] = {'emoji': default_emoji, 'color': ''}
    return result


# [perf 2026-05-29] 사이드바 뱃지 카운트 — 매 페이지 2 count 쿼리였음.
#   20초 TTL 캐시 (뱃지 숫자는 실시간일 필요 없음). 워커별 캐시.
import time as _time
_counts_cache = {'ts': 0.0, 'unmapped': 0, 'failed': 0, 'sets_alerts': 0}
_COUNTS_TTL = 20.0


def get_cached_badge_counts() -> tuple[int, int]:
    """(unmapped 대기 수, upload 실패 수) — 20초 TTL 캐시.
    사이드바와 홈 KPI 가 동일 값을 공유 (중복 count 제거). 카운트라 캐시 안전.
    """
    now = _time.monotonic()
    if (now - _counts_cache['ts']) >= _COUNTS_TTL:
        from shared.db import SessionLocal
        from lemouton.sourcing.models import DiscoveryQueueItem
        from lemouton.uploader.models import MarketRegistration
        s = SessionLocal()
        try:
            _counts_cache['unmapped'] = s.query(DiscoveryQueueItem).filter_by(status='pending').count()
            _counts_cache['failed'] = s.query(MarketRegistration).filter_by(status='failed').count()
            # [판매처 연동] 전 구성 알림 합(사이드바 글로벌 배지). 싼 쿼리(sets 테이블만, _option_matrix_data 미사용).
            try:
                from lemouton.sets.models import SetChannel
                from lemouton.sets.alert_service import alerts_for_set
                _ids = [r[0] for r in s.query(SetChannel.set_id).distinct().all()]
                _counts_cache['sets_alerts'] = sum(len(alerts_for_set(s, _sid)) for _sid in _ids)
            except Exception:
                _counts_cache['sets_alerts'] = 0
            _counts_cache['ts'] = now
        finally:
            s.close()
    return _counts_cache['unmapped'], _counts_cache['failed']


def register_routes(app: Flask) -> None:
    from webapp.routes.home import bp as home_bp
    from webapp.routes.bundles import bp as bundles_bp
    from webapp.routes.templates_page import bp as templates_bp
    from webapp.routes.track import bp as track_bp
    from webapp.routes.queue_dlq import bp as queue_dlq_bp
    from webapp.routes.settings import bp as settings_bp
    from webapp.routes.accounts import bp as accounts_bp
    from webapp.routes.api import bp as api_bp
    from webapp.routes.api_pricing import bp as api_pricing_bp  # [v3]
    from webapp.routes.api_benefits import bp as api_benefits_bp  # [v8] 동적 혜택
    from webapp.routes.api_benefits_crud import bp as api_benefits_crud_bp  # [v6 D2-A] 혜택 추가 폼 (4 scope)
    from webapp.routes.api_inventory_link import bp as api_inv_link_bp  # [v17] 재고관리 연동
    from webapp.routes.sources import bp as sources_bp  # [v2] 소싱처 운영센터
    # [2026-06-30] 소싱처 사전 블루프린트 제거 — 크롤링 가이드 전체보기로 통합(중복 화면 제거)
    from webapp.routes.trash import bp as trash_bp  # [v2] 휴지통 + 변경 이력
    from webapp.routes.orders import bp as orders_bp  # [v2] 주문관리
    from webapp.routes.market_upload import bp as market_upload_bp  # [v6] Phase 4 — 마켓 업로드 설정 M2
    from webapp.routes.inventory import bp as inventory_bp  # ★ STEP 7 Sprint 0 Task 0.4 — 재고관리 탭 (R1)
    from webapp.routes.api_sidebar import bp as api_sidebar_bp  # [v3] 사이드바 커스터마이징
    from webapp.routes.mapping import bp as mapping_bp  # 맵핑 — 모음전 상품 ↔ 재고관리 SKU
    from webapp.routes.roadmap import bp as roadmap_bp  # 로드맵 · 추가예정 기능
    from webapp.routes.data_guide import bp as data_guide_bp  # 데이터 가이드 · 참고용 전체 데이터 흐름·탭별 지도
    from webapp.routes.sourcing_guide import bp as sourcing_guide_bp  # 소싱처 크롤링 가이드
    from webapp.routes.marketplace_guide import bp as marketplace_guide_bp  # 판매처 추가·데이터지도
    from webapp.routes.sets_api import bp as sets_api_bp  # 구성(세트) 4단계 흐름 API
    from webapp.routes.api_sources_parse import bp as api_sources_parse_bp  # Task 6 — 창 HTML→파서 구조화
    from webapp.routes.admin_dedup import bp as admin_dedup_bp  # Task 4 — 단품 dedup 마이그레이션
    from scheduler.webhook import bp as webhook_bp
    app.register_blueprint(home_bp)
    app.register_blueprint(bundles_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(track_bp)
    app.register_blueprint(queue_dlq_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(api_pricing_bp)  # [v3]
    app.register_blueprint(api_benefits_bp)  # [v8] 동적 혜택
    app.register_blueprint(api_benefits_crud_bp)  # [v6 D2-A] 혜택 추가 폼 (4 scope)
    app.register_blueprint(api_inv_link_bp)  # [v17] 재고관리 연동
    app.register_blueprint(sources_bp)  # [v2]
    app.register_blueprint(trash_bp)  # [v2]
    app.register_blueprint(orders_bp)  # [v2]
    app.register_blueprint(market_upload_bp)  # [v6] Phase 4
    app.register_blueprint(inventory_bp)  # ★ STEP 7 — 재고관리 탭
    app.register_blueprint(api_sidebar_bp)  # [v3] 사이드바 커스터마이징
    app.register_blueprint(mapping_bp)  # 맵핑 — 모음전 상품 ↔ 재고관리 SKU
    app.register_blueprint(roadmap_bp)  # 로드맵 · 추가예정 기능
    app.register_blueprint(data_guide_bp)  # 데이터 가이드 · 참고용
    app.register_blueprint(sourcing_guide_bp)  # 소싱처 크롤링 가이드
    app.register_blueprint(marketplace_guide_bp)  # 판매처 추가·데이터지도
    app.register_blueprint(sets_api_bp)  # 구성(세트) 4단계 흐름 API
    app.register_blueprint(api_sources_parse_bp)  # Task 6 — 창 HTML→파서 구조화
    app.register_blueprint(admin_dedup_bp)  # Task 4 — 단품 dedup 마이그레이션
    app.register_blueprint(webhook_bp)

    @app.context_processor
    def inject_sidebar_counts():
        """사이드바 nav-badge 동적 카운트 + 사용자 레이아웃 주입."""
        from webapp.routes.api_sidebar import get_layout_for_template
        unmapped, failed = get_cached_badge_counts()  # [perf] 20초 TTL 캐시 공유
        return {
            'sidebar_unmapped_count': unmapped,
            'sidebar_failed_count': failed,
            'sidebar_layout': get_layout_for_template(),
            'sidebar_badge_values': {'unmapped': unmapped, 'failed': failed,
                                     'sets_alerts': _counts_cache.get('sets_alerts', 0)},
            'sidebar_mode_icons': _sidebar_mode_icons(),
        }

    @app.context_processor
    def inject_source_labels():
        """[2026-06-30 단일명부] JS 표면(크롤위젯·옵션모달)이 명부 라벨을 쓰도록 주입."""
        try:
            from lemouton.sourcing.source_registry import get_labels
            return {'source_labels': get_labels()}
        except Exception:
            return {'source_labels': {}}
