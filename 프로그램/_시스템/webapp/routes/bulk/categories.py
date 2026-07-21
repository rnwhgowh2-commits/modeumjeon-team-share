# -*- coding: utf-8 -*-
"""카테고리 사전 라우트 — 전수 수집(harvest)·현황(status).

실수집은 서버에서만 의미가 있다(마켓 API=서버 단일IP·IP 등록 게이트).
수집 실패는 502 + 사유 원문 — 실패를 성공으로 칠하지 않는다.

⚠️ 마켓별 path·인증은 `webapp/data/marketplace_api_map.json` 이 정본이다(consult-market-map
게이트). 계획서 초안이 추정한 스마트스토어 `/external/v1/categories` 는 지도 실측과 달라
`/v1/categories` 를 쓴다(smartstore.get-category-list-product 및 카테고리군 다른 4개 API
전부 /external 프리픽스 없음 — 상품/주문 계열과 다른 규약).
"""
from __future__ import annotations

import datetime
import time

from flask import jsonify

from shared.db import SessionLocal
from lemouton.registration import category_harvest as ch
from lemouton.registration.models import MarketCategory
from . import bp

MARKETS = ('smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon')


def _first_env_prefix(session, market):
    from lemouton.sourcing.models_v2 import UploadAccount
    acct = (session.query(UploadAccount)
            .filter_by(market=market, is_active=True).order_by(UploadAccount.id).first())
    if acct is None:
        raise ch.HarvestError(f'{market}: 활성 계정이 없음 — 판매처 계정 관리에서 먼저 등록')
    return acct.env_prefix


def _run_harvest(market):
    """마켓별 실호출 → 행 리스트. (테스트에서 monkeypatch 되는 경계)"""
    import lemouton.uploader.market_fetch as MF
    s = SessionLocal()
    try:
        if market == 'eleven11':
            client = MF._eleven11_client(_first_env_prefix(s, market))
            xml = client.request('GET', '/rest/cateservice/category')
            return ch.parse_eleven11(xml)
        if market == 'smartstore':
            client = MF._smartstore_client(_first_env_prefix(s, market))
            # 지도(marketplace_api_map.json: smartstore.get-category-list-product) 실측 —
            # /external 프리픽스 없음. 카테고리군 API 5개 전부 이 규약(상품/주문과 다름).
            payload = client.request('GET', '/v1/categories')
            return ch.parse_smartstore(payload)
        if market == 'coupang':
            client = MF._coupang_client(_first_env_prefix(s, market))
            base = '/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/'
            def fetch(code):
                res = client.request('GET', base + code)
                return (res or {}).get('data') or {}
            return ch.harvest_coupang(fetch, sleep=time.sleep)
        if market in ('auction', 'gmarket'):
            client = MF._esm_client(market, _first_env_prefix(s, market))
            def fetch(code):
                path = '/item/v1/categories/site-cats' + (f'/{code}' if code else '')
                return client.request('GET', path)
            return ch.harvest_esm_site(fetch, sleep=time.sleep)
        if market == 'lotteon':
            import requests as _rq
            from lemouton.auth.secrets import load_credentials
            from shared.platforms.lotteon.auth import build_headers as _lotteon_headers
            creds = load_credentials(market='lotteon', env_prefix=_first_env_prefix(s, market))
            def fetch(skip, limit):
                r = _rq.get(
                    'https://onpick-api.lotteon.com/cheetah/econCheetah.ecn',
                    params={'job': 'cheetahStandardCategory', 'skip': skip, 'limit': limit},
                    headers=_lotteon_headers(creds.api_key), timeout=30)
                if r.status_code != 200:
                    raise ch.HarvestError(f'롯데온 표준카테고리 HTTP {r.status_code}: {r.text[:300]}')
                return (r.json() or {}).get('data') or []
            return ch.harvest_lotteon(fetch, sleep=time.sleep)
        raise ch.HarvestError(f'모르는 마켓: {market}')
    finally:
        s.close()


@bp.post('/api/categories/harvest/<market>')
def harvest(market):
    if market not in MARKETS:
        return jsonify({'ok': False, 'error': f'모르는 마켓: {market}'}), 400
    try:
        rows = _run_harvest(market)
    except ch.HarvestError as e:
        return jsonify({'ok': False, 'error': str(e)}), 502
    s = SessionLocal()
    try:
        try:
            summary = ch.save_snapshot(s, market, rows, now=datetime.datetime.utcnow())
        except ch.HarvestError as e:
            # save_snapshot 도 HarvestError 를 던질 수 있다(빈 rows 거부·배치 내 중복 코드).
            # 여기서도 502+원문 — 조용한 500 으로 삼키지 않는다.
            return jsonify({'ok': False, 'error': str(e)}), 502
        return jsonify({'ok': True, 'market': market, **summary})
    finally:
        s.close()


@bp.get('/api/categories/status')
def status():
    s = SessionLocal()
    try:
        out = []
        for m in MARKETS:
            q = s.query(MarketCategory).filter_by(market=m)
            alive = q.filter(MarketCategory.removed_at.is_(None))
            last = (q.order_by(MarketCategory.harvested_at.desc()).first())
            out.append({
                'market': m,
                'total': alive.count(),
                'leaves': alive.filter(MarketCategory.is_leaf.is_(True)).count(),
                'removed': q.filter(MarketCategory.removed_at.isnot(None)).count(),
                'last_harvested': (last.harvested_at.isoformat(sep=' ') if last else None),
            })
        return jsonify({'ok': True, 'rows': out})
    finally:
        s.close()
