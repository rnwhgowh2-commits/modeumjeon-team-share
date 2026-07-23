# -*- coding: utf-8 -*-
"""카테고리 사전 라우트 — 전수 수집(harvest)·현황(status).

실수집은 서버에서만 의미가 있다(마켓 API=서버 단일IP·IP 등록 게이트).
수집 실패는 사유 원문을 그대로 노출한다 — 실패를 성공으로 칠하지 않는다.

⚠️ 마켓별 path·인증은 `webapp/data/marketplace_api_map.json` 이 정본이다(consult-market-map
게이트). 스마트스토어 카테고리 path 는 [2026-07-22 라이브 실측] 지도 문서 표기(`/v1/categories`)
로는 **HTTP 404** — 실서버는 다른 스스 API 와 같이 `/external` 프리픽스가 필요해
`/external/v1/categories` 를 쓴다(문서의 /v1 표기는 프리픽스 생략 관례. 지도 되채움 완료).

★ [2026-07-22 코드리뷰 수정] 수집은 백그라운드 스레드로 돈다. Dockerfile 이 gunicorn 을
`--timeout 60`(sync worker)로 띄우는데, 쿠팡 BFS 는 노드당 1콜+0.2s 슬립이라 카테고리
트리가 조금만 커도 수 분이 걸린다 — 동기 처리였으면 워커가 60초에 죽어 요청도 응답도
증발했다(거짓 실패). POST 는 시작만 확인해 주고(202), 실제 진행상황·성공/실패는
GET status 를 폴링해서 읽는다.

★★ [2026-07-22 코드리뷰 수정 #2] 실행 상태를 DB 테이블(MarketCategoryHarvestRun)로 옮겼다.
라이브 배포는 gunicorn `--workers 3`(OS 프로세스 3개)이라, 이전의 모듈 레벨
dict+threading.Lock 은 프로세스 로컬이었다 — ①같은 마켓 중복실행 방지(409)가 요청이
다른 워커로 가면 무효였고 ②GET status 폴링이 harvest 를 돌린 워커가 아닌 다른 워커에
떨어지면 running=False·낡은 결과로 보였다(결과 증발처럼 보이는 버그 재현 가능). 어느
워커가 요청을 받아도 같은 DB 행을 보게 만들어 이 문제를 없앤다.

advisory lock(webapp/routes/api.py 의 `pg_advisory_xact_lock` 참조)은 여기 안 쓴다 — 그건
트랜잭션 수명(커밋/롤백까지)만 유효한데, harvest 는 수 분짜리 백그라운드 스레드라 그렇게
오래 트랜잭션을 열어 둘 수 없다. 대신 실행 상태 행 자체를 `with_for_update()` 로 원자적
클레임한다(SQLite 는 `with_for_update()` 를 조용히 무시하지만 개발·테스트는 단일 프로세스라
무해 — Postgres 라이브에서만 실제 잠금이 걸린다).

스테일 30분 회수: `running=True` 인데 `started_at` 이 30분을 넘겼으면 죽은 실행으로 보고
새 POST 가 이를 회수해 다시 시작한다. 데몬 스레드는 워커가 재시작(배포·크래시)되면 자기
상태를 정리할 새 없이 함께 죽어 running=True 로 영원히 남을 수 있기 때문이다.
"""
from __future__ import annotations

import datetime
import inspect
import json
import threading
import time

from flask import jsonify, request
from sqlalchemy.exc import IntegrityError

from shared.db import SessionLocal
from lemouton.registration import category_harvest as ch
from lemouton.registration.models import MarketCategory, MarketCategoryHarvestRun
from . import bp

MARKETS = ('smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon')

# 죽은(스테일) 실행 회수 기준 — 이보다 오래 running=True 인 행은 새 POST 가 되찾아 간다.
# [2026-07-22 라이브 실측] 쿠팡 BFS(노드당 1콜)는 100분 넘게 정상 진행 — 30분이면
# 살아있는 실행을 뺏어 이중 수집이 나므로 쿠팡만 3시간으로 늘린다.
STALE_AFTER = datetime.timedelta(minutes=30)
STALE_AFTER_BY_MARKET = {'coupang': datetime.timedelta(hours=3)}


def _first_env_prefix(session, market):
    from lemouton.sourcing.models_v2 import UploadAccount
    acct = (session.query(UploadAccount)
            .filter_by(market=market, is_active=True).order_by(UploadAccount.id).first())
    if acct is None:
        raise ch.HarvestError(f'{market}: 활성 계정이 없음 — 판매처 계정 관리에서 먼저 등록')
    return acct.env_prefix


