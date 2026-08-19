# -*- coding: utf-8 -*-
"""상품수집&전송 — 골라서 지금 보내기.

설계서: docs/superpowers/specs/2026-08-02-상품-마켓전송-탭-design.md
사장님 확정 2026-08-02 — 더망고 「상품 업데이트 & 마켓등록/수정」 구조를 따르되
우리 데이터 모델(구성=벌)에 맞춘다.

━━ 🔴 하위탭 원천이 두 곳이다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  화면 가로탭 = 여기 :data:`SUBTABS`
  상단 메뉴 펼침 = `webapp/routes/api_sidebar.py` 의 `_SEND2`
  **둘을 같이 안 고치면 메뉴만 옛것으로 남는다** — optgen 하위탭 때 실제로 겪었다.

━━ 이 탭이 자동화와 다른 점 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  자동화 = 값이 바뀌면 **저절로** 나간다 (조건·주기)
  마켓 전송 = 사장님이 **골라서 지금** 보낸다 (신규 등록 포함)
"""
from flask import Blueprint, jsonify, redirect, render_template, request

bp = Blueprint('market_send', __name__)

#: 상단 분류 「상품수집&전송」의 하위탭 2개 — 사장님 확정 ⑤.
#  ⚠️ 여기 없는 탭은 화면에 아예 안 뜬다(catalog·bulk·optgen 과 같은 함정).
SUBTABS = [
    {'key': 'send', 'label': '마켓 전송', 'url': '/market-send',
     'desc': '보낼 상품을 골라 지금 마켓으로 보냅니다'},
    {'key': 'auto', 'label': '자동화', 'url': '/automation',
     'desc': '소싱처 수집과 판매처 전송이 저절로 돌게 합니다'},
]


#: 보낼 마켓 — 정책 화면과 같은 순서·같은 이름(두 화면이 다르면 남의 집 같다).
def _markets():
    from lemouton.policy.fields import MARKETS
    return list(MARKETS)


#: 소싱처 로고그리드용 고정 순서 — shared/display_no.py 의 접두 명부가 단일 진실 원천.
#  ⚠️ 여기서 새로 짓지 않는다 — 표시번호 접두랑 어긋나면 두 화면이 다른 명부를 쓰게 된다.
def _source_universe():
    from shared.display_no import PREFIX_BY_SITE
    return list(PREFIX_BY_SITE.keys())


def _source_labels():
    from lemouton.sources.site_labels import SITE_LABEL
    return dict(SITE_LABEL)


@bp.get('/market-send')
def index():
    """마켓 전송 — 필터 · 목록 · 전송 실행 (A안: 필터 전부 펼침 · 더망고식)."""
    from shared.db import SessionLocal
    from lemouton.send import listing as L
    s = SessionLocal()
    try:
        srcs = L.source_options(s)
    finally:
        s.close()
    return render_template('market_send/index.html',
                           active_app='send', active='market_send',
                           subtabs=SUBTABS, tab='send',
                           markets=_markets(), sources=srcs,
                           source_universe=_source_universe(),
                           source_labels=_source_labels(),
                           date_basis=L.DATE_BASIS, policy_filter=L.POLICY_FILTER,
                           listed_filter=L.LISTED_FILTER, search_in=L.SEARCH_IN)


@bp.get('/api/market-send/rows')
def api_rows():
    """목록 한 쪽. 한 줄 = **구성(벌)** — 사장님 확정 ①.

    query: page · per_page · date_basis · date_from · date_to ·
           policy · listed · sources(콤마) · search_in · keyword
    """
    from shared.db import SessionLocal
    from lemouton.send import listing as L
    a = request.args
    s = SessionLocal()
    try:
        got = L.rows(
            s, page=a.get('page', 1, type=int), per_page=a.get('per_page', 50, type=int),
            date_basis=a.get('date_basis', ''), date_from=a.get('date_from', ''),
            date_to=a.get('date_to', ''), policy=a.get('policy', ''),
            listed=a.get('listed', ''),
            sources=[x for x in (a.get('sources') or '').split(',') if x],
            search_in=a.get('search_in', 'name'), keyword=a.get('keyword', ''))
    finally:
        s.close()
    for r in got['rows']:                       # 화면이 그대로 쓰게 문자열로
        r['crawled_at'] = r['crawled_at'].strftime('%m-%d %H:%M') if r['crawled_at'] else ''
        r['sent'] = {k: v.strftime('%m-%d %H:%M') for k, v in (r['sent'] or {}).items() if v}
    return jsonify({'ok': True, **got})


