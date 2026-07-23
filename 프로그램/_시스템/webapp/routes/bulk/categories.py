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

스테일 10분 회수: `running=True` 인데 `progress_at`(없으면 `started_at`) 이 10분을 넘겼으면
죽은 실행으로 보고 새 POST 가 이를 회수해 다시 시작한다. 데몬 스레드는 워커가 재시작(배포·
크래시)되면 자기 상태를 정리할 새 없이 함께 죽어 running=True 로 영원히 남을 수 있기 때문이다.

★★★ [2026-07-23 실측 사고 대응] 쿠팡 수집이 두 번 연속 완주 실패했다 — 1,534건에서 22분간
progress_count/progress_at 갱신이 멈춘 채(=백그라운드 데몬 스레드 사망) `running=True` 로
남아 있었다. 살아있는 실행은 `_make_progress_writer` 가 20초 스로틀로 `progress_at` 을
계속 갱신하므로 10분이면 "죽었다"고 보기에 충분히 넉넉하다 — 예전에 있던 쿠팡 전용
3시간 특례(`STALE_AFTER_BY_MARKET`)는 진행률 자체가 죽음을 훨씬 빨리·정확히 알려주므로
더는 필요 없어 제거했다. 그리고 완주까지 수 시간 걸리는 쿠팡·ESM 은 이제 200건 단위로
체크포인트 저장(`save_snapshot(..., partial=True)`, `_make_chunk_saver`)이 되므로, 스레드가
죽어도 마지막 청크까지는 DB 에 남는다 — 회수된 재실행은 이미 저장된 코드를 updated 로
흡수하고 새 코드만 added 로 이어 붙인다(전부 유실 → 마지막 청크까지만 유실로 개선).