def _run_harvest(market, on_progress=None):
    """마켓별 실호출 → 행 리스트. (테스트에서 monkeypatch 되는 경계)

    on_progress — 선택. 수 분~수 시간 걸리는 마켓(쿠팡·옥션·G마켓·롯데온)에만 전달된다.
    11번가·스마트스토어는 단발 호출이라 진행률 콜백이 의미 없어 그냥 무시된다.
    """
    import lemouton.uploader.market_fetch as MF
    s = SessionLocal()
    try:
        if market == 'eleven11':
            client = MF._eleven11_client(_first_env_prefix(s, market))
            xml = client.request('GET', '/rest/cateservice/category')
            return ch.parse_eleven11(xml)
        if market == 'smartstore':
            client = MF._smartstore_client(_first_env_prefix(s, market))
            # [2026-07-22 라이브 실측] 문서 표기 '/v1/categories' 는 404 — 실서버는
            # 다른 스스 API 처럼 /external 프리픽스 필요.
            payload = client.request('GET', '/external/v1/categories')
            return ch.parse_smartstore(payload)
        if market == 'coupang':
            client = MF._coupang_client(_first_env_prefix(s, market))
            base = '/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/'
            def fetch(code):
                res = client.request('GET', base + code)
                return (res or {}).get('data') or {}
            return ch.harvest_coupang(fetch, sleep=time.sleep, on_progress=on_progress)
        if market in ('auction', 'gmarket'):
            client = MF._esm_client(market, _first_env_prefix(s, market))
            def fetch(code):
                path = '/item/v1/categories/site-cats' + (f'/{code}' if code else '')
                return client.request('GET', path)
            return ch.harvest_esm_site(fetch, sleep=time.sleep, on_progress=on_progress)
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
                # [2026-07-22 라이브 실측] 응답 최상위는 'data' 배열이 아니라
                # {"itemList":[{"data":{std_cat_id..}, ...}, ...]} — 항목마다 data 객체가 들어있다.
                body = r.json() or {}
                rows = [(it.get('data') or {}) for it in (body.get('itemList') or [])]
                if not rows and skip == 0:
                    # 200 인데 비면 응답 원문을 보여야 원인을 안다(조용한 0건 금지)
                    raise ch.HarvestError('롯데온 표준카테고리 200이지만 itemList 비어있음 — 응답 원문: ' + r.text[:300])
                return rows
            return ch.harvest_lotteon(fetch, sleep=time.sleep, on_progress=on_progress)
        raise ch.HarvestError(f'모르는 마켓: {market}')
    finally:
        s.close()


def _claim_run(session, market):
    """실행 상태 행을 원자적으로 클레임한다.

    이미 running=True 이고 started_at 이 30분 이내면 클레임 실패(False) — 진짜 진행 중.
    그 외(행 없음/미실행/30분 넘은 스테일)면 running=True·started_at=now·error=None 으로
    갱신하고 커밋 후 True. summary_json 은 일부러 건드리지 않는다 — 실행 중·실패 후에도
    "직전 성공" 요약이 화면에 남아 결과를 잃지 않게 하기 위해서다(_finish_error 도 동일).
    """
    now = datetime.datetime.utcnow()
    row = (session.query(MarketCategoryHarvestRun)
           .filter_by(market=market)
           .with_for_update()
           .first())
    if row is None:
        row = MarketCategoryHarvestRun(market=market, running=False)
        session.add(row)
        try:
            session.flush()
        except IntegrityError:
            # 동시에 다른 트랜잭션이 먼저 행을 만든 레이스 — 방금 생긴 행을 다시 잠가서 읽는다.
            session.rollback()
            row = (session.query(MarketCategoryHarvestRun)
                   .filter_by(market=market)
                   .with_for_update()
                   .first())
            if row is None:
                # 이론상 도달 불가(경합 승자 커밋 전제)지만, None 이면 500 대신 클레임 실패로.
                return False
    stale_after = STALE_AFTER_BY_MARKET.get(market, STALE_AFTER)
    if row.running and row.started_at and (now - row.started_at) < stale_after:
        session.rollback()
        return False
    row.running = True
    row.started_at = now
    row.finished_at = None
    row.error = None
    session.commit()
    return True


def _finish_success(market, summary):
    s = SessionLocal()
    try:
        row = s.query(MarketCategoryHarvestRun).filter_by(market=market).first()
        if row is None:
            row = MarketCategoryHarvestRun(market=market)
            s.add(row)
        row.running = False
        row.finished_at = datetime.datetime.utcnow()
        row.summary_json = json.dumps(summary)
        row.error = None
        s.commit()
    finally:
        s.close()


