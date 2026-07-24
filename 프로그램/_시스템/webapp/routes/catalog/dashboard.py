# -*- coding: utf-8 -*-
"""현황 보기 — 건수 스냅샷을 화면 모양으로 빚는다.

★ 28만 행을 세지 않는다. market_product_counts 스냅샷만 읽어 즉시 뜬다.
"""
from flask import jsonify, request

from lemouton.catalog.timefmt import iso_utc
from shared.db import SessionLocal

from . import bp

#: 화면에 그리는 순서. unknown 은 마지막 — 있으면 눈에 띄어야 한다.
STATUSES = ('sale', 'soldout', 'stopped', 'waiting', 'unknown')


def build_dashboard(counts: dict, measured: dict, group_counts: dict) -> dict:
    """{마켓:{계정:{상태:건수}}} → 화면이 읽는 모양.

    없는 상태는 0 으로 채운다 — 빈칸은 '모름'으로 오해된다.
    확인 시각이 없으면 None 그대로 둔다 — 없는 걸 '방금'으로 채우면
    낡은 숫자를 최신인 척 보여주게 된다.
    """
    markets = []
    summary = {s: 0 for s in STATUSES}
    summary['total'] = 0

    for market, accounts in counts.items():
        acc_list = []
        m_total = 0
        for account_key, by_status in accounts.items():
            row = {'account_key': account_key}
            a_total = 0
            for s in STATUSES:
                n = int(by_status.get(s, 0) or 0)
                row[s] = n
                a_total += n
                summary[s] += n
            row['total'] = a_total
            t = measured.get((market, account_key))
            row['measured_at'] = iso_utc(t)
            m_total += a_total
            acc_list.append(row)
        acc_list.sort(key=lambda r: r['total'], reverse=True)
        markets.append({'market': market, 'total': m_total, 'accounts': acc_list})
        summary['total'] += m_total

    markets.sort(key=lambda m: m['total'], reverse=True)
    summary['groups'] = int(group_counts.get('groups', 0) or 0)
    summary['linked'] = int(group_counts.get('linked', 0) or 0)

    return {'markets': markets, 'summary': summary,
            'unknown_total': summary['unknown']}


@bp.get('/api/dashboard')
def api_dashboard():
    """현황 숫자. 화면은 이것만 부르면 된다.

    scope='bundle'(기본) — 마켓에 올라간 상품 전체(우리 캐시)
    scope='bulk'         — 우리가 대량등록으로 올린 상품만
    ★ 탭이 실제로 다른 숫자를 보여줘야 한다. 같은 값을 주면 거짓 기능이다.
    """
    from lemouton.catalog import repository as R
    from lemouton.catalog.bulk_scope import bulk_counts
    from lemouton.catalog.models import MarketProduct, MarketProductGroup

    scope = (request.args.get('scope') or 'bundle').strip()
    if scope not in ('bundle', 'bulk'):
        return jsonify({'error': f'모르는 구분입니다: {scope}'}), 400

    s = SessionLocal()
    try:
        if scope == 'bulk':
            groups = s.query(MarketProductGroup).filter(
                MarketProductGroup.deleted_at.is_(None)).count()
            linked = s.query(MarketProduct).filter(
                MarketProduct.group_id.isnot(None),
                MarketProduct.deleted_at.is_(None)).count()
            out = build_dashboard(bulk_counts(s), {},
                                  {'groups': groups, 'linked': linked})
            out['scope'] = 'bulk'
            return jsonify(out)

        counts = R.dashboard_counts(s, market=request.args.get('market') or None)
        measured = R.account_measured_at(s)
        groups = s.query(MarketProductGroup).filter(
            MarketProductGroup.deleted_at.is_(None)).count()
        linked = s.query(MarketProduct).filter(
            MarketProduct.group_id.isnot(None),
            MarketProduct.deleted_at.is_(None)).count()
        out = build_dashboard(counts, measured,
                              {'groups': groups, 'linked': linked})
        out['scope'] = 'bundle'
        return jsonify(out)
    except Exception as e:      # noqa: BLE001
        return jsonify({'error': 'dashboard_failed', 'detail': str(e)[:300]}), 500
    finally:
        s.close()


@bp.post('/api/sync')
def api_sync():
    """「지금 동기화」 — 마켓 하나 또는 계정 하나만 다시 훑는다.

    ⚠️ 전체(28만 건)는 30~60분이 걸려 웹 요청으로 감당할 수 없다.
       market 을 반드시 찍어야 한다.
    """
    from lemouton.catalog import sync as S

    body = request.get_json(silent=True) or {}
    market = (body.get('market') or '').strip()
    account_key = (body.get('account_key') or '').strip()
    if not market:
        return jsonify({'ok': False,
                        'error': '어느 마켓을 다시 볼지 골라주세요.'}), 400

    s = SessionLocal()
    try:
        if account_key:
            acc = next((a for a in S._active_accounts(s, market)
                        if a.account_key == account_key), None)
            if acc is None:
                return jsonify({'ok': False,
                                'error': f'없는 계정입니다: {account_key}'}), 404
            client = S._client_for(market, acc.env_prefix)
            r = S.sync_account(s, market, account_key, client=client,
                               vendor_id=getattr(client, 'vendor_id', None))
            return jsonify({'ok': r['ok'], 'result': r})
        out = S.sync_all(session=s, market=market)
        return jsonify({'ok': out['failed_count'] == 0, 'result': out})
    except Exception as e:      # noqa: BLE001
        return jsonify({'ok': False, 'error': str(e)[:300]}), 500
    finally:
        s.close()
