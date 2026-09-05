"""
르무통 재고 업데이트 — Flask 진입점.
실행: python app.py  (또는 START.bat)
"""
import logging
import os
from pathlib import Path

# 실행 위치와 무관하게 동작하도록 cwd 를 이 파일 위치(_시스템/)로 고정
os.chdir(Path(__file__).resolve().parent)

from flask import Flask, jsonify

from config import Config
from shared.db import init_db


def _resolve_samba_wave_url() -> str | None:
    """SAMBA_WAVE_URL 환경변수를 읽어 공백 제거 후 반환, 없거나 공백뿐이면 None.

    모듈 최상단 함수로 빼서 create_app()(실DB 연결 필요) 없이 단독 테스트 가능하게 함
    — _inject_samba_wave_url 컨텍스트 프로세서가 이 함수만 부른다.
    """
    return (os.environ.get('SAMBA_WAVE_URL') or '').strip() or None


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder='webapp/templates',
        static_folder='webapp/static',
    )
    app.config["SECRET_KEY"] = Config.SECRET_KEY
    # [모바일 1단계] 폰에서 앱을 열 때마다 비밀번호를 다시 묻지 않게.
    #   flask_login 기본값은 365일 — 90일로 줄인다(PC 에도 같이 적용됨).
    from datetime import timedelta as _td
    app.config["REMEMBER_COOKIE_DURATION"] = _td(days=90)
    app.config["REMEMBER_COOKIE_HTTPONLY"] = True
    app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
    # REMEMBER_COOKIE_SECURE 는 일부러 안 켠다 — 라이브(mou-m.com)는 Cloudflare/Caddy
    #   뒤 HTTPS 지만 로컬 개발은 http://localhost 라, Secure 를 켜면 로컬에서
    #   remember 쿠키가 브라우저에 아예 저장되지 않아 자동로그인이 조용히 죽는다.
    #   세션 쿠키(SESSION_COOKIE_SECURE)도 같은 이유로 안 켜져 있어 일관적이다.
    # 템플릿 자동 리로드 — debug=False 에서도 코드 변경 즉시 반영
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    # trailing slash 자동 매칭 — /bundles 와 /bundles/ 둘 다 정상 처리
    app.url_map.strict_slashes = False
    # 정적 자원 캐싱 — /static/* 응답에 Cache-Control: max-age=2592000 (30일).
    # [2026-06-05 PERF] 아래 _static_auto_version 이 모든 정적 URL 에 파일별 ?v=<mtime>
    #   을 자동 주입하므로, 파일이 바뀌면 URL 이 바뀌어 즉시 새 버전을 받는다(freshness 보장).
    #   따라서 안전하게 장기 캐시 가능 → 같은 작업 세션 내 페이지 이동 시 재검증 왕복 0.
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 2592000

    # [2026-06-03] 정적 캐시버스트 — toss.css 변경 시 ?v=<수정시각> 로 즉시 반영.
    #   배경: 위 캐시 때문에 CSS 수정해도 브라우저가 옛 파일을 써서 안 바뀌던 문제.
    #   toss.css mtime 을 버전으로 주입 → 파일 바뀔 때만 URL 변경 → 캐시 자동 무효화.
    @app.context_processor
    def _inject_static_ver():
        try:
            _p = os.path.join(os.path.dirname(__file__), 'webapp', 'static', 'toss.css')
            return {'STATIC_VER': str(int(os.path.getmtime(_p)))}
        except Exception:
            return {'STATIC_VER': '1'}

    # [2026-06-05 PERF] 모든 정적 URL 에 파일별 수정시각(mtime)을 ?v= 로 자동 주입.
    #   기존엔 toss.css(STATIC_VER) 만 버스트했고, 나머지 JS/CSS 는 후처리에서
    #   'no-cache, must-revalidate' 로 강제돼 매 페이지 로드마다 서버 재검증(왕복)이 발생 → 느렸음.
    #   이 훅으로 모든 정적파일이 "바뀌면 URL 변경(=즉시 갱신), 안 바뀌면 동일 URL(=캐시 재사용,
    #   재검증 왕복 0)" 가 되어 freshness 와 속도를 동시에 확보. (url_for('static',...) 전부 적용)
    @app.url_defaults
    def _static_auto_version(endpoint, values):
        if endpoint == 'static' and values.get('filename') and 'v' not in values:
            try:
                _fp = os.path.join(app.static_folder, values['filename'])
                values['v'] = int(os.path.getmtime(_fp))
            except Exception:
                pass

    import lemouton.sourcing.models  # noqa: F401  # SQLAlchemy 모델 등록
    import lemouton.sourcing.models_pricing  # noqa: F401  # v3 — 소싱처사전+가격설정
    # [2026-08-02] 축 매핑 저장소(source_axis_aliases) — 「우리 축 값 ↔ 소싱처 표기」.
    #   ★ create_all 은 **import 된 모델만** 만든다. 여기 빠지면 표가 조용히 안 생기고
    #     화면은 원인 없는 오류만 낸다.
    import lemouton.sourcing.axis_alias  # noqa: F401
    # [2026-08-02] 소싱처별 「확인 도장」(axis_confirmations)
    import lemouton.sourcing.axis_confirm  # noqa: F401
    # [2026-07-23 · 2차 T8] 실구매 피드백(경유 쿠폰 실적용 요율) — create_all 등록용
    import lemouton.sourcing.purchase_feedback  # noqa: F401
    # ★ pricing.settings 의 AccountUploadPolicy 가 upload_accounts(models_v2) 를 FK 로 참조한다.
    #   models_v2 가 등록되기 전에 init_db() 가 돌면 NoReferencedTableError 로 앱이 아예 안 뜬다.
    #   (2026-07-20 라이브 502 장애 — team-share-dev 조건부 import 뒤에만 있어서 라이브에선 누락)
    import lemouton.sourcing.models_v2  # noqa: F401  # upload_accounts — 아래 FK 타겟
    import lemouton.pricing.settings  # noqa: F401
    import lemouton.uploader.models  # noqa: F401
    import lemouton.templates.models  # noqa: F401
    import lemouton.pricing.fee_defaults  # noqa: F401  # 마켓별 수수료 기준(화면에서 고침)
    import lemouton.inventory.models  # noqa: F401  # ★ STEP 7 Sprint 1A — 재고관리 13 테이블
    import lemouton.sets.models  # noqa: F401  # 구성(세트) 레이어 V1 경량
    import lemouton.margin.models  # noqa: F401  # 마진계산기 — margin_analyses
    import lemouton.send.models  # noqa: F401  # [2026-08-02] 마켓 전송 작업·건별 결과
    import lemouton.delivery.models  # noqa: F401  # 배송검사 (MangoOrder, MangoStatusMap)
    import lemouton.claims.models  # noqa: F401  # CS 클레임 처리상태 (ClaimHandling)
    import lemouton.cs_inquiries.models  # noqa: F401  # CS 고객문의 처리상태
    import lemouton.registration.models  # noqa: F401  # 대량등록 — ProductDraft, ProductDraftMarket
    # [2026-07-24 상품관리] 마켓 상품 캐시 3테이블 — market_products / _counts / _groups.
    #   ★ create_all 은 **import 된 모델만** 만든다. 여기 빠지면 테이블이 조용히 안 생기고
    #     화면은 "불러오지 못했습니다"만 띄운다(에러 원인이 안 드러남).
    import lemouton.catalog.models  # noqa: F401
    import lemouton.registration.process_policy  # noqa: F401  # 대량등록 ② 가공정책 4테이블
    import lemouton.policy.models  # noqa: F401  # [2026-08-24] 정책·0층 규칙·2층 계정설정
    # [2026-08-25 Phase 7-1] 정규 카테고리 3표 — 표를 만들려면 여기서 불러야 한다
    #   (`shared/db.py:init_db` 의 create_all 은 **등록된 모델만** 만든다).
    import lemouton.policy.normalized_category  # noqa: F401
    import lemouton.registration.notice_defaults  # noqa: F401  # 고시정보 기본값 (notice_defaults)
    # ★ 소싱 정규화 모델(source_products·crawl_deltas·crawl_lap_runs·crawl_change_stats).
    #   여태 team-share-dev 에서만 import 됐는데, create_all 은 **import 된 모델만** 만든다
    #   → 다른 환경에선 크롤 변동 통계 테이블이 조용히 안 생긴다(에러도 안 남).
    #   import 는 멱등하고 create_all 은 없는 테이블만 만들어 기존 DB엔 영향이 없다.
    import lemouton.sources.models  # noqa: F401
    import lemouton.sources.grade_config_store  # noqa: F401  # 등급 설정 1행(crawl_grade_config)

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
    # v34.11 — brand 색 DB 영속화 (Fly.io 멀티 인스턴스 + deploy reset 문제 해결)
    import webapp.icon_store_model  # noqa: F401
    # 우리 서버 IP 명부 (팀 공유) — 신규 테이블, create_all 자동 생성
    import webapp.server_ip_model  # noqa: F401
    # 주문·클레임 적재 (1년치 조회의 전제) — 신규 테이블, create_all 자동 생성
    import lemouton.markets.models_orders  # noqa: F401
    # 롯데온 셀러오피스 통합주문조회 크롤 적재 (OpenAPI 미제공분의 유일한 원천)
    import lemouton.markets.models_lotteon_so  # noqa: F401
    # 마켓 정산 대조 실행 이력 — 마켓 화면 엑셀 ↔ 우리 정산예정금액(2026-08-12)
    import lemouton.margin.models_settle_recon  # noqa: F401
    # 실매입가(사람이 적는 값) — 적재분과 물리적으로 분리된 표(2026-08-06). 재수집에 안 지워진다.
    import lemouton.markets.models_purchase  # noqa: F401
    # 실매입가 **변경 이력**(누가 언제 얼마→얼마) — 덧붙이기 전용(2026-08-12).
    import lemouton.markets.models_purchase_history  # noqa: F401
    import lemouton.markets.models_supply  # noqa: F401
    # 「주문 관리」 상태(사장님이 만든 항목 + 줄마다 지정) — 재수집에 안 지워지는 별도 표.
    import lemouton.markets.models_order_status  # noqa: F401

    init_db()

    # v34.11 — 기존 icon_overrides.json (머신 휘발) 을 DB 로 1회성 마이그레이션
    try:
        from webapp.icon_store import migrate_from_json
        migrate_from_json()
    except Exception:
        import logging as _logging
        _logging.getLogger(__name__).exception("icon_store migration skipped")

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

    # 제품명 단일 SKU brand-strip — 단일 옵션 detail 페이지용 (LCP 불가시 brand 중복만 제거)
    # 사용: {{ opt | display_pname_single }}  또는  {{ opt | display_pname_single('FREE') }}
    from shared.product_display import format_pname_single, format_color_single

    @app.template_filter('display_pname_single')
    def _display_pname_single(opt, fallback=''):
        try:
            brand = (opt.model.brand if getattr(opt, 'model', None) else '') or ''
            name = ''
            if getattr(opt, 'model', None):
                name = (opt.model.model_name_display or opt.model.model_name_raw or '')
            return format_pname_single(brand, name, fallback=fallback or getattr(opt, 'canonical_sku', ''))
        except Exception:
            return fallback or ''

    @app.template_filter('cleaned_color_single')
    def _cleaned_color_single(opt):
        try:
            raw = (opt.color_display or opt.color_code or '') if opt else ''
            pname = ''
            if getattr(opt, 'model', None):
                pname = (opt.model.model_name_display or opt.model.model_name_raw or '')
            return format_color_single(raw, pname=pname)
        except Exception:
            return 'ONE Color'

    @app.get("/mockup/<path:filename>")
    def mockup(filename):
        """docs/mockups/ HTML 파일 서빙 — 디자인 시안 미리보기."""
        from flask import send_from_directory
        from pathlib import Path
        mockup_dir = Path(__file__).resolve().parent / "docs" / "mockups"
        return send_from_directory(str(mockup_dir), filename)

    @app.get("/health")
    def health():
        out = dict(
            status="ok",
            app="lemouton-stock-update",
            port=Config.PORT,
            db=Config.DB_PATH.name,
        )
        # [2026-07-19] 서버 직접 크롤 게이트 상태 — 서버 app.env 는 저장소 밖이라
        #   밖에서 확인할 방법이 없었다. 크롤=로컬 원칙(CLAUDE.md)이 실제로 지켜지는지
        #   브라우저로 바로 볼 수 있게 노출(값이 아니라 on/off 여부만).
        try:
            from lemouton.sourcing.server_crawl_gate import server_crawl_enabled
            out["server_crawl"] = "on" if server_crawl_enabled() else "off"
        except Exception:   # noqa: BLE001
            out["server_crawl"] = "unknown"
        # [perf 2026-06-12] ?db=1 → 라이브 DB 왕복 지연 진단(공개·timing+엔진종류만, 데이터 X).
        #   라이브가 SQLite(로컬파일·빠름)인지 원격 Postgres(왕복 지연)인지 즉시 판별용.
        from flask import request as _rq
        if _rq.args.get('db'):
            import time as _t
            from sqlalchemy import text as _sqltext
            from shared.db import SessionLocal as _SL
            _s = _SL()
            try:
                _times = []
                for _ in range(5):
                    _a = _t.perf_counter()
                    _s.execute(_sqltext("SELECT 1")).scalar()
                    _times.append((_t.perf_counter() - _a) * 1000)
                _a = _t.perf_counter()
                _s.execute(_sqltext("SELECT count(*) FROM options")).scalar()
                _cnt_ms = (_t.perf_counter() - _a) * 1000
                out['db_engine'] = 'sqlite' if Config.DB_URL.startswith('sqlite') else 'postgres'
                out['db_select1_avg_ms'] = round(sum(_times) / len(_times), 2)
                out['db_select1_min_ms'] = round(min(_times), 2)
                out['db_count_options_ms'] = round(_cnt_ms, 2)
            except Exception as _e:
                out['db_error'] = str(_e)[:120]
            finally:
                _s.close()
        return jsonify(**out)

    from webapp.routes import register_routes
    register_routes(app)

    # ─────────────────────────────────────────────────────────────────
    # 응답 시간 계측 + gzip 압축 — 페이로드 50%+ 축소 (텍스트 응답 한정)
    # DevTools Network 탭에서 X-Server-Time-Ms 헤더로 응답시간 확인.
    # 500ms 이상은 콘솔에도 WARN. /static/* 측정 제외.
    # ─────────────────────────────────────────────────────────────────
    import time as _time
    import gzip as _gzip
    from io import BytesIO as _BytesIO
    from flask import g as _g, request as _req

    _GZIP_TYPES = (
        'text/html', 'text/css', 'text/plain', 'text/xml',
        'application/json', 'application/javascript', 'text/javascript', 'application/xml',
        'image/svg+xml',
    )

    # [2026-08-06 PERF] 정적파일 gzip 결과 캐시 — 키 = "경로|ETag", 값 = 압축 바이트.
    #   ETag 는 Flask 가 (mtime, 크기) 로 만들므로 파일이 바뀌면 키가 바뀐다 = 자동 무효화.
    #   상한 256개 (정적파일 총수보다 넉넉) — 넘으면 그냥 캐시 안 함(메모리 폭주 방지).
    _GZ_CACHE: dict[str, bytes] = {}
    _GZ_CACHE_MAX = 256

    # [2026-06-12 perf-B] 요청별 DB 시간 분리 — 라이브 로그/헤더에서 'DB vs Python' 가시화.
    #   목적: 느린 요청이 원격DB 왕복 때문인지(쿼리 ms 큼) Python 처리 때문인지(쿼리 ms 작음)를
    #         라이브 로그만 보고 확정 → 어디를 최적화할지 추측 없이 결정.
    #   비용: 쿼리당 perf_counter 2회 + g 접근 — 무시 가능. 실패해도 절대 응답 영향 X.
    try:
        from shared.db import engine as _perf_engine
        from sqlalchemy import event as _perf_event
        from flask import has_request_context as _has_ctx

        @_perf_event.listens_for(_perf_engine, "before_cursor_execute")
        def _db_q_t0(conn, cursor, statement, params, context, executemany):
            context._perf_q_t0 = _time.perf_counter()

        @_perf_event.listens_for(_perf_engine, "after_cursor_execute")
        def _db_q_t1(conn, cursor, statement, params, context, executemany):
            try:
                if _has_ctx():
                    dt = (_time.perf_counter() - getattr(context, '_perf_q_t0', _time.perf_counter())) * 1000.0
                    _g._db_ms = getattr(_g, '_db_ms', 0.0) + dt
                    _g._db_n = getattr(_g, '_db_n', 0) + 1
            except Exception:
                pass
    except Exception:
        pass

    @app.before_request
    def _perf_t0():
        if _req.path.startswith('/static/'):
            return
        _g._perf_t0 = _time.perf_counter()
        _g._db_ms = 0.0
        _g._db_n = 0

    # ── [2026-08-12] 앞단(Cloudflare/Caddy)이 502·504 본문을 자기 오류 페이지로 갈아치운다 ──
    #   증상: 앱이 `jsonify({"ok":False,"error":...}), 502` 를 내도 브라우저에는 6.4KB 짜리
    #        Cloudflare "Bad gateway" HTML 이 도착 → 화면 JS 의 `res.json()` 이 터져
    #        사용자는 사유 대신 「네트워크 오류: Unexpected token '<'」 만 본다.
    #   실측(2026-08-12 라이브): /accounts/api/upload/accounts/13/write-test 에 없는 상품번호를
    #        넣어 앱이 일부러 502 JSON 을 내게 했더니 응답이 HTML 로 바뀌고 앱 헤더
    #        (X-Server-Time-Ms 등)까지 통째로 사라졌다 = 앞단이 갈아치운 것이 확정.
    #   대응: JSON 응답에 한해 502·504 를 424(Failed Dependency)로 바꾼다. 4xx 는 앞단이
    #        그대로 통과시키므로 본문(사유·hint·body_snippet)이 화면까지 살아서 간다.
    #        의미도 맞다 — "우리 서버는 살아 있고 바깥 마켓 호출이 실패했다".
    #        화면 JS 는 전부 `data.ok` 로 판정하므로 상태코드 변경의 부작용이 없다.
    _CDN_SWALLOWED = (502, 504)

    @app.after_request
    def _unswallow_gateway_json(resp):
        if resp.status_code in _CDN_SWALLOWED and resp.mimetype == 'application/json':
            resp.headers['X-Upstream-Status'] = str(resp.status_code)  # 원래 뜻 보존
            resp.status_code = 424
        return resp

    @app.after_request
    def _perf_log(resp):
        t0 = getattr(_g, '_perf_t0', None)
        if t0 is not None:
            ms = (_time.perf_counter() - t0) * 1000.0
            db_ms = getattr(_g, '_db_ms', 0.0)
            db_n = getattr(_g, '_db_n', 0)
            py_ms = ms - db_ms
            resp.headers['X-Server-Time-Ms'] = f"{ms:.1f}"
            resp.headers['X-Server-DB-Ms'] = f"{db_ms:.1f}"      # DB 왕복 합계
            resp.headers['X-Server-DB-Q'] = str(db_n)            # 쿼리 수
            if ms >= 500:
                app.logger.warning(
                    f"[perf-slow] {ms:6.0f}ms (DB {db_ms:5.0f}ms/{db_n}q, Py {py_ms:5.0f}ms) "
                    f"{_req.method} {_req.full_path}")

        # [2026-06-05 PERF] gzip 압축 — 텍스트성 응답(동적 HTML/JSON + 정적 JS/CSS/SVG) 모두.
        #   기존엔 정적파일(send_file = direct_passthrough)이 압축에서 제외돼 toss.css(188KB)·
        #   toss.js(141KB) 등이 무압축 전송됐음. 실측: 정적 JS/CSS 합계 694KB → 172KB (75%↓).
        #   no-cache 강제는 제거(위 _static_auto_version 의 ?v=mtime 으로 freshness 보장하므로 불필요).
        try:
            _ctype = (resp.content_type or '').split(';')[0].strip()
            if (
                resp.status_code == 200
                and _ctype in _GZIP_TYPES
                and 'Content-Encoding' not in resp.headers
                and 'gzip' in (_req.headers.get('Accept-Encoding') or '').lower()
            ):
                # [2026-08-06 PERF] 정적파일은 압축 결과를 메모리에 재사용.
                #   기존: 요청마다 toss.css(241KB) 를 compresslevel=5 로 재압축 → 1코어 서버에서
                #   CSS/JS 25개 × 매 요청 = 순수 CPU 낭비. ETag(=파일 mtime·크기) 가 같으면
                #   내용도 같으므로 캐시 적중. 파일이 바뀌면 ETag 가 바뀌어 자동 무효화.
                #   캐시가 있으니 압축률을 9 로 올려 전송량도 함께 줄인다(압축은 파일당 1회뿐).
                _is_static = _req.path.startswith('/static/')
                _ck = None
                if _is_static:
                    _ck = f"{_req.path}|{resp.headers.get('ETag') or ''}"
                    _hit = _GZ_CACHE.get(_ck)
                    if _hit is not None:
                        resp.direct_passthrough = False
                        resp.set_data(_hit)
                        resp.headers['Content-Encoding'] = 'gzip'
                        resp.headers['Content-Length'] = str(len(_hit))
                        resp.headers['Vary'] = 'Accept-Encoding'
                        return resp

                if resp.direct_passthrough:
                    resp.direct_passthrough = False  # 정적파일 본문 읽기 허용
                _data = resp.get_data()
                if len(_data) >= 256:
                    buf = _BytesIO()
                    with _gzip.GzipFile(fileobj=buf, mode='wb',
                                        compresslevel=9 if _is_static else 5) as gz:
                        gz.write(_data)
                    gz_data = buf.getvalue()
                    if len(gz_data) < len(_data):
                        resp.set_data(gz_data)
                        resp.headers['Content-Encoding'] = 'gzip'
                        resp.headers['Content-Length'] = str(len(gz_data))
                        vary = resp.headers.get('Vary')
                        if not vary or 'accept-encoding' not in vary.lower():
                            resp.headers['Vary'] = (vary + ', Accept-Encoding') if vary else 'Accept-Encoding'
                        if _ck and len(_GZ_CACHE) < _GZ_CACHE_MAX:
                            _GZ_CACHE[_ck] = gz_data
        except Exception:
            pass  # 압축 실패 시 원본 그대로 — 절대 사용자 영향 X
        return resp

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
            # 폰 크롤 리모컨 (상태·자동 on/off·지금 한 바퀴) — 크롤은 로컬 PC 확장이 한다
            from webapp.routes.mobile_crawl import bp as _mobile_crawl_bp
            app.register_blueprint(_mobile_crawl_bp)
            # 폰 앱 껍데기 ('전체' 메뉴·설치 안내·폰 전용 화면 단일 원천)
            from webapp.routes.mobile_shell import bp as _mobile_shell_bp
            app.register_blueprint(_mobile_shell_bp)
            # 폰 전용 주문 화면 (배치5 — 1-C·2-A·3-C. 데이터는 /orders 와 같은 원천)
            from webapp.routes.mobile_orders import bp as _mobile_orders_bp
            app.register_blueprint(_mobile_orders_bp)
            # 폰 전용 매트릭스 화면 (D-1 — 검색→옵션 카드. 데이터는 PC /matrix 와 같은 함수)
            from webapp.routes.mobile_matrix import bp as _mobile_matrix_bp
            app.register_blueprint(_mobile_matrix_bp)
            # 폰 전용 정산 요약 화면 (E-1 — 기간 KPI+마켓 막대. 정산액은 sell_source
            # _settlement_for 단일 원천, 저장분만 읽어 마켓 호출 0)
            from webapp.routes.mobile_settle import bp as _mobile_settle_bp
            app.register_blueprint(_mobile_settle_bp)
            # 폰 크롤 가이드 읽기 화면 (F-2 — 목차→절 읽기. 내용은 정본 md 를 렌더
            # 시점에 읽는다 — 사본 0. 게이트는 PC /sourcing-guide 와 동일 admin)
            from webapp.routes.mobile_guide import bp as _mobile_guide_bp
            app.register_blueprint(_mobile_guide_bp)
            app.logger.info("[team-share] 모바일 PWA blueprint 등록됨")
        except ImportError as _e:
            # 흔적 없이 삼키면 import 하나만 깨져도 폰 라우트가 통째로 사라진다
            # (이 프로젝트가 싸우는 '조용한 실패'). 등록 동작은 그대로, 로그만 남긴다.
            app.logger.warning(f"[team-share] 모바일 blueprint import 실패: {_e}")

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

    # v34.8 — brand 색 override 를 모든 페이지에 SSR 인라인 주입.
    # 클라이언트 부트스트랩 fetch 가 실패해도 (JWT 일시 에러 등) 색상이 즉시 적용됨.
    @app.context_processor
    def _inject_brand_color_overrides():
        try:
            from webapp.icon_store import list_icons
            return {'brand_color_overrides': list_icons().get('brand', {})}
        except Exception:
            return {'brand_color_overrides': {}}

    # 대량등록 모드 → samba-wave 로 전환하는 스위치. 값 없으면(기본) 기존 /bulk/ 그대로 —
    # samba-wave 실배포 전까지 라이브 동작 무변화.
    @app.context_processor
    def _inject_samba_wave_url():
        return {'samba_wave_url': _resolve_samba_wave_url()}

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

    # ─────────────────────────────────────────────────────────────────
    # [2026-08-06 PERF] 정적파일 캐시 해방 — 프로그램 전체 체감속도의 최대 병목이었다.
    #
    # 실측한 증상(라이브):
    #   · 화면 조작 가능(domInteractive) 2,931ms  ↔  서버 응답(TTFB) 은 400ms 뿐
    #   · CSS/JS 한 개가 최대 250초 대기, 탭 이동 시 36개 중 3개만 캐시 재사용
    #
    # 원인: 응답에 `Vary: Cookie` 가 붙어 있었다(Flask 세션을 건드리면 자동으로 붙는다).
    #   ① Cloudflare 는 Cookie 로 갈리는 응답을 캐시하지 않는다 → cf-cache-status: BYPASS
    #      → CSS/JS 25개가 전부 원본 서버(Lightsail)까지 온다.
    #   ② 원본은 워커 2개뿐이라, 주문조회처럼 무거운 요청이 돌면 정적파일이 그 뒤에 줄 선다.
    #      (재현: preview.json 4개 동시 실행 중 toss.css 가 2분 내 미응답)
    #   ③ 브라우저도 Vary 가 안 맞으면 캐시를 못 써서 매번 304 재검증 왕복을 한다.
    #
    # 고침: 정적파일 응답에서 Cookie 흔적을 지우고, 버전(?v=mtime) 이 붙은 URL 은 불변으로 표시.
    #   → Cloudflare 가 엣지에 캐시(HIT) → 원본까지 안 옴 → 무거운 요청과 경쟁하지 않는다.
    #   → 브라우저는 재검증조차 안 한다 → 탭 이동 시 정적파일 네트워크 요청 0.
    #
    # 왜 안전한가: 모든 정적 URL 에 위 `_static_auto_version` 이 파일 수정시각을 ?v= 로 넣는다.
    #   파일이 바뀌면 URL 이 바뀌므로 낡은 캐시를 볼 수 없다. ?v= 가 없는 URL(서비스워커가
    #   부르는 /static/sw.js·manifest.json 등)은 불변 처리에서 제외하고 짧게(1시간)만 캐시한다.
    #
    # WSGI 계층에 두는 이유: `Vary: Cookie` 는 Flask 가 after_request 들이 다 끝난 뒤
    #   세션 저장 단계에서 붙인다. after_request 에서 지우면 그 뒤에 다시 붙어서 안 지워진다.
    # ─────────────────────────────────────────────────────────────────
    _NO_IMMUTABLE = ('/static/sw.js', '/static/manifest.json')

    class _StaticCacheHeaders:
        """/static/* 응답을 CDN·브라우저가 캐시할 수 있는 모양으로 바로잡는다."""

        def __init__(self, wsgi_app):
            self._wsgi_app = wsgi_app

        def __call__(self, environ, start_response):
            path = environ.get('PATH_INFO', '') or ''
            if not path.startswith('/static/'):
                return self._wsgi_app(environ, start_response)

            # ?v=<수정시각> 이 붙은 URL 만 "영구 불변" — 내용이 바뀌면 URL 이 바뀌므로 안전.
            #   🔴 이름이 정확히 'v' 인 것만 인정한다. 그냥 문자열로 'v=' 를 찾으면
            #      ?nov=1 · ?rev=2 같은 주소가 1년 고정돼 영영 안 바뀐다(되돌리기 불가).
            qs = environ.get('QUERY_STRING', '') or ''
            has_v = any(p.split('=', 1)[0] == 'v' for p in qs.split('&') if p)
            versioned = has_v and (path not in _NO_IMMUTABLE)
            cache_value = (
                'public, max-age=31536000, immutable' if versioned
                else 'public, max-age=3600'
            )

            def _start(status, headers, exc_info=None):
                out = []
                for key, value in headers:
                    k = key.lower()
                    if k == 'set-cookie':
                        continue        # 쿠키가 붙으면 CDN 이 캐시를 포기한다
                    if k == 'vary':
                        value = 'Accept-Encoding'   # Cookie 축 제거
                    elif k == 'cache-control':
                        value = cache_value
                    out.append((key, value))
                have = {k.lower() for k, _ in out}
                if 'vary' not in have:
                    out.append(('Vary', 'Accept-Encoding'))
                if 'cache-control' not in have:
                    out.append(('Cache-Control', cache_value))
                return start_response(status, out, exc_info)

            return self._wsgi_app(environ, _start)

    app.wsgi_app = _StaticCacheHeaders(app.wsgi_app)

    # 자동전환 스케줄러(1분 틱) — gunicorn(--preload) 마스터에서 1회 기동. 서버크롤 스케줄러와
    # 독립(발주확인=마켓 API). MOUM_NO_AUTOCONFIRM_SCHED=1 이면 끔(테스트·로컬 선택).
    if os.environ.get("MOUM_NO_AUTOCONFIRM_SCHED") != "1":
        try:
            from scheduler.main import start_auto_confirm_scheduler
            start_auto_confirm_scheduler()
        except Exception:   # noqa: BLE001 — 스케줄러 실패가 앱 기동을 막지 않게
            import logging
            logging.getLogger(__name__).exception("auto-confirm 스케줄러 시작 실패")

    # 주문 수집(증분) + 백필 처리 — 같은 마스터 스레드에서. MOUM_ORDER_INGEST_HOURS=0 이면 끔.
    #  ★ start_scheduler() 는 `__main__`(개발 실행)에서만 불리므로 거기 등록하면
    #    프로덕션(gunicorn)에서 아예 돌지 않는다. 여기가 실제로 도는 자리다.
    #  ★ 긴 백필이 여기(요청을 처리하지 않는 마스터)서 돌아야 한다 — 워커에서 돌리면
    #    워커가 점유돼 502 가 되고, 워커 재활용 때 작업이 통째로 죽는다.
    try:
        from scheduler.main import start_order_ingest_scheduler
        start_order_ingest_scheduler()
    except Exception:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("주문 수집 스케줄러 시작 실패")

    # 상품관리 — 마켓 상품 머리글 야간 훑기. MOUM_CATALOG_SYNC_HOUR 없으면 안 켜진다.
    #  ★ start_scheduler() 안에 있던 것을 여기로 옮겼다 — 거기 두면 프로덕션에서
    #    아예 안 돈다(주문 수집이 2026-07-20 에 겪은 바로 그 자리).
    #    라이브 실측 2026-08-04: 캐시가 3,291건에서 멈춰 있었다(롯데온만 실제 136,510건).
    try:
        from scheduler.main import start_catalog_sync_scheduler
        start_catalog_sync_scheduler()
    except Exception:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("상품 훑기 스케줄러 시작 실패")

    # 노션 투두 일일 보고(매일 09:30 KST → 카카오톡). MOUM_NOTION_REPORT_AT="" 이면 끔.
    #  설정(노션 토큰·카카오 로그인)이 안 됐으면 틱이 조용히 실패만 남기고 끝난다.
    try:
        from scheduler.main import start_notion_report_scheduler
        start_notion_report_scheduler()
    except Exception:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("노션 보고 스케줄러 시작 실패")

    return app