def _finish_error(market, error_text):
    s = SessionLocal()
    try:
        row = s.query(MarketCategoryHarvestRun).filter_by(market=market).first()
        if row is None:
            row = MarketCategoryHarvestRun(market=market)
            s.add(row)
        row.running = False
        row.finished_at = datetime.datetime.utcnow()
        row.error = error_text
        # summary_json 은 건드리지 않는다 — 직전 성공 결과가 있으면 화면에 계속 보인다.
        s.commit()
    finally:
        s.close()


PROGRESS_THROTTLE_SECONDS = 20  # 노드마다 UPDATE 하면 쿠팡 BFS 에서 DB 를 초당 5번 두드린다.


def _make_progress_writer(market):
    """20초 스로틀 진행률 기록 콜백 — 실측 필요성: 쿠팡이 수 시간 걸리는데 "돌고 있는지
    멈췄는지" 구분이 안 된다. progress_count/progress_at 을 별도 세션으로 갱신한다.

    기록 실패(DB 일시 장애 등)는 삼키되 조용히 넘기지 않는다 — 로그 한 줄만 남기고
    수집 자체는 계속 진행한다(진행률 기록이 수집을 죽이면 원래 목적보다 손해가 크다).
    """
    state = {'last_write': 0.0}

    def on_progress(count):
        now = time.monotonic()
        if now - state['last_write'] < PROGRESS_THROTTLE_SECONDS:
            return
        state['last_write'] = now
        s = SessionLocal()
        try:
            row = s.query(MarketCategoryHarvestRun).filter_by(market=market).first()
            if row is None:
                row = MarketCategoryHarvestRun(market=market)
                s.add(row)
            row.progress_count = count
            row.progress_at = datetime.datetime.utcnow()
            s.commit()
        except Exception as e:  # noqa: BLE001 — 진행률 기록 실패가 수집 자체를 죽이면 안 된다.
            s.rollback()
            print(f'[category_harvest] {market}: 진행률 기록 실패(수집은 계속) — {e!r}')
        finally:
            s.close()

    return on_progress


