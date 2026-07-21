# -*- coding: utf-8 -*-
"""카테고리 사전 라우트 — 전수 수집(harvest)·현황(status).

실수집은 서버에서만 의미가 있다(마켓 API=서버 단일IP·IP 등록 게이트).
수집 실패는 사유 원문을 그대로 노출한다 — 실패를 성공으로 칠하지 않는다.

⚠️ 마켓별 path·인증은 `webapp/data/marketplace_api_map.json` 이 정본이다(consult-market-map
게이트). 계획서 초안이 추정한 스마트스토어 `/external/v1/categories` 는 지도 실측과 달라
`/v1/categories` 를 쓴다(smartstore.get-category-list-product 및 카테고리군 다른 4개 API
전부 /external 프리픽스 없음 — 상품/주문 계열과 다른 규약).

★ [2026-07-22 코드리뷰 수정] 수집은 백그라운드 스레드로 돈다. Dockerfile 이 gunicorn 을
`--timeout 60`(sync worker)로 띄우는데, 쿠팡 BFS 는 노드당 1콜+0.2s 슬립이라 카테고리
트리가 조금만 커도 수 분이 걸린다 — 동기 처리였으면 워커가 60초에 죽어 요청도 응답도
증발했다(거짓 실패). POST 는 시작만 확인해 주고(202), 실제 진행상황·성공/실패는
GET status 를 폴링해서 읽는다.
"""
from __future__ import annotations

import datetime
import threading
import time

from flask import jsonify
from sqlalchemy.exc import IntegrityError

from shared.db import SessionLocal
from lemouton.registration import category_harvest as ch
from lemouton.registration.models import MarketCategory
from . import bp

MARKETS = ('smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon')

# 마켓별 백그라운드 수집 상태 — {market: {'running','started_at','finished_at','summary','error'}}.
# 프로세스 전역(모듈 레벨) 메모리 상태다: gunicorn 워커가 여러 개면 워커마다 따로 논다
# (지금은 단일 워커 전제 — 워커 수를 늘리면 이 상태도 워커 간에 안 보인다는 걸 알고 있을 것).
_harvest_state: dict[str, dict] = {}
_harvest_lock = threading.Lock()


def _new_state() -> dict:
    return {'running': False, 'started_at': None, 'finished_at': None,
            'summary': None, 'error': None}


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


def _harvest_and_save(market):
    """백그라운드 스레드 본체 — `_run_harvest` → `save_snapshot`, 결과를 `_harvest_state` 에 반영.

    실패(HarvestError·저장 시점 IntegrityError·그 밖의 예상 밖 예외)는 전부 사유 원문을
    `state['error']` 에 남긴다 — 삼키지 않는다. 성공 시에는 `state['summary']` 를 채우고
    `state['error']` 는 None 으로 되돌린다(직전 실패가 이번 성공 뒤에도 남아 있으면 화면이
    거짓 실패를 계속 보여준다).
    """
    state = _harvest_state[market]
    s = SessionLocal()
    try:
        rows = _run_harvest(market)
        summary = ch.save_snapshot(s, market, rows, now=datetime.datetime.utcnow())
        with _harvest_lock:
            state['summary'] = summary
            state['error'] = None
    except ch.HarvestError as e:
        s.rollback()
        with _harvest_lock:
            state['error'] = str(e)
    except IntegrityError as e:
        # save_snapshot 이 배치 내 중복은 미리 걸러내지만, 이 가드를 뚫고 동시 저장이
        # 붙는 경우(레이스)까지 대비한다 — 500 으로 죽지 않고 사유를 상태로 번역한다.
        s.rollback()
        with _harvest_lock:
            state['error'] = f'{market}: 저장 충돌(IntegrityError) — {e}'
    except Exception as e:  # noqa: BLE001 — 예상 밖 예외도 삼키지 않고 원문을 상태에 남긴다.
        s.rollback()
        with _harvest_lock:
            state['error'] = f'{market}: 예상 밖 오류 — {e!r}'
    finally:
        s.close()
        with _harvest_lock:
            state['running'] = False
            state['finished_at'] = datetime.datetime.utcnow()


@bp.post('/api/categories/harvest/<market>')
def harvest(market):
    """카테고리 전수 수집 시작 — 응답은 "시작했다"만 확인해 준다(결과는 안 실린다).

    응답 계약 (카드 JS 가 그대로 분기한다):
      - 모르는 마켓                → 400 {'ok': False, 'error': '모르는 마켓: <m>'}
      - 그 마켓이 이미 수집 중    → 409 {'ok': False, 'error': '<m>: 이미 수집이 진행 중입니다'}
      - 시작 성공                 → 202 {'ok': True, 'started': True, 'market': '<m>'}
    성공/실패 결과(added/updated/removed/total 또는 사유 원문)는 이 응답에 없다 — 백그라운드
    스레드가 끝난 뒤 GET /api/categories/status 의 running/last_error/last_summary 로 읽는다.
    (구 버전은 200 으로 바로 결과를 돌려줬다 — sync 워커 60초 타임아웃에 죽는 게 Critical
    코드리뷰 지적이라 이 계약으로 바꿨다.)
    """
    if market not in MARKETS:
        return jsonify({'ok': False, 'error': f'모르는 마켓: {market}'}), 400
    with _harvest_lock:
        state = _harvest_state.setdefault(market, _new_state())
        if state['running']:
            return jsonify({'ok': False, 'error': f'{market}: 이미 수집이 진행 중입니다'}), 409
        state['running'] = True
        state['started_at'] = datetime.datetime.utcnow()
        state['finished_at'] = None
        state['error'] = None
        # state['summary'] 는 지우지 않는다 — 이번 수집이 끝날 때까지 화면은 "직전 성공"을
        # 계속 보여준다(진행 중이라고 결과를 없는 셈 치면 사용자가 더 불안하다).
    t = threading.Thread(target=_harvest_and_save, args=(market,), daemon=True)
    t.start()
    return jsonify({'ok': True, 'started': True, 'market': market}), 202


@bp.get('/api/categories/status')
def status():
    """마켓별 카테고리 사전 현황 — DB 집계(total/leaves/removed/last_harvested) +
    백그라운드 수집 상태(running/last_error/last_summary)를 합쳐서 준다."""
    s = SessionLocal()
    try:
        out = []
        for m in MARKETS:
            q = s.query(MarketCategory).filter_by(market=m)
            alive = q.filter(MarketCategory.removed_at.is_(None))
            last = (q.order_by(MarketCategory.harvested_at.desc()).first())
            with _harvest_lock:
                st = _harvest_state.get(m) or _new_state()
                running, last_error, last_summary = st['running'], st['error'], st['summary']
            out.append({
                'market': m,
                'total': alive.count(),
                'leaves': alive.filter(MarketCategory.is_leaf.is_(True)).count(),
                'removed': q.filter(MarketCategory.removed_at.isnot(None)).count(),
                'last_harvested': (last.harvested_at.isoformat(sep=' ') if last else None),
                'running': running,
                'last_error': last_error,
                'last_summary': last_summary,
            })
        return jsonify({'ok': True, 'rows': out})
    finally:
        s.close()