@bp.post('/api/market-send/start')
def api_start():
    """전송 시작 — **백그라운드로** 띄우고 곧바로 job_id 를 돌려준다.

    🔴 요청 안에서 돌리면 사이트 전체가 502 난다(gunicorn 180초·CF 100초 상한 —
      이 저장소에 실제 사고 이력). 화면은 job_id 로 로그만 받아 간다.

    body: {set_ids: [...], markets: [...]}  (둘 다 필수)
    """
    from shared.db import SessionLocal
    from lemouton.send import runner as R
    from lemouton.send.service import SendError
    p = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        jid = R.start(s, set_ids=[int(x) for x in (p.get('set_ids') or [])],
                      markets=[str(x) for x in (p.get('markets') or [])],
                      filters=p.get('filters') or {})
        return jsonify({'ok': True, 'job_id': jid})
    except SendError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    finally:
        s.close()


@bp.get('/api/market-send/rows/<int:set_id>/history')
def api_row_history(set_id: int):
    """구성 하나(호버카드용) — 옵션별·소싱처별 최근 가격·재고 2줄.

    같은 옵션에 소싱처가 여럿이면 값도 여럿이다 — 「지금 사오는 곳」을 안 정했으므로
    (listing.py 의 buy_source=None 과 같은 원칙) 한 숫자로 뭉개지 않고 소싱처별로 그대로 낸다.

    응답: {skus: [{sku, color, size, sources: {소싱처키: {history:[{date,price,stock}], current_price, current_stock}}}]}
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    from collections import defaultdict
    from shared.db import SessionLocal
    from lemouton.sets.models import SetProduct, SetOption
    from lemouton.sourcing.models import Option
    from lemouton.templates.models import PriceTrackHistory

    since = _dt.now(_tz.utc) - _td(days=14)   # 호버카드는 최근 2줄이면 충분 — 전체 이력은 /price-chart
    s = SessionLocal()
    try:
        skus = [r[0] for r in
                s.query(SetOption.canonical_sku)
                .join(SetProduct, SetOption.set_product_id == SetProduct.id)
                .filter(SetProduct.set_id == set_id).all()]
        if not skus:
            return jsonify(ok=True, skus=[])

        opts = (s.query(Option).filter(Option.canonical_sku.in_(skus))
                .order_by(Option.sort_order, Option.color_code, Option.size_code).all())
        rows = (s.query(PriceTrackHistory)
                .filter(PriceTrackHistory.canonical_sku.in_(skus),
                        PriceTrackHistory.captured_at >= since)
                .order_by(PriceTrackHistory.canonical_sku, PriceTrackHistory.source,
                          PriceTrackHistory.captured_at).all())

        hist: dict = defaultdict(lambda: defaultdict(dict))
        for r in rows:
            d = r.captured_at.strftime('%m-%d %H:%M') if r.captured_at else '?'
            existing = hist[r.canonical_sku][r.source].get(d)
            if existing is None or r.price is not None:
                hist[r.canonical_sku][r.source][d] = {'date': d, 'price': r.price, 'stock': r.stock}

        out = []
        for o in opts:
            src_data = {}
            for src_key, day_map in hist.get(o.canonical_sku, {}).items():
                pts = sorted(day_map.values(), key=lambda x: x['date'])[-2:]   # 최근 2개만
                cur = pts[-1] if pts else {}
                src_data[src_key] = {
                    'history': pts,
                    'current_price': cur.get('price'),
                    'current_stock': cur.get('stock'),
                }
            if not src_data:
                continue   # 이력 없는 옵션은 카드에서 뺀다 — 빈 줄을 늘어놓지 않는다
            out.append({
                'sku': o.canonical_sku,
                'color': o.color_display or o.color_code or '',
                'size': o.size_display or o.size_code or '',
                'sources': src_data,
            })
        return jsonify(ok=True, skus=out)
    finally:
        s.close()


@bp.get('/api/market-send/jobs/<int:job_id>/log')
def api_log(job_id: int):
    """`after` 뒤에 생긴 로그 줄만. 화면이 1초마다 받아 간다."""
    from shared.db import SessionLocal
    from lemouton.send import runner as R
    from lemouton.send.service import SendError
    s = SessionLocal()
    try:
        return jsonify({'ok': True,
                        **R.log_since(s, job_id, request.args.get('after', 0, type=int))})
    except SendError as e:
        return jsonify({'ok': False, 'error': str(e)}), 404
    finally:
        s.close()


@bp.get('/automation/')
def automation_slash():
    """끝에 빗금 붙은 주소도 자동화로 — 저장해 둔 바로가기가 죽지 않게."""
    return redirect('/automation' + (('?' + request.query_string.decode())
                                     if request.query_string else ''), code=302)
