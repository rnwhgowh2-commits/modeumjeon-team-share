# -*- coding: utf-8 -*-
"""상품수집&전송 — 골라서 지금 보내기.

설계서: docs/superpowers/specs/2026-08-02-상품-마켓전송-탭-design.md
사장님 확정 2026-08-02 — 더망고 「상품 업데이트 & 마켓등록/수정」 구조를 따르되
우리 데이터 모델(구성=벌)에 맞춘다.

━━ [중요] 하위탭 원천이 두 곳이다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
    """마켓 전송 — 조건검색(상품·소싱처·판매처 기준) · 목록 · 전송 실행.

    2026-08-19 사장님 확정 1-B·2-A·3-A·4-D — 이슈 #1057.
    """
    from shared.db import SessionLocal
    from lemouton.send import listing as L
    s = SessionLocal()
    try:
        srcs = L.source_options(s)
        accts = L.account_options(s)
    finally:
        s.close()
    return render_template('market_send/index.html',
                           active_app='send', active='market_send',
                           subtabs=SUBTABS, tab='send',
                           markets=_markets(), sources=srcs, accounts=accts,
                           source_universe=_source_universe(),
                           source_labels=_source_labels(),
                           date_basis=L.DATE_BASIS, sort_options=L.SORT_OPTIONS,
                           policy_filter=L.POLICY_FILTER, search_in=L.SEARCH_IN)


@bp.get('/api/market-send/rows')
def api_rows():
    """목록 한 쪽. 한 줄 = **구성(벌)** — 사장님 확정 ①.

    query: page · per_page · date_basis · date_from · date_to · sort ·
           policy · unlisted_only · registered_only · stock_status ·
           sources(콤마) · accounts(콤마) · search_in · keyword
    """
    from shared.db import SessionLocal
    from lemouton.send import listing as L
    a = request.args
    s = SessionLocal()
    try:
        got = L.rows(
            s, page=a.get('page', 1, type=int), per_page=a.get('per_page', 50, type=int),
            date_basis=a.get('date_basis', ''), date_from=a.get('date_from', ''),
            date_to=a.get('date_to', ''), sort=a.get('sort', ''),
            policy=a.get('policy', ''),
            unlisted_only=a.get('unlisted_only', '', type=str) == '1',
            registered_only=a.get('registered_only', '', type=str) == '1',
            stock_status=a.get('stock_status', ''),
            sources=[x for x in (a.get('sources') or '').split(',') if x],
            accounts=[x for x in (a.get('accounts') or '').split(',') if x],
            search_in=a.get('search_in', 'name'), keyword=a.get('keyword', ''))
    finally:
        s.close()
    for r in got['rows']:                       # 화면이 그대로 쓰게 문자열로
        r['crawled_at'] = r['crawled_at'].strftime('%m-%d %H:%M') if r['crawled_at'] else ''
        r['sent'] = {k: v.strftime('%m-%d %H:%M') for k, v in (r['sent'] or {}).items() if v}
        mc = r.get('market_collected_at')
        r['market_collected_at'] = mc.strftime('%m-%d %H:%M') if mc else ''
    return jsonify({'ok': True, **got})


@bp.get('/api/market-send/suggest/products')
def api_suggest_products():
    """상품 기준 자동완성 — 브랜드·상품명. `?q=` 두 글자 이상."""
    from shared.db import SessionLocal
    from lemouton.send import listing as L
    s = SessionLocal()
    try:
        return jsonify({'ok': True, **L.suggest_products(s, request.args.get('q', ''))})
    finally:
        s.close()


@bp.get('/api/market-send/suggest/policies')
def api_suggest_policies():
    """판매처 기준 정책 이름 자동완성. `?q=` 두 글자 이상."""
    from shared.db import SessionLocal
    from lemouton.send import listing as L
    s = SessionLocal()
    try:
        return jsonify({'ok': True, **L.suggest_policies(s, request.args.get('q', ''))})
    finally:
        s.close()


@bp.post('/api/market-send/start')
def api_start():
    """전송 시작 — **백그라운드로** 띄우고 곧바로 job_id 를 돌려준다.

    [중요] 요청 안에서 돌리면 사이트 전체가 502 난다(gunicorn 180초·CF 100초 상한 —
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


@bp.get('/api/market-send/rows/<int:set_id>/margin')
def api_row_margin(set_id: int):
    """구성 하나(호버카드용) — 옵션별·마켓별 판매가·최근 변동·예상마진.

    산식은 새로 안 만든다 — 매입가는 `price_diff._current_purchase`(주문 쪽과
    같은 경로), 수수료율은 `pricing.unified.resolve_market_policy`(가격을 만들 때
    쓴 그 정책), 마진은 `reconcile.compute_margin_amount` 그대로 재사용한다.
    셋 중 하나라도 못 구하면 그 칸만 margin_reason 으로 「확인 불가」를 남긴다
    (listing.py 의 buy_source=None 과 같은 원칙 — 모르는 걸 0 으로 채우지 않는다).

    응답: {skus: [{sku, color, size, markets: {마켓키: {price, stock, fetched_at,
                   prev_price, margin, margin_reason}}}]}
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    from collections import defaultdict
    from shared.db import SessionLocal
    from lemouton.sets.models import (SetProduct, SetOption, SetChannel,
                                      SetChannelOption, ChannelChangeEvent)
    from lemouton.sourcing.models import Option
    from lemouton.orders.price_diff import _current_purchase, _price_templates_for, _PriceLike
    from lemouton.pricing.unified import resolve_market_policy
    from lemouton.uploader.reconcile import compute_margin_amount

    since = _dt.now(_tz.utc) - _td(days=14)
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

        finals, _errors = _current_purchase(s, skus)
        tpl_by_sku = _price_templates_for(s, skus)

        mkt_rows = (s.query(SetChannel.market, SetChannelOption.canonical_sku,
                            SetChannelOption.mkt_price, SetChannelOption.mkt_stock,
                            SetChannelOption.mkt_fetched_at)
                    .join(SetChannelOption, SetChannelOption.channel_id == SetChannel.id)
                    .filter(SetChannel.set_id == set_id,
                            SetChannelOption.canonical_sku.in_(skus)).all())
        by_sku: dict = defaultdict(dict)
        for mk, sku, price, stock, fetched_at in mkt_rows:
            by_sku[sku][mk] = {'price': price, 'stock': stock, 'fetched_at': fetched_at}

        # 최근 가격 변동 1건씩 (sku, market) — desc 정렬이라 처음 만난 게 최신
        chg_rows = (s.query(ChannelChangeEvent)
                    .filter(ChannelChangeEvent.set_id == set_id,
                            ChannelChangeEvent.canonical_sku.in_(skus),
                            ChannelChangeEvent.field == 'price',
                            ChannelChangeEvent.at >= since)
                    .order_by(ChannelChangeEvent.canonical_sku, ChannelChangeEvent.market,
                              ChannelChangeEvent.at.desc()).all())
        recent_chg = {}
        for c in chg_rows:
            recent_chg.setdefault((c.canonical_sku, c.market), c)

        fee_cache: dict = {}

        def _fee_for(market, tpl):
            key = (market, id(tpl))
            if key not in fee_cache:
                try:
                    pol = resolve_market_policy(tpl, market, 'sourcing')
                    fee_cache[key] = (float(pol['fee_rate']), int(pol.get('shipping_fee') or 0))
                except Exception:                                  # noqa: BLE001
                    fee_cache[key] = None
            return fee_cache[key]

        out = []
        for o in opts:
            mk_data = by_sku.get(o.canonical_sku, {})
            if not mk_data:
                continue
            purchase = finals.get(o.canonical_sku)
            tpl = tpl_by_sku.get(o.canonical_sku)
            markets_out = {}
            for mk, d in mk_data.items():
                price, margin, reason = d['price'], None, None
                if price is None:
                    reason = '판매가 확인 불가'
                elif purchase is None:
                    reason = '매입가 확인 불가'
                else:
                    fee = _fee_for(mk, tpl)
                    if fee is None:
                        reason = '수수료 정책 확인 불가'
                    else:
                        fee_rate, shipping = fee
                        margin = compute_margin_amount(_PriceLike(price, fee_rate, shipping), purchase)
                        if margin is None:
                            reason = '계산 불가'
                chg = recent_chg.get((o.canonical_sku, mk))
                markets_out[mk] = {
                    'price': price, 'stock': d['stock'],
                    'fetched_at': d['fetched_at'].strftime('%m-%d %H:%M') if d['fetched_at'] else None,
                    'prev_price': chg.prev_value if chg else None,
                    'margin': margin, 'margin_reason': reason,
                }
            out.append({
                'sku': o.canonical_sku,
                'color': o.color_display or o.color_code or '',
                'size': o.size_display or o.size_code or '',
                'markets': markets_out,
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