def _harvest_and_save(market):
    """백그라운드 스레드 본체 — `_run_harvest` → `save_snapshot`, 결과를 DB 실행 상태 행에 반영.

    실패(HarvestError·저장 시점 IntegrityError·그 밖의 예상 밖 예외)는 전부 사유 원문을
    `error` 컬럼에 남긴다 — 삼키지 않는다. 단 예상 밖 예외의 `repr(e)` 는 길이가 예측 불가라
    500자로 절단한다(HarvestError·IntegrityError 메시지는 이미 짧게 조립돼 원문 그대로).
    성공 시에는 `summary_json` 을 채우고 `error` 는 None 으로 되돌린다(직전 실패가 이번
    성공 뒤에도 남아 있으면 화면이 거짓 실패를 계속 보여준다).
    """
    s = SessionLocal()
    try:
        # 테스트가 `_run_harvest` 를 market 한 인자짜리로 monkeypatch 하는 경우가 있어
        # (기존 카드 202/409/에러 계약 테스트) on_progress 는 실제 시그니처가 받을 때만 넘긴다.
        on_progress = _make_progress_writer(market)
        if 'on_progress' in inspect.signature(_run_harvest).parameters:
            rows = _run_harvest(market, on_progress=on_progress)
        else:
            rows = _run_harvest(market)
        summary = ch.save_snapshot(s, market, rows, now=datetime.datetime.utcnow())
        _finish_success(market, summary)
    except ch.HarvestError as e:
        s.rollback()
        _finish_error(market, str(e))
    except IntegrityError as e:
        # save_snapshot 이 배치 내 중복은 미리 걸러내지만, 이 가드를 뚫고 동시 저장이
        # 붙는 경우(레이스)까지 대비한다 — 500 으로 죽지 않고 사유를 상태로 번역한다.
        s.rollback()
        _finish_error(market, f'{market}: 저장 충돌(IntegrityError) — {e}')
    except Exception as e:  # noqa: BLE001 — 예상 밖 예외도 삼키지 않고 원문을 상태에 남긴다.
        s.rollback()
        _finish_error(market, f'{market}: 예상 밖 오류 — {e!r}'[:500])
    finally:
        s.close()


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

    "이미 진행 중" 판정은 DB 실행 상태 행(어느 gunicorn 워커가 받아도 공유)의 원자적
    클레임(`_claim_run`)으로 한다 — 30분 넘게 running=True 인 스테일 행은 새 요청이 회수한다.
    """
    if market not in MARKETS:
        return jsonify({'ok': False, 'error': f'모르는 마켓: {market}'}), 400
    s = SessionLocal()
    try:
        claimed = _claim_run(s, market)
    finally:
        s.close()
    if not claimed:
        return jsonify({'ok': False, 'error': f'{market}: 이미 수집이 진행 중입니다'}), 409
    t = threading.Thread(target=_harvest_and_save, args=(market,), daemon=True)
    t.start()
    return jsonify({'ok': True, 'started': True, 'market': market}), 202


@bp.get('/api/categories/esm-probe')
def esm_probe():
    """M2 실측용 임시 — extra_code 전략 확정 후 제거 예정 (플랜 Task 8 Step 1).

    ESM(옥션·G마켓) 등록 카테고리는 'sd코드/site코드' 짝이 필요한데, site-cats 목록
    응답엔 sd 코드가 없다는 게 이미 확인돼 있다(사전 지식 7). 이 라우트는 리프
    site-cat 코드 1건을 넣으면 ①`site-cats/{code}` 개별 조회 ②`sd-cats/{code}` 조회
    두 응답을 **원문 그대로** 돌려준다 — sd 코드가 어느 쪽에 실려 오는지 실측하기 위함
    (추측 금지: 실측 전엔 전략을 확정하지 않는다). 실패도 원문 사유를 그대로 노출한다.
    """
    market = (request.args.get('market') or '').strip()
    code = (request.args.get('code') or '').strip()
    if market not in ('auction', 'gmarket'):
        return jsonify({'ok': False, 'error': "market 은 'auction' 또는 'gmarket' 이어야 합니다"}), 400
    if not code:
        return jsonify({'ok': False, 'error': 'code 가 필요합니다'}), 400

    import lemouton.uploader.market_fetch as MF
    s = SessionLocal()
    try:
        env_prefix = _first_env_prefix(s, market)
    except ch.HarvestError as e:
        return jsonify({'ok': False, 'error': str(e)}), 502
    finally:
        s.close()

    try:
        client = MF._esm_client(market, env_prefix)
    except Exception as e:  # noqa: BLE001 — 자격증명 로드 실패도 원문 노출(추측 금지)
        return jsonify({'ok': False, 'error': f'{market}: 클라이언트 생성 실패 — {e}'}), 502

    try:
        site_cats = client.request('GET', f'/item/v1/categories/site-cats/{code}')
    except Exception as e:  # noqa: BLE001 — 실측용 프로브라 실패도 원문 그대로 노출
        return jsonify({'ok': False, 'error': f'site-cats 조회 실패: {e}'}), 502

    try:
        sd_cats = client.request('GET', f'/item/v1/categories/sd-cats/{code}')
    except Exception as e:  # noqa: BLE001
        return jsonify({'ok': False, 'error': f'sd-cats 조회 실패: {e}'}), 502

    return jsonify({'ok': True, 'site_cats': site_cats, 'sd_cats': sd_cats})


@bp.get('/api/categories/status')
def status():
    """마켓별 카테고리 사전 현황 — DB 집계(total/leaves/removed/last_harvested) +
    DB 실행 상태 행(running/last_error/last_summary)을 합쳐서 준다.
    실행 상태를 DB 에서 읽으므로 어느 워커가 요청을 받아도 같은 답을 준다."""
    s = SessionLocal()
    try:
        out = []
        for m in MARKETS:
            q = s.query(MarketCategory).filter_by(market=m)
            alive = q.filter(MarketCategory.removed_at.is_(None))
            last = (q.order_by(MarketCategory.harvested_at.desc()).first())
            run = s.query(MarketCategoryHarvestRun).filter_by(market=m).first()
            running = bool(run.running) if run else False
            last_error = run.error if run else None
            last_summary = (json.loads(run.summary_json)
                             if (run is not None and run.summary_json) else None)
            out.append({
                'market': m,
                'total': alive.count(),
                'leaves': alive.filter(MarketCategory.is_leaf.is_(True)).count(),
                'removed': q.filter(MarketCategory.removed_at.isnot(None)).count(),
                'last_harvested': (last.harvested_at.isoformat(sep=' ') if last else None),
                'running': running,
                'last_error': last_error,
                'last_summary': last_summary,
                # [2026-07-23] 진행률 노출 — 쿠팡처럼 수 시간 걸리는 수집이 "돌고 있는지
                # 멈췄는지" 화면에서 구분되게. progress_at 이 오래 안 움직이면 죽은 실행 의심.
                'progress_count': (run.progress_count if run else None),
                'progress_at': (run.progress_at.isoformat(sep=' ') if (run and run.progress_at) else None),
                'started_at': (run.started_at.isoformat(sep=' ') if (run and run.started_at) else None),
            })
        return jsonify({'ok': True, 'rows': out})
    finally:
        s.close()
