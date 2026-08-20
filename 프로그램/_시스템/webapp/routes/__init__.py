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
# 모드 전환 아이콘 기본값 (partials/_modeswitch.html 하드코딩과 일치)
_MODE_DEFAULTS = {'bundles': '📦', 'inventory': '🏷', 'bulk': '🚀'}


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
# [perf 2026-08-06] 구성 알림 합(sets_alerts)이 세트마다 3~5쿼리(alerts_for_set N+1)라,
#   20초마다 걸리는 **운 나쁜 요청 하나**가 세트수×쿼리를 뒤집어썼다(실측: 세트 60개
#   = 180쿼리가 /bundles 콜드 로드에 얹힘). 판정 로직(alerts_for_set)은 단일 원천
#   그대로 두고, 계산만 요청 경로 밖(백그라운드 스레드·single-flight)으로 옮긴다.
#   값은 마지막으로 계산한 것을 보여준다(stale-while-revalidate — 배지라 안전).
import threading as _threading
import time as _time
_counts_cache = {'ts': 0.0, 'unmapped': 0, 'failed': 0, 'sets_alerts': 0}
_COUNTS_TTL = 20.0
_alerts_cache = {'ts': 0.0, 'count': 0, 'ever': False}
_ALERTS_TTL = 300.0
_alerts_refreshing = _threading.Lock()


def _rebuild_sets_alerts() -> None:
    """전 구성 알림 합 재계산 — 판정은 alerts_for_set **호출만**(재구현 금지)."""
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        from lemouton.sets.models import SetChannel
        from lemouton.sets.alert_service import alerts_for_set
        _ids = [r[0] for r in s.query(SetChannel.set_id).distinct().all()]
        _alerts_cache['count'] = sum(len(alerts_for_set(s, _sid)) for _sid in _ids)
    except Exception:
        _alerts_cache['count'] = 0
    finally:
        s.close()
    _alerts_cache['ts'] = _time.monotonic()
    _alerts_cache['ever'] = True


def _sets_alerts_swr() -> int:
    """마지막으로 계산한 알림 합 — 낡았으면 백그라운드에서 한 번만 다시 센다."""
    now = _time.monotonic()
    if (_alerts_cache['ever'] and (now - _alerts_cache['ts']) < _ALERTS_TTL):
        return _alerts_cache['count']
    if _alerts_refreshing.acquire(blocking=False):
        def _run():
            try:
                _rebuild_sets_alerts()
            finally:
                _alerts_refreshing.release()
        try:
            _threading.Thread(target=_run, name='sidebar-alerts-swr',
                              daemon=True).start()
        except Exception:      # noqa: BLE001 — 스레드를 못 만들면 자물쇠를 돌려준다
            _alerts_refreshing.release()   # (안 돌려주면 배지가 영원히 안 갱신)
    # 아직 한 번도 못 셌으면 0 — 화면은 배지를 아예 안 그린다(0 을 「알림 없음」으로
    # 단정하지 않는다. 첫 계산이 끝나면 다음 페이지부터 진짜 수가 보인다).
    return _alerts_cache['count']


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
            _counts_cache['ts'] = now
        finally:
            s.close()
    # 구성 알림 합 — 요청 경로 밖에서 갱신(N+1 을 페이지 렌더에 얹지 않는다)
    _counts_cache['sets_alerts'] = _sets_alerts_swr()
    return _counts_cache['unmapped'], _counts_cache['failed']


