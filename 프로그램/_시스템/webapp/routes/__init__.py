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
    """저장된 모드 전환 아이콘(모음전/재고관리) 조회 — 없으면 기본 이모지 폴백."""
    from webapp.icon_store import get_icon
    result = {}
    for key, default_emoji in _MODE_DEFAULTS.items():
        rec = get_icon('mode', key)
        if rec and rec.get('icon'):
            result[key] = {
                'emoji': rec['icon'],
                'color': _MODE_COLOR_HEX.get(rec.get('color') or 'default', ''),
            }
        else:
            result[key] = {'emoji': default_emoji, 'color': ''}
    return result


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
    from webapp.routes.source_registry import bp as source_registry_bp  # [v3] 사전
    from webapp.routes.trash import bp as trash_bp  # [v2] 휴지통 + 변경 이력
    from webapp.routes.orders import bp as orders_bp  # [v2] 주문관리
    from webapp.routes.market_upload import bp as market_upload_bp  # [v6] Phase 4 — 마켓 업로드 설정 M2
    from webapp.routes.inventory import bp as inventory_bp  # ★ STEP 7 Sprint 0 Task 0.4 — 재고관리 탭 (R1)
    from webapp.routes.api_sidebar import bp as api_sidebar_bp  # [v3] 사이드바 커스터마이징
    from webapp.routes.mapping import bp as mapping_bp  # 맵핑 — 모음전 상품 ↔ 재고관리 SKU
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
    app.register_blueprint(source_registry_bp)  # [v3]
    app.register_blueprint(trash_bp)  # [v2]
    app.register_blueprint(orders_bp)  # [v2]
    app.register_blueprint(market_upload_bp)  # [v6] Phase 4
    app.register_blueprint(inventory_bp)  # ★ STEP 7 — 재고관리 탭
    app.register_blueprint(api_sidebar_bp)  # [v3] 사이드바 커스터마이징
    app.register_blueprint(mapping_bp)  # 맵핑 — 모음전 상품 ↔ 재고관리 SKU
    app.register_blueprint(webhook_bp)

    @app.context_processor
    def inject_sidebar_counts():
        """사이드바 nav-badge 동적 카운트 + 사용자 레이아웃 주입."""
        from shared.db import SessionLocal
        from lemouton.sourcing.models import DiscoveryQueueItem
        from lemouton.uploader.models import MarketRegistration
        from webapp.routes.api_sidebar import get_layout_for_template
        s = SessionLocal()
        try:
            unmapped = s.query(DiscoveryQueueItem).filter_by(status='pending').count()
            failed = s.query(MarketRegistration).filter_by(status='failed').count()
        finally:
            s.close()
        return {
            'sidebar_unmapped_count': unmapped,
            'sidebar_failed_count': failed,
            'sidebar_layout': get_layout_for_template(),
            'sidebar_badge_values': {'unmapped': unmapped, 'failed': failed},
            'sidebar_mode_icons': _sidebar_mode_icons(),
        }
