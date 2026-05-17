"""[E] 홈 화면 — KPI 4개 + 다음 자동 실행 + 가격 차트 + 빠른 진입."""
import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, jsonify

from shared.db import SessionLocal
from lemouton.sourcing.models import Model, DiscoveryQueueItem
from lemouton.uploader.models import MarketRegistration
from lemouton.templates.models import PriceTrackHistory
from lemouton.sources.models import SourceProduct, SourceOption

bp = Blueprint('home', __name__)


def _get_musinsa_non_member_alert():
    """무신사 비회원가 크롤링 감지 — D1 드로워 카드용.

    검출 룰 (Phase 8.8.3 정확화):
      - source_id=3 (무신사) 의 SourceOption 중 다음 조건 충족 시 "비회원가" 판정:
        (1) dynamic_benefits_json 에 ``is_member_price=True`` 없음 OR
        (2) ``member_price`` 키 없음/None OR
        (3) ``member_price >= sale_price`` (의심 — 회원가 효과 없음)
      - 회원가 추출 성공 옵션 (is_member_price=True + member_price < sale_price) 는 정상 → 제외

    Returns: {'product_count': N, 'option_count': M, 'details': [{bundle, options:[...]}]}
    """
    s = SessionLocal()
    try:
        from lemouton.sourcing.models_pricing import OptionSourceUrl
        sps = (s.query(SourceProduct)
               .filter_by(site='musinsa', deleted_at=None)
               .all())
        product_count = 0
        option_count = 0
        details = []
        for sp in sps:
            # 옵션별 비회원가 판정 (SourceOption.dynamic_benefits_json 검사)
            opts = []
            sk_rows = (s.query(OptionSourceUrl)
                       .filter_by(source_id=3, product_url=sp.url)
                       .all())
            # SourceOption (옵션 단위 dyn) 조회 — sku 별 dyn 확인
            so_by_sku = {}
            for so in (s.query(SourceOption).filter_by(source_product_id=sp.id, deleted_at=None).all()):
                try:
                    so_dyn = json.loads(so.dynamic_benefits_json or '{}') if so.dynamic_benefits_json else {}
                except Exception:
                    so_dyn = {}
                # color/size 로 매칭 (대표)
                k = f"{so.color_text or ''}|{so.size_text or ''}"
                so_by_sku[k] = so_dyn

            for osu in sk_rows:
                if not osu.price_cached:
                    continue
                # 옵션의 dyn 가져오기 (첫 매칭 옵션 dyn 사용 — 모든 옵션 동일 가정)
                sample_dyn = next(iter(so_by_sku.values()), {})
                _is_member = bool(sample_dyn.get('is_member_price'))
                _member_price = sample_dyn.get('member_price')
                # 비회원가 판정
                is_non_member = (
                    not _is_member or
                    _member_price is None or
                    (_member_price and _member_price >= osu.price_cached)
                )
                if is_non_member:
                    opts.append({
                        'sku': osu.canonical_sku,
                        'sale_price': osu.price_cached,
                        'expected_member_price': int(osu.price_cached * 0.89),  # 추정 (11% 차이)
                        'has_dyn': bool(sample_dyn),
                    })
            if opts:
                product_count += 1
                option_count += len(opts)
                details.append({
                    'sp_id': sp.id,
                    'name': sp.product_name or '(이름 미설정)',
                    'url': sp.url,
                    'last_fetched_at': sp.last_fetched_at.strftime('%m-%d %H:%M') if sp.last_fetched_at else '—',
                    'options': opts[:20],
                    'opt_total': len(opts),
                })
        return {
            'product_count': product_count,
            'option_count': option_count,
            'details': details,
        }
    finally:
        s.close()


@bp.get('/api/dashboard/musinsa-non-member')
def api_musinsa_non_member():
    """드로워 detail 비동기 fetch (Phase 8.8.2 에서 확장)."""
    return jsonify({'ok': True, 'data': _get_musinsa_non_member_alert()})


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

        # ⚠ 무신사 비회원가 크롤링 알림 (Phase 8.8.1 — D1 드로워)
        nm_alert = _get_musinsa_non_member_alert()

        return {
            'bundles': bundles,
            'unmapped': unmapped,
            'price_changes': recent_changes,
            'upload_failed': upload_failed,
            'auto_on': auto_on,
            'auto_off': auto_off,
            'musinsa_non_member_products': nm_alert['product_count'],
            'musinsa_non_member_options': nm_alert['option_count'],
            'musinsa_non_member_details': nm_alert['details'],
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
    """홈 — KPI/모음전/자동화 표시. 한 helper 실패해도 페이지는 떠야 함 (defensive)."""
    import logging
    _log = logging.getLogger(__name__)

    def _safe(fn, fallback, label):
        try:
            return fn()
        except Exception as e:
            _log.exception("[home/index] %s 실패 (fallback 사용): %s", label, e)
            return fallback

    return render_template(
        'home.html',
        active='home',
        kpis=_safe(_get_kpis, {
            'bundles': 0, 'unmapped': 0, 'price_changes': 0, 'upload_failed': 0,
            'auto_on': 0, 'auto_off': 0,
            'musinsa_non_member_products': 0, 'musinsa_non_member_options': 0,
            'musinsa_non_member_details': [],
        }, 'kpis'),
        recent_bundles=_safe(lambda: _get_recent_bundles(), [], 'recent_bundles'),
        next_run=_safe(_get_next_run_info, {'countdown': '—', 'next_at': '—'}, 'next_run'),
        bundle_toggle_rows=_safe(lambda: _get_bundle_toggle_rows(limit=5), [], 'bundle_toggle_rows'),
    )
