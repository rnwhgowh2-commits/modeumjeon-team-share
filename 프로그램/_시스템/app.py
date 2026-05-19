"""
르무통 재고 업데이트 — Flask 진입점.
실행: python app.py  (또는 START.bat)
"""
import logging
import os
from pathlib import Path

from flask import Flask, jsonify

from config import Config
from shared.db import init_db


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder='webapp/templates',
        static_folder='webapp/static',
    )
    app.config["SECRET_KEY"] = Config.SECRET_KEY
    # 템플릿 자동 리로드 — debug=False 에서도 코드 변경 즉시 반영
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    # trailing slash 자동 매칭 — /bundles 와 /bundles/ 둘 다 정상 처리
    app.url_map.strict_slashes = False

    import lemouton.sourcing.models  # noqa: F401  # SQLAlchemy 모델 등록
    import lemouton.sourcing.models_pricing  # noqa: F401  # v3 — 소싱처사전+가격설정
    import lemouton.pricing.settings  # noqa: F401
    import lemouton.uploader.models  # noqa: F401
    import lemouton.templates.models  # noqa: F401
    import lemouton.inventory.models  # noqa: F401  # ★ STEP 7 Sprint 1A — 재고관리 13 테이블

    # 팀공유 모드 — fresh DB (Supabase) 에서 create_all 시 모든 FK 타겟 테이블 필요
    # 기존 SQLite 는 이미 모든 테이블 존재 → 영향 없음.
    if os.environ.get("ENVIRONMENT") == "team-share-dev":
        # 추가 모델 (app.py 기본 6개에 누락된 것)
        for _mod in [
            "lemouton.sources.models",        # bundle_*, source_options 등
            "lemouton.sourcing.models_v2",
            "lemouton.multitenancy.models",
            "lemouton.audit.models",          # audit_log
            "lemouton.mapping.models",        # 맵핑 사전 (차원·캐노니컬·별칭)
        ]:
            try:
                __import__(_mod)
            except ImportError as _e:
                pass  # 모델 파일 없음 (정상)
        # User/LoginSession (신규 전용)
        try:
            import webapp.auth.models  # noqa: F401
        except ImportError:
            pass

    # 항상 맵핑 모델 등록 (team-share-dev 외 환경에서도 테이블 사용 가능하도록)
    import lemouton.mapping.models  # noqa: F401

    init_db()

    # Jinja2 — JSON 문자열을 chip 배열로 풀기 위한 filter
    import json as _json
    @app.template_filter('from_json')
    def _from_json(value):
        if not value:
            return []
        try:
            return _json.loads(value)
        except (ValueError, TypeError):
            return []

    # 컬러·사이즈 표시 기본값 — 빈값 → "ONE Color" / "FREE"
    @app.template_filter('color_or_default')
    def _color_or_default(value):
        s = (str(value).strip() if value is not None else '')
        return s if s else 'ONE Color'

    @app.template_filter('size_or_default')
    def _size_or_default(value):
        s = (str(value).strip() if value is not None else '')
        return s if s else 'FREE'

    @app.get("/mockup/<path:filename>")
    def mockup(filename):
        """docs/mockups/ HTML 파일 서빙 — 디자인 시안 미리보기."""
        from flask import send_from_directory
        from pathlib import Path
        mockup_dir = Path(__file__).resolve().parent / "docs" / "mockups"
        return send_from_directory(str(mockup_dir), filename)

    @app.get("/health")
    def health():
        return jsonify(
            status="ok",
            app="lemouton-stock-update",
            port=Config.PORT,
            db=Config.DB_PATH.name,
        )

    from webapp.routes import register_routes
    register_routes(app)

    # ─────────────────────────────────────────────────────────────────
    # 팀공유 모드 — 인증 시스템 활성화 (env-gated, 백워드 호환)
    # ENVIRONMENT=team-share-dev 일 때만 Flask-Login 통합.
    # 기존 (env 미설정) 에서는 import 도 안 됨 → 기존 동작 100% 동일.
    # ─────────────────────────────────────────────────────────────────
    if os.environ.get("ENVIRONMENT") == "team-share-dev":
        try:
            from webapp.auth import init_auth
            init_auth(app)
        except ImportError as _e:
            app.logger.warning(f"[team-share] auth 모듈 import 실패 (Day 2 미완): {_e}")
        # 모바일 PWA Blueprint (바코드 스캔 + 입출고/조정)
        try:
            from webapp.routes.mobile import bp as _mobile_bp
            app.register_blueprint(_mobile_bp)
            app.logger.info("[team-share] 모바일 PWA blueprint 등록됨")
        except ImportError:
            pass  # mobile 모듈 없음 (기존 환경)

    # PARITY_720 D-2 — /api/v1/* alias (기존 /inventory/api/* 를 표준 경로로 노출)
    from flask import Blueprint as _Blueprint
    api_v1 = _Blueprint('api_v1', __name__, url_prefix='/api/v1')

    @api_v1.get('/inventory/notifications/unread-count')
    def _v1_unread():
        from webapp.routes.inventory import notifications as _n
        return _n.notification_unread_count_api()

    @api_v1.get('/inventory/notifications/recent')
    def _v1_recent():
        from webapp.routes.inventory import notifications as _n
        return _n.notification_recent_api()

    @api_v1.get('/inventory/autocomplete/partner')
    def _v1_ac_partner():
        from webapp.routes.inventory import notifications as _n
        return _n.autocomplete_partner()

    @api_v1.get('/inventory/autocomplete/sku')
    def _v1_ac_sku():
        from webapp.routes.inventory import notifications as _n
        return _n.autocomplete_sku()

    @api_v1.get('/health')
    def _v1_health():
        return jsonify(status='ok', api_version='v1')

    app.register_blueprint(api_v1)

    # 옛 링크 호환 — /markets/<market> → /accounts/upload?market=<market>
    from flask import redirect as _redirect
    @app.get('/markets/<market>')
    def _legacy_market_redirect(market):
        return _redirect(f'/accounts/upload?market={market}', code=302)

    # ─────────────────────────────────────────────────────────────────
    # PARITY_720 Tier 1 — P-26 Security + N-12 Error + D-16 Idempotency
    # + W-8 Kill switch + D-26 Deprecation + P-10/D-17 Rate limit
    # ─────────────────────────────────────────────────────────────────
    _SECURITY_HEADERS = {
        'X-Frame-Options': 'DENY',
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
        'X-XSS-Protection': '1; mode=block',
    }

    # W-8 Kill switch — config 또는 환경변수로 긴급 비활성화
    _KILL_SWITCHES = {
        'inventory_writes': os.environ.get('KILL_INVENTORY_WRITES') == '1',
        'webhook_outbound': os.environ.get('KILL_WEBHOOK') == '1',
    }
    app.config['KILL_SWITCHES'] = _KILL_SWITCHES

    # D-26 Deprecation — 라우트 별 Sunset 일자 (yyyy-mm-dd) 매핑 (현재 비어있음)
    _DEPRECATIONS = {
        # '/inventory/legacy-endpoint': '2026-12-31',
    }

    @app.after_request
    def _apply_security_headers(resp):
        for k, v in _SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        # D-26 Deprecation/Sunset 헤더
        sunset = _DEPRECATIONS.get(_req.path)
        if sunset:
            resp.headers['Deprecation'] = 'true'
            resp.headers['Sunset'] = sunset
        return resp

    # D-16 Idempotency-Key — 24h in-memory 캐시
    from collections import deque
    from threading import Lock
    from flask import request as _req
    _idem_cache: dict[str, tuple[float, str]] = {}
    _idem_lock = Lock()
    _IDEM_TTL_SEC = 24 * 3600

    @app.before_request
    def _idempotency_check():
        key = _req.headers.get('Idempotency-Key', '').strip()
        if not key or _req.method != 'POST':
            return
        now = datetime.now(timezone.utc).timestamp()
        with _idem_lock:
            # 만료 항목 정리
            expired = [k for k, (t, _) in _idem_cache.items() if (now - t) > _IDEM_TTL_SEC]
            for k in expired:
                _idem_cache.pop(k, None)
            if key in _idem_cache:
                from flask import jsonify as _jsonify
                resp = _jsonify(error='idempotent_replay',
                                message='동일 Idempotency-Key 로 24h 내 처리됨',
                                original_path=_idem_cache[key][1])
                resp.status_code = 409
                return resp
            _idem_cache[key] = (now, _req.path)

    # P-10 / D-17 Rate limit
    _rl_buckets: dict[str, deque] = {}
    _rl_lock = Lock()
    _RL_WINDOW_SEC = 10
    _RL_MAX = 30

    @app.before_request
    def _rate_limit_post():
        if _req.method != 'POST':
            return
        if not _req.path.startswith('/inventory/'):
            return
        # W-8 Kill switch 우선
        if _KILL_SWITCHES.get('inventory_writes'):
            from flask import jsonify as _jsonify
            resp = _jsonify(error='kill_switch_active',
                            message='재고 쓰기 작업이 일시 중지되었습니다 (KILL_INVENTORY_WRITES)')
            resp.status_code = 503
            return resp
        ip = _req.headers.get('X-Forwarded-For', _req.remote_addr or '?').split(',')[0].strip()
        now = datetime.now(timezone.utc).timestamp()
        with _rl_lock:
            dq = _rl_buckets.setdefault(ip, deque())
            while dq and (now - dq[0]) > _RL_WINDOW_SEC:
                dq.popleft()
            if len(dq) >= _RL_MAX:
                from flask import jsonify as _jsonify
                resp = _jsonify(error='rate_limit_exceeded',
                                message=f'요청이 너무 많습니다 ({_RL_MAX}/{_RL_WINDOW_SEC}s)')
                resp.status_code = 429
                return resp
            dq.append(now)

    @app.errorhandler(500)
    def _err_500(e):
        import logging as _logging
        _logging.getLogger(__name__).exception("Internal server error")
        if _req.path.startswith('/api/') or _req.path.endswith('.json'):
            return jsonify(error='internal_error', message=str(e)), 500
        return render_template_or_text("500 내부 오류 — 로그를 확인하세요"), 500

    @app.errorhandler(404)
    def _err_404(e):
        if _req.path.startswith('/api/'):
            return jsonify(error='not_found', path=_req.path), 404
        return render_template_or_text(f"404 — {_req.path} 없음"), 404

    return app


def render_template_or_text(text):
    """템플릿 없으면 plain text — error 핸들러가 base 템플릿 충돌하지 않도록."""
    return f"<!DOCTYPE html><html><body style='font-family:sans-serif;padding:40px'><h2>{text}</h2><a href='/'>← 홈으로</a></body></html>"


# datetime import 보강 (rate limit 에서 사용)
from datetime import datetime, timezone  # noqa: E402, F811


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(Config.LOG_DIR / "app.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


if __name__ == "__main__":
    _setup_logging()
    app = create_app()
    # 스케줄러는 운영 모드에서만 시작 (테스트 모드는 명시적으로 호출)
    if not Config.DEBUG:
        try:
            from scheduler.main import start_scheduler
            start_scheduler()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("scheduler 시작 실패 — Flask는 계속 진행")
    print(f"\n[르무통 재고 업데이트] Starting on http://{Config.HOST}:{Config.PORT}\n")
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