def render_template_or_text(text):
    """템플릿 없으면 plain text — error 핸들러가 base 템플릿 충돌하지 않도록."""
    return f"<!DOCTYPE html><html><body style='font-family:sans-serif;padding:40px'><h2>{text}</h2><a href='/'>← 홈으로</a></body></html>"


# datetime import 보강 (rate limit 에서 사용)
from datetime import datetime, timezone  # noqa: E402, F811


def _setup_logging() -> None:
    # [2026-06-05 PERF] 로그 자동 회전 — app.log 가 무한정 커지던 문제(27MB+ 관측) 방지.
    #   5MB 초과 시 app.log.1~3 으로 밀고, 4개 초과분(가장 오래된 것)은 자동 삭제.
    #   → 로그 총량 최대 ~20MB 로 상한. 로그인·크롤·데이터엔 영향 없음(단순 기록 파일).
    from logging.handlers import RotatingFileHandler
    _fh = RotatingFileHandler(
        Config.LOG_DIR / "app.log", encoding="utf-8",
        maxBytes=5 * 1024 * 1024, backupCount=3,
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            _fh,
            logging.StreamHandler(),
        ],
    )


if __name__ == "__main__":
    _setup_logging()
    app = create_app()
    # 스케줄러는 운영 모드에서만 시작 (테스트 모드는 명시적으로 호출)
    # [2026-06-03] DISABLE_SCHEDULER=1 (로컬 '보면서 크롤' 모드) 이면 자동 스케줄러 끔
    #   → 매분 자동 크롤로 브라우저 창이 계속 뜨는 것 방지. 수동 「전체 크롤」만 동작.
    if not Config.DEBUG and os.environ.get("DISABLE_SCHEDULER") != "1":
        try:
            from scheduler.main import start_scheduler
            start_scheduler()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("scheduler 시작 실패 — Flask는 계속 진행")
    print(f"\n[르무통 재고 업데이트] Starting on http://{Config.HOST}:{Config.PORT}\n")
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