def register_routes(app: Flask) -> None:
    from webapp.routes.home import bp as home_bp
    from webapp.routes.bundles import bp as bundles_bp
    from webapp.routes.templates_page import bp as templates_bp
    from webapp.routes.track import bp as track_bp
    from webapp.routes.settings import bp as settings_bp
    from webapp.routes.accounts import bp as accounts_bp
    from webapp.routes.api import bp as api_bp
    from webapp.routes.api_pricing import bp as api_pricing_bp  # [v3]
    from webapp.routes.api_benefits import bp as api_benefits_bp  # [v8] 동적 혜택
    from webapp.routes.api_benefits_crud import bp as api_benefits_crud_bp  # [v6 D2-A] 혜택 추가 폼 (4 scope)
    from webapp.routes.api_inventory_link import bp as api_inv_link_bp  # [v17] 재고관리 연동
    # [2026-06-30] 소싱처 사전 블루프린트 제거 — 크롤링 가이드 전체보기로 통합(중복 화면 제거)
    # [2026-07-30] 삭제 — 미맵핑 큐(/queue)·업로드 실패함(/dlq)·소싱처 운영센터(/sources)·맵핑(/mapping).
    #   넷 다 사이드바에서 이미 걸러져 라이브에 안 보였고(한 달+ 무사고), 다른 화면이 참조하지 않았다.
    #   미맵핑·업로드실패의 내용은 「자동화」의 수집·전송 이력 보고서로 옮겨졌다.
    #   별칭 사전 모듈(lemouton/mapping)은 matcher.normalize 를 쓰는 곳이 있어 그대로 둔다.
    from webapp.routes.trash import bp as trash_bp  # [v2] 휴지통 + 변경 이력
    from webapp.routes.orders import bp as orders_bp  # [v2] 주문관리
    from webapp.routes.market_upload import bp as market_upload_bp  # [v6] Phase 4 — 마켓 업로드 설정 M2
    from webapp.routes.inventory import bp as inventory_bp  # ★ STEP 7 Sprint 0 Task 0.4 — 재고관리 탭 (R1)
    from webapp.routes.bulk import bp as bulk_bp  # [2026-07-17] 대량등록 3번째 모드
    from webapp.routes.catalog import bp as catalog_bp  # [2026-07-24] 상품관리 — 마켓 상품 캐시·현황
    from webapp.routes.optgen import bp as optgen_bp  # [2026-08-01] 옵션생성 & 상품생성 허브
    from webapp.routes.optgen_sku import bp as optgen_sku_bp  # 미구성 SKU 편입 + SKU 번호(품번·바코드·GTIN) + SKU 연결상태
    from webapp.routes.market_send import bp as market_send_bp  # [2026-08-02] 상품수집&전송
    from webapp.routes.api_sidebar import bp as api_sidebar_bp  # [v3] 사이드바 커스터마이징
    from webapp.routes.roadmap import bp as roadmap_bp  # 로드맵 · 추가예정 기능
    from webapp.routes.data_guide import bp as data_guide_bp  # 데이터 가이드 · 참고용 전체 데이터 흐름·탭별 지도
    from webapp.routes.sourcing_guide import bp as sourcing_guide_bp  # 소싱처 크롤링 가이드
    from webapp.routes.marketplace_guide import bp as marketplace_guide_bp  # 판매처 추가·데이터지도
    from webapp.routes.sets_api import bp as sets_api_bp  # 구성(세트) 4단계 흐름 API
    from webapp.routes.api_sources_parse import bp as api_sources_parse_bp  # Task 6 — 창 HTML→파서 구조화
    from webapp.routes.admin_dedup import bp as admin_dedup_bp
    from webapp.routes.admin_display_no import bp as admin_display_no_bp  # 표시번호 소급 부여
    from webapp.routes.admin_owner_snapshot import bp as admin_owner_snapshot_bp  # [2026-08-01] 옵션 주인 이관 기준 지문(읽기 전용)
    from webapp.routes.admin_fee_audit import bp as admin_fee_audit_bp  # [2026-08-02] 수수료율 13% 재기·고치기
    from webapp.routes.matrix import bp as matrix_bp  # 매트릭스 옵션 — 원본(U)·파생(P)
    from webapp.routes.policy import bp as policy_bp  # 마켓별 정책 — 생성·적용  # Task 4 — 단품 dedup 마이그레이션
    from webapp.routes.api_margin import bp as api_margin_bp  # 마진 계산기 — 업로드·분석·내보내기
    from webapp.routes.api_keywords import bp as api_keywords_bp  # 카드별 분류 키워드 (팀 공유) — /api/keywords
    from webapp.routes.api_brand_dict import bp as api_brand_dict_bp  # 브랜드 사전·미확정 정리 — /api/brand_dict(/suggest)
    from webapp.routes.api_product_counts import bp as api_product_counts_bp  # 계층 분석 등록수 — /api/product-counts
    from webapp.routes.api_sourcing_settings import bp as api_sourcing_settings_bp  # 소싱처 계정 관리 — /api/sourcing-sites·/api/settings
    from webapp.routes.api_blackspot import bp as api_blackspot_bp  # 소싱처 주문번호 추출 — /api/blackspot/fetch_order_no
    from webapp.routes.live_send_test import bp as live_send_test_bp  # 실전송 테스트 — 한 구성만 안전 전송
    from webapp.routes.notion_report import bp as notion_report_bp  # 노션 투두 일일 보고 — 점검·카카오 연결
    from webapp.routes.order_ingest import bp as order_ingest_bp  # 주문 적재 — 현황·백필
    from webapp.routes.period_probe import bp as period_probe_bp  # 조회기간 상한 실측 — 읽기 전용 프로브
    from webapp.routes.upload_rate_probe import bp as upload_rate_probe_bp  # 업로드 속도한도 실측 — 쓰기 프로브(env 게이트)
    from scheduler.webhook import bp as webhook_bp
    app.register_blueprint(home_bp)
    app.register_blueprint(bundles_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(track_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(api_pricing_bp)  # [v3]
    app.register_blueprint(api_benefits_bp)  # [v8] 동적 혜택
    app.register_blueprint(api_benefits_crud_bp)  # [v6 D2-A] 혜택 추가 폼 (4 scope)
    app.register_blueprint(api_inv_link_bp)  # [v17] 재고관리 연동
    app.register_blueprint(trash_bp)  # [v2]
    app.register_blueprint(orders_bp)  # [v2]
    app.register_blueprint(market_upload_bp)  # [v6] Phase 4
    app.register_blueprint(inventory_bp)  # ★ STEP 7 — 재고관리 탭
    app.register_blueprint(bulk_bp)  # [2026-07-17] 대량등록
    app.register_blueprint(catalog_bp)  # [2026-07-24] 상품관리 — 마켓 상품 캐시·현황
    app.register_blueprint(optgen_bp)  # [2026-08-01] 옵션생성 & 상품생성 허브
    app.register_blueprint(optgen_sku_bp)  # 미구성 SKU 편입 + SKU 번호(품번·바코드·GTIN) + SKU 연결상태
    app.register_blueprint(market_send_bp)  # [2026-08-02] 상품수집&전송 (마켓 전송 · 자동화)
    app.register_blueprint(api_sidebar_bp)  # [v3] 사이드바 커스터마이징
    app.register_blueprint(roadmap_bp)  # 로드맵 · 추가예정 기능
    app.register_blueprint(data_guide_bp)  # 데이터 가이드 · 참고용
    app.register_blueprint(sourcing_guide_bp)  # 소싱처 크롤링 가이드
    app.register_blueprint(marketplace_guide_bp)  # 판매처 추가·데이터지도
    app.register_blueprint(sets_api_bp)  # 구성(세트) 4단계 흐름 API
    app.register_blueprint(api_sources_parse_bp)  # Task 6 — 창 HTML→파서 구조화
    app.register_blueprint(admin_dedup_bp)
    app.register_blueprint(admin_display_no_bp)
    app.register_blueprint(admin_owner_snapshot_bp)  # [2026-08-01] 옵션 주인 이관 기준 지문
    app.register_blueprint(admin_fee_audit_bp)  # [2026-08-02] 수수료율 13% 재기·고치기
    app.register_blueprint(matrix_bp)
    app.register_blueprint(policy_bp)  # Task 4 — 단품 dedup 마이그레이션
    app.register_blueprint(api_margin_bp)  # 마진 계산기 — 업로드·분석·내보내기
    app.register_blueprint(api_keywords_bp)  # 카드별 분류 키워드 (팀 공유) — /api/keywords
    app.register_blueprint(api_brand_dict_bp)  # 브랜드 사전·미확정 정리 — /api/brand_dict(/suggest)
    app.register_blueprint(api_product_counts_bp)  # 계층 분석 등록수 — /api/product-counts
    app.register_blueprint(api_sourcing_settings_bp)  # 소싱처 계정 관리 — /api/sourcing-sites·/api/settings
    app.register_blueprint(api_blackspot_bp)  # 소싱처 주문번호 추출 — /api/blackspot/fetch_order_no
    app.register_blueprint(live_send_test_bp)  # 실전송 테스트 — 한 구성만 안전 전송
    app.register_blueprint(notion_report_bp)  # 노션 투두 일일 보고 — 점검·카카오 연결
    app.register_blueprint(order_ingest_bp)  # 주문 적재 — 현황·백필
    app.register_blueprint(period_probe_bp)  # 조회기간 상한 실측 — 읽기 전용 프로브
    app.register_blueprint(upload_rate_probe_bp)  # 업로드 속도한도 실측 — 쓰기 프로브(env 게이트)
    app.register_blueprint(webhook_bp)

    @app.context_processor
    def inject_sidebar_counts():
        """사이드바 nav-badge 동적 카운트 + 사용자 레이아웃 주입."""
        from webapp.routes.api_sidebar import get_layout_for_template
        unmapped, failed = get_cached_badge_counts()  # [perf] 20초 TTL 캐시 공유
        layout = get_layout_for_template()
        # [배치 재설계] 상단 탭은 같은 layout 을 옮겨 담기만 한다 — 메뉴를 두 번 적지 않는다.
        # 여기서 터지면 사이드바까지 같이 죽으므로, 실패해도 화면은 뜨게 두고 로그만 남긴다.
        try:
            from webapp.nav_top import build as _build_topnav
            topnav = _build_topnav(layout)
        except Exception:
            from flask import current_app
            current_app.logger.exception('[topnav] 상단 탭 구성 실패 — 사이드바로 폴백')
            topnav = None
        return {
            'sidebar_unmapped_count': unmapped,
            'sidebar_failed_count': failed,
            'sidebar_layout': layout,
            'topnav': topnav,
            'sidebar_badge_values': {'unmapped': unmapped, 'failed': failed,
                                     'sets_alerts': _counts_cache.get('sets_alerts', 0)},
            'sidebar_mode_icons': _sidebar_mode_icons(),
        }

    @app.context_processor
    def inject_active_app_default():
        """모드 활성 판정 기본값 — 블루프린트 스코프 processor(inventory·bulk)가 덮어쓴다.

        [2026-07-17] 예전엔 sidebar.html 이 active_app != 'inventory' 라는 부정조건으로
        모음전을 켰다 → 3번째 모드(bulk) 추가 시 모음전이 같이 켜짐. 모음전 라우트는
        active_app 을 안 넘기므로 전역 기본값이 필수.
        """
        return {'active_app': 'bundles'}

    @app.context_processor
    def inject_design_mode():
        """화면 디자인 표시 주입 — 서버가 그릴 때 넣어야 화면이 깜빡이지 않는다.

        [2026-08-02 사장님 확정] 고르는 기능을 없앴다 — 늘 화이트 타입이다.
        예전에는 사람마다 저장된 값을 읽어 왔는데, 이제 읽지 않는다(그만큼 빨라진다).
        """
        from webapp.design_mode import body_class, MODES, DEFAULT_MODE
        return {
            'design_mode': DEFAULT_MODE,
            'design_body_class': body_class(),
            'design_modes': MODES,
        }

    @app.context_processor
    def inject_source_labels():
        """[2026-06-30 단일명부] JS 표면(크롤위젯·옵션모달)이 명부 라벨을 쓰도록 주입."""
        try:
            from lemouton.sourcing.source_registry import get_labels
            return {'source_labels': get_labels()}
        except Exception:
            return {'source_labels': {}}
