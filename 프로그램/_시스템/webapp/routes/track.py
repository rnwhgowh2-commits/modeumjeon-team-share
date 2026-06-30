"""[E] 가격·재고 추적 화면."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request

from shared.db import SessionLocal
from lemouton.sourcing.models import Model, Option
from lemouton.templates.models import PriceTrackHistory

bp = Blueprint('track', __name__)

# 소싱처별 의미 색상 — 5색 색조 모두 다르게 (5개 라인 명확 구분)
SOURCE_COLORS = {
    'lemouton': '#3182F6',     # 파랑 — 르무통 (브랜드 primary)
    'musinsa': '#191F28',      # 검정 — 무신사 BI
    'ssf': '#F2994A',          # 주황 — SSF (5색 색조 차별화)
    'smartstore': '#03C75A',   # 그린 — 네이버 스마트스토어 BI
    'lotteon': '#E04444',      # 빨강 — 롯데
}
SOURCE_LABELS = {
    'lemouton': '르무통 공홈',
    'musinsa': '무신사',
    'ssf': 'SSF',
    'smartstore': '스마트스토어',
    'lotteon': '롯데',
}


def _options_for_chart(s, model_code: str | None, color_code: str | None):
    q = s.query(Option)
    if model_code and model_code != 'all':
        q = q.filter_by(model_code=model_code)
    if color_code and color_code != 'all':
        q = q.filter_by(color_code=color_code)
    return q.order_by(Option.model_code, Option.color_code, Option.size_code).limit(20).all()


def _series_for_option(s, canonical_sku: str, days: int):
    """가격 이력 시리즈 — captured_at 은 ISO 문자열로 직렬화 (JS tojson 호환)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        s.query(PriceTrackHistory)
        .filter(PriceTrackHistory.canonical_sku == canonical_sku,
                PriceTrackHistory.captured_at >= cutoff)
        .order_by(PriceTrackHistory.captured_at)
        .all()
    )
    by_source: dict[str, list] = {}
    for r in rows:
        # captured_at 이 None 또는 datetime — 둘 다 처리
        at_iso = r.captured_at.isoformat() if r.captured_at else ''
        by_source.setdefault(r.source, []).append({
            'price': r.price,
            'stock': r.stock,
            'at': at_iso,
        })
    lowest = None
    for src, points in by_source.items():
        if not points:
            continue
        cur_min = min(p['price'] for p in points if p['price'] is not None) if any(p['price'] for p in points) else None
        if cur_min is None:
            continue
        if lowest is None or cur_min < lowest['price']:
            lowest = {'source': src, 'price': cur_min}
    return {'by_source': by_source, 'lowest': lowest}


def _color_codes_for_model(s, model_code: str | None) -> list[tuple[str, str]]:
    """선택된 모음전(또는 전체) 의 색상 옵션 리스트 — (color_code, color_display)."""
    q = s.query(Option.color_code, Option.color_display).distinct()
    if model_code and model_code != 'all':
        q = q.filter_by(model_code=model_code)
    rows = q.order_by(Option.color_code).all()
    return [(r[0], r[1] or r[0]) for r in rows]


def _chart_bounds(by_source: dict) -> tuple[int, int]:
    """차트 Y축 동적 범위 — 모든 데이터 min/max + 5% 패딩."""
    prices = []
    for points in by_source.values():
        for p in points:
            if p.get('price') is not None:
                prices.append(p['price'])
    if not prices:
        return 0, 100000  # 빈 차트 기본값
    lo, hi = min(prices), max(prices)
    span = max(hi - lo, 1000)
    pad = span * 0.1
    return int(lo - pad), int(hi + pad)


@bp.route('/track')
def index():
    model_code = request.args.get('model_code', 'all')
    color_code = request.args.get('color_code', 'all')
    days = int(request.args.get('days', '30'))

    s = SessionLocal()
    try:
        models = s.query(Model).order_by(Model.model_code).all()
        color_options = _color_codes_for_model(s, model_code)
        opts = _options_for_chart(s, model_code, color_code)
        charts = []
        for o in opts:
            series = _series_for_option(s, o.canonical_sku, days)
            y_lo, y_hi = _chart_bounds(series['by_source'])
            charts.append({
                'sku': o.canonical_sku,
                'series': series,
                'y_lo': y_lo,
                'y_hi': y_hi,
            })
    finally:
        s.close()
    return render_template(
        'track/index.html',
        active='track',
        models=models,
        model_code=model_code,
        color_code=color_code,
        color_options=color_options,
        days=days,
        charts=charts,
        source_colors=SOURCE_COLORS,
        source_labels=_track_source_labels(),
    )


def _track_source_labels() -> dict:
    """[2026-06-30 단일명부] 명부(get_labels) 라벨 + 하드코딩 폴백 병합."""
    out = dict(SOURCE_LABELS)
    try:
        from lemouton.sourcing.source_registry import get_labels
        out.update(get_labels())
    except Exception:
        pass
    return out