★★★★ [2026-07-23 실측 사고 대응 #3 — 이어받기] 위 대응 후에도 세 번째로 죽었다. 이번엔
**124건**에서 정지 — 200건 문턱을 한 번도 못 넘겨 첫 청크조차 저장 못 했다(저장 0건).
근본 원인 두 가지를 같이 고쳤다:
①청크를 200 → 50(`CHUNK_SIZE`, `lemouton/registration/category_harvest.py`)으로 줄여 죽기
전에 최소 한 번은 저장될 확률을 높였다.
②그래도 죽으면 "매번 처음부터 BFS" 라 진도가 안 나가던 문제 — `harvest_coupang` 에
`known` 파라미터를 추가해, 이미 DB 에 있고(리프로 확정됐거나 자식까지 저장된) 노드는
fetch 없이 지나가고 그 자식만 큐에 이어 넣는다. `_run_harvest` 의 쿠팡 분기가 시작 전
`market_categories` 를 읽어 `known` 을 구성한다 — 기존 「재수집」 버튼을 다시 누르면
자동으로 이어받기가 된다(새 버튼 없음).

★★★★★ [2026-07-23 자식누락 차단] 위 ②의 "children 이 하나라도 있으면 skip" 판정은
자식이 DB 에 '일부만' 저장된 채 죽은 경우(실제 자식 A,B,C 중 A 만 저장)를 걸러내지
못해 B,C 를 영원히 놓칠 위험이 있었다(사용자는 완료됐다고 믿는데 카테고리가 조용히
빠짐). `market_categories.child_count`(그 노드를 fetch 했을 때 마켓이 알려준 자식 수)를
추가해, `len(children) == child_count` 로 정확히 일치할 때만 skip 하도록 정정했다 —
하나라도 안 맞으면(개수 부족·NULL=옛 데이터) 안전 우선으로 재fetch 한다(`category_harvest.py`
의 `harvest_coupang`/`_build_coupang_known` docstring 참조).
"""
from __future__ import annotations

import datetime
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

# 죽은(스테일) 실행 회수 기준 — 이보다 오래 진행률(progress_at, 없으면 started_at)이
# 안 움직인 running=True 행은 새 POST 가 되찾아 간다. [2026-07-23 실측 사고 대응] 예전엔
# started_at 기준 30분(쿠팡만 3시간 특례)이었으나, 살아있는 실행은 진행률 필드가 20초
# 스로틀로 계속 갱신되므로(_make_progress_writer) 진행률 기준으로 바꾸면 10분이면 충분하고
# 마켓별 특례가 필요 없다 — 쿠팡 전용 3시간 특례는 제거.
STALE_AFTER = datetime.timedelta(minutes=10)


def _first_env_prefix(session, market):
    from lemouton.sourcing.models_v2 import UploadAccount
    acct = (session.query(UploadAccount)
            .filter_by(market=market, is_active=True).order_by(UploadAccount.id).first())
    if acct is None:
        raise ch.HarvestError(f'{market}: 활성 계정이 없음 — 판매처 계정 관리에서 먼저 등록')
    return acct.env_prefix


def _build_coupang_known(session):
    """`market_categories`(coupang, removed_at IS NULL) → `harvest_coupang(known=...)` 형태.

    [2026-07-23 실측 사고 대응 #3 — 이어받기] 매번 처음부터 BFS 하면 죽은 지점까지 다시
    걷느라 진도가 안 나간다. parent_code 관계로 "이 노드의 자식이 DB 에 몇 개 있는가"를
    판정해 known[code]['children'] 에 채운다 — `harvest_coupang` 은 is_leaf=True 이거나
    len(children) == child_count(그 노드가 fetch 됐을 때 마켓이 알려준 자식 수와 정확히
    일치)인 노드만 fetch 를 건너뛴다(자세한 안전 조건은 `category_harvest.harvest_coupang`
    docstring 참조 — [2026-07-23 자식누락 차단] 자식이 일부만 저장된 채 죽은 경계 케이스를
    "children 이 하나라도 있으면 skip" 으로 잘못 넘기지 않기 위한 정정). 빈 테이블(첫 수집)
    이면 빈 dict 를 돌려줘 기존 전체 탐색과 동일하다.
    """
    rows = (session.query(MarketCategory)
            .filter_by(market='coupang', removed_at=None).all())
    children_by_parent = {}
    for r in rows:
        if r.parent_code:
            children_by_parent.setdefault(r.parent_code, []).append(r.code)
    known = {}
    for r in rows:
        known[r.code] = {
            'is_leaf': bool(r.is_leaf),
            'name': r.name,
            'raw': r.raw_json or '{}',
            'children': children_by_parent.get(r.code, []),
            # [2026-07-23 자식누락 차단] NULL=모름(옛 데이터) — harvest_coupang 이 이걸로
            # "children 을 전부 확보했는지"를 판정한다(models.MarketCategory.child_count 주석 참조).
            'child_count': r.child_count,
        }
    return known


def _run_harvest(market, on_progress=None, on_chunk=None):
    """마켓별 실호출 → 행 리스트. (테스트에서 monkeypatch 되는 경계)

    on_progress — 선택. 수 분~수 시간 걸리는 마켓(쿠팡·옥션·G마켓·롯데온)에만 전달된다.
    11번가·스마트스토어는 단발 호출이라 진행률 콜백이 의미 없어 그냥 무시된다.
    on_chunk — 선택. 쿠팡·ESM(옥션·G마켓)에만 전달된다(체크포인트 저장, `_make_chunk_saver`
    참조). 그 외 마켓은 무시된다 — 11번가·스마트스토어는 단발 호출이라 죽어도 유실이
    한 콜 분량뿐이고, 롯데온은 페이지당 최대 100건이라 완주 시간이 짧아 이번 스코프 밖.

    쿠팡 분기는 시작 전 `_build_coupang_known` 으로 이미 DB 에 있는 가지를 읽어
    `harvest_coupang(known=...)` 로 넘긴다 — [2026-07-23 이어받기] 죽었던 지점까지는
    API 호출 없이 지나가고 미탐색 프런티어부터 이어서 fetch 한다. 「재수집」 버튼을 다시
    누르는 것만으로 이어받기가 된다(별도 UI 없음).
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
            known = _build_coupang_known(s)
            print(f'[category_harvest] coupang: 이미 확보 {len(known)}개, 이어서 시작')
            return ch.harvest_coupang(fetch, sleep=time.sleep, on_progress=on_progress,
                                       on_chunk=on_chunk, known=known)
        if market in ('auction', 'gmarket'):
            client = MF._esm_client(market, _first_env_prefix(s, market))
            def fetch(code):
                path = '/item/v1/categories/site-cats' + (f'/{code}' if code else '')
                return client.request('GET', path)
            return ch.harvest_esm_site(fetch, sleep=time.sleep, on_progress=on_progress, on_chunk=on_chunk)
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

    [2026-07-23 실측 사고 대응] 스테일(죽은 실행) 판정 기준을 `started_at` 에서
    `progress_at`(있으면 그것, 없으면 `started_at`)로 바꿨다 — 살아있는 실행은
    `_make_progress_writer` 가 20초마다 `progress_at` 을 갱신하므로, 이게 멈춰 있다는 건
    started_at 이 오래됐다는 것보다 훨씬 직접적인 "죽었다"의 증거다(오래 걸리는 정상
    수집을 스테일로 오판해 뺏는 사고를 막는다). 이미 running=True 이고 그 기준 시각이
    10분 이내면 클레임 실패(False) — 진짜 진행 중. 그 외(행 없음/미실행/10분 넘은
    스테일/기준 시각 자체가 없음)면 running=True·started_at=now·error=None 으로 갱신하고
    커밋 후 True. summary_json 은 일부러 건드리지 않는다 — 실행 중·실패 후에도
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
    if row.running:
        reference = row.progress_at or row.started_at
        if reference and (now - reference) < STALE_AFTER:
            session.rollback()
            return False
    row.running = True
    row.started_at = now
    row.finished_at = None
    row.error = None
    # [2026-07-23 리뷰 수정 I7] progress_count/progress_at 도 새 실행 시작 시 비운다.
    # 안 비우면 재시작 직후에도 지난 실행의 "3120건째 · 400분 전"이 화면에 남아
    # "지금 이 실행이 얼마나 갔는지"를 보여준다는 진행률 기능의 목적을 정면으로 흐린다.
    row.progress_count = None
    row.progress_at = None
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


def _make_chunk_saver(market):
    """청크(CHUNK_SIZE=50건 단위 — [2026-07-23 실측 사고 대응 #3] 200→50) 체크포인트 저장 콜백.

    쿠팡·ESM 은 노드당 1콜 BFS 라 전량 완주까지 수 시간 걸린다. 종전엔 전량을 메모리에
    쌓았다가 맨 마지막에 한 번만 저장해, 중간에 스레드가 죽으면(워커 재시작·메모리 캡·
    earlyoom) 전부 유실됐다(실측 1: 1,534건에서 22분간 progress_count 정지 = 사망, 복구 후
    total=0. 실측 2: 200건 문턱조차 못 넘기고 124건에서 정지 — 첫 청크 저장 0건). 문턱을 50
    으로 낮춰 죽기 전에 더 자주 저장되게 했다. `harvest_coupang`/`harvest_esm_site` 의
    `on_chunk` 가 50건 늘 때마다 이 콜백을 부르면, 별도 세션으로
    `save_snapshot(..., partial=True)` 를 실행해 그 시점까지 수집한 코드를 바로 DB 에
    반영한다 — 죽어도 마지막 청크까지는 남는다.

    partial=True 라 이 저장은 removed_at 마킹·re_confirm 강등을 하지 않는다(부분 수집일
    뿐이라 "사라졌다"고 판단할 근거가 없다 — save_snapshot 참조). 전량 기준 정리는 완주
    후 `_harvest_and_save` 의 최종 저장(partial=False, 기본값)에서만 수행한다.

    저장 실패는 삼키되(청크 저장이 죽으면 수집 자체를 죽이는 게 원래 목적보다 손해가
    크다 — `_make_progress_writer` 와 동일 원칙) 로그 한 줄만 남기고 수집을 계속한다.
    """
    import datetime as _dt

    def on_chunk(rows_so_far):
        s = SessionLocal()
        try:
            ch.save_snapshot(s, market, rows_so_far, now=_dt.datetime.utcnow(), partial=True)
        except Exception as e:  # noqa: BLE001 — 청크 저장 실패가 수집 자체를 죽이면 안 된다.
            s.rollback()
            print(f'[category_harvest] {market}: 청크 저장 실패(수집은 계속) — {e!r}')
        finally:
            s.close()

    return on_chunk


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
        # [2026-07-23 리뷰 수정 I8] `inspect.signature` 로 콜백 유무를 분기하던 코드는
        # 시그니처가 하나라도 바뀌면 조용히 진행률 기록이 빠지는 퇴화 경로였다 — 항상
        # on_progress 를 넘긴다. 11번가·스마트스토어처럼 단발 호출인 마켓은 콜백을
        # 그냥 무시하므로 안전하다(`_run_harvest` docstring 참조).
        on_progress = _make_progress_writer(market)
        # [2026-07-23 체크포인트] on_chunk 도 항상 넘긴다 — 쿠팡·ESM 외 마켓은
        # `_run_harvest` 가 그냥 무시하므로 안전하다(`_run_harvest` docstring 참조).
        on_chunk = _make_chunk_saver(market)
        rows = _run_harvest(market, on_progress=on_progress, on_chunk=on_chunk)
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
    """TEMP-REMOVE-AFTER-M2T8 — M2 실측용 임시 — extra_code 전략 확정 후 제거 예정 (플랜 Task 8 Step 1).

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
