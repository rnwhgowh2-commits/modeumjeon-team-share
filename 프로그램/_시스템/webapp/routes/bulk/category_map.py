# -*- coding: utf-8 -*-
"""M2 — 맵핑표(category_map) 조회/확정/제안생성 + 브랜드·지재권 제한표 CRUD 라우트.

원칙(스펙 §C·§D):
  · 자동 확정 금지 — confirmed 는 사장님(또는 등록 흐름에서의 명시적 선택)이 confirm 을
    호출해야만 된다. suggest 는 suggested/re_confirm 행만 갱신한다.
  · confirm 은 대상 코드가 로컬 사전(market_categories)에 실재·현존해야 통과한다 —
    사라진(removed) 코드나 애초에 없는 코드를 확정 게이트에 박아 넣으면 다음 등록이
    조용히 실패하거나(마켓이 거부) 틀린 카테고리로 올라간다.
  · 쿠팡 추천 앵커는 활성 계정이 없거나, 자격증명 로드(client 생성)가 실패하거나, predict 가
    예외를 던져도 500 을 내지 않는다(앵커는 있으면 좋은 보조 신호일 뿐 — 이름 유사도만으로도
    제안은 만들어진다).
"""
from __future__ import annotations

import datetime
import json
import threading
import time

from flask import jsonify, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from shared.db import SessionLocal
from lemouton.registration.models import (
    SourceCategory, CategoryMapRow, MarketCategory, BrandRestriction,
    MarketCategoryHarvestRun,
)
from lemouton.registration import category_suggest as cs
from lemouton.registration import observed_map as om
from . import bp

# 쿠팡 추천 앵커 — source 의 리프(source_categories) 개수가 이보다 많으면 콜 수가
# 너무 커진다(리프 수만큼 predict 콜) → 앵커를 생략하고 이름 유사도만 쓴다.
COUPANG_ANCHOR_LEAF_LIMIT = 200


def _err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _find_map_row(session, source, path, market):
    """(source_id, source_path, market) 로 CategoryMapRow 1행 조회 — confirm 의 동시성
    수렴 재조회(아래)가 monkeypatch 로 경계를 잡을 수 있게 별도 함수로 뺐다."""
    return (session.query(CategoryMapRow)
            .filter_by(source_id=source, source_path=path, market=market).first())


# ── 판정(resolve) ───────────────────────────────────────────────────────
@bp.get('/api/catmap/resolve')
def catmap_resolve():
    """등록 흐름이 마켓 호출 전에 묻는 판정 API — confirmed/suggested/none 3분기."""
    source = (request.args.get('source') or '').strip()
    path = (request.args.get('path') or '').strip()
    market = (request.args.get('market') or '').strip()
    if not (source and path and market):
        return _err('source, path, market 이 모두 필요합니다')

    s = SessionLocal()
    try:
        row = (s.query(CategoryMapRow)
               .filter_by(source_id=source, source_path=path, market=market).first())
        if row is None:
            return jsonify({'ok': True, 'status': 'none', 'code': None, 'path': None, 'candidates': []})
        candidates = json.loads(row.candidates_json) if row.candidates_json else []
        # re_confirm 도 사장님 입장에선 "다시 골라야 함" — suggested 와 같은 취급으로 노출한다.
        status = 'confirmed' if row.status == 'confirmed' else 'suggested'
        return jsonify({'ok': True, 'status': status, 'code': row.market_cat_code,
                        'path': row.market_cat_path, 'candidates': candidates})
    finally:
        s.close()


# ── 확정(confirm) ───────────────────────────────────────────────────────
@bp.post('/api/catmap/confirm')
def catmap_confirm():
    """맵핑을 confirmed 로 승격 — 코드가 로컬 사전에 없거나 removed 면 400 거부.

    동시성(리뷰 이월): 같은 (source, path, market) 키로 두 요청이 동시에 "행 없음"을
    보고 각자 INSERT 를 시도하면 UNIQUE(uq_category_map_source_market) 위반으로
    하나가 IntegrityError 를 받는다. `lemouton/margin/keyword_store.py::get_config`
    의 관례를 그대로 이식 — rollback 후 재조회해 그 행을 UPDATE 로 덮어써 수렴시킨다
    (500 대신 정상 confirmed 응답).
    """
    p = request.get_json(silent=True) or {}
    source = (p.get('source') or '').strip()
    path = (p.get('path') or '').strip()
    market = (p.get('market') or '').strip()
    code = str(p.get('code') or '').strip()
    if not (source and path and market and code):
        return _err('source, path, market, code 가 모두 필요합니다')
    # [2026-07-23 리뷰 수정 I3] 롯데온은 카테고리 코드가 아니라 본보기 상품번호(spdNo)를
    # 쓴다 — 카테고리 맵핑 대상이 아니므로 확정 요청 자체를 거부한다(잘못 확정되면
    # 다음 등록이 조용히 틀린 카테고리로 시도된다).
    if market == 'lotteon':
        return _err('롯데온은 카테고리 대신 본보기 상품번호(spdNo)를 씁니다 — 맵핑 대상 아님')

    s = SessionLocal()
    try:
        mc = (s.query(MarketCategory)
              .filter_by(market=market, code=code, removed_at=None).first())
        if mc is None:
            removed = (s.query(MarketCategory)
                       .filter(MarketCategory.market == market, MarketCategory.code == code,
                               MarketCategory.removed_at.isnot(None)).first())
            if removed is not None:
                return _err(f'{market} 카테고리 코드 {code} 는 재수집에서 사라졌습니다(제거됨) — '
                            f'검색으로 다시 골라 주세요')
            return _err(f'{market} 카테고리 사전에 코드 {code} 가 없습니다 — 검색으로 다시 골라 주세요')

        now = _now()
        row = _find_map_row(s, source, path, market)
        if row is None:
            row = CategoryMapRow(source_id=source, source_path=path, market=market,
                                 market_cat_code=code)
            s.add(row)
        row.market_cat_code = code
        row.market_cat_path = mc.full_path
        row.status = 'confirmed'
        row.method = 'manual'
        row.confirmed_at = now
        row.updated_at = now
        try:
            s.commit()
        except IntegrityError:
            # 경합 패자 — 승자가 이미 같은 키로 커밋했다. rollback 후 그 행을 재조회해
            # UPDATE 로 수렴시킨다(재조회에서도 못 찾으면 설명 불가 → 삼키지 않고 재던짐).
            s.rollback()
            row = _find_map_row(s, source, path, market)
            if row is None:
                raise
            row.market_cat_code = code
            row.market_cat_path = mc.full_path
            row.status = 'confirmed'
            row.method = 'manual'
            row.confirmed_at = now
            row.updated_at = now
            s.commit()
        return jsonify({'ok': True, 'row': {
            'source': row.source_id, 'path': row.source_path, 'market': row.market,
            'code': row.market_cat_code, 'market_cat_path': row.market_cat_path,
            'status': row.status,
        }})
    finally:
        s.close()


# ── 삭제(delete) ────────────────────────────────────────────────────────
@bp.delete('/api/catmap/<int:row_id>')
def catmap_delete(row_id):
    """M2 I2 — 잘못 확정한 맵핑의 탈출구. 삭제하면 다음 판정(resolve)은 status='none'
    으로 돌아가 등록 흐름이 다시 검색부터 시작한다(자동 재확정 없음 — 사장님이
    다시 고르거나 재제안(suggest)이 새로 채운다). 없는 행이면 404."""
    s = SessionLocal()
    try:
        row = s.query(CategoryMapRow).filter_by(id=row_id).first()
        if row is None:
            return _err('맵핑 행을 찾을 수 없습니다.', 404)
        s.delete(row)
        s.commit()
        return jsonify({'ok': True})
    finally:
        s.close()


# ── 제안 생성(suggest) ──────────────────────────────────────────────────
def _coupang_predict_adapter(client):
    """generate_suggestions 에 주입할 콜러블 — predict 예외를 삼켜 500 을 막는다.

    실제 래퍼(`shared/platforms/coupang/categories.py::predict`)는 성공 시 int, 실패 시
    None 을 돌려주는 얇은 함수라 — 그 값을 그대로 돌려주면 generate_suggestions 의
    bare-int 분기가 처리한다.
    """
    from shared.platforms.coupang.categories import predict as _predict

    def _adapter(name, brand=None):
        try:
            return _predict(product_name=name, brand=brand, client=client)
        except Exception:  # noqa: BLE001 — 앵커 실패는 유사도 제안으로 폴백, 500 금지
            return None
    return _adapter


@bp.post('/api/catmap/suggest/<source_id>')
def catmap_suggest(source_id):
    """source_categories(source_id) 의 각 경로에 6마켓 제안을 동기 생성한다.

    쿠팡 앵커는 ①활성 쿠팡 계정이 있고 ②이 source 의 리프 수가 상한(200) 이하일 때만
    주입한다. 둘 중 하나라도 아니면 이름 유사도만 쓰고 응답의 coupang_anchor=False 로
    사유를 명시한다(추측·과다호출 방지).
    """
    s = SessionLocal()
    try:
        leaf_count = s.query(SourceCategory).filter_by(source_id=source_id).count()
        if leaf_count == 0:
            return _err(f'{source_id}: 소싱처 카테고리가 없습니다 — 먼저 수집(M3)하거나 '
                        f'경로를 확인하세요', 404)

        coupang_predict = None
        coupang_anchor = False
        anchor_note = None
        if leaf_count > COUPANG_ANCHOR_LEAF_LIMIT:
            anchor_note = f'source 리프 수 {leaf_count}건이 상한({COUPANG_ANCHOR_LEAF_LIMIT})을 넘어 쿠팡 앵커를 생략했습니다 — 이름 유사도만 사용'
        else:
            from lemouton.sourcing.models_v2 import UploadAccount
            acct = (s.query(UploadAccount)
                    .filter_by(market='coupang', is_active=True)
                    .order_by(UploadAccount.id).first())
            if acct is None:
                anchor_note = '활성 쿠팡 계정이 없어 쿠팡 앵커를 생략했습니다 — 이름 유사도만 사용'
            else:
                try:
                    import lemouton.uploader.market_fetch as MF
                    client = MF._coupang_client(acct.env_prefix)
                    coupang_predict = _coupang_predict_adapter(client)
                    coupang_anchor = True
                except Exception:  # noqa: BLE001 — 자격증명 로드 실패도 앵커 생략 폴백, 500 금지
                    coupang_predict = None
                    coupang_anchor = False
                    anchor_note = '쿠팡 계정 인증 정보 로드 실패 — 이름 유사도만 사용'

        result = cs.generate_suggestions(s, source_id, coupang_predict=coupang_predict)
        result['ok'] = True
        result['coupang_anchor'] = coupang_anchor
        if anchor_note:
            result['coupang_anchor_note'] = anchor_note
        return jsonify(result)
    finally:
        s.close()


# ── 등록 실적에서 회수(observe) ─────────────────────────────────────────
# 실행 상태 그릇은 카테고리 수집(harvest)과 같은 테이블을 재사용한다 — 그 테이블의
# primary key 는 '마켓'이지만 실제로 필요한 건 "누가 돌고 있나 / 얼마나 갔나 / 무엇으로
# 끝났나" 뿐이라, 마켓 이름과 겹치지 않는 예약 키 한 행을 쓴다(새 테이블·마이그레이션 없이
# 409 중복실행 방지·워커 3개 공유·진행률·스테일 회수까지 그대로 얻는다).
# `/api/categories/status` 는 MARKETS 만 순회하므로 이 행이 그 화면에 새지 않는다.
OBSERVE_RUN_KEY = '__observe__'

# 마켓별 호출 간 최소 간격(초) — 지도 §1 「업로드 한도(실측)」보다 **느리게** 간다.
#   [2026-07-23 리뷰 I5] 예전 값(ESM 0.35s=2.9콜/s)은 실측보다 4배 빨랐다. 근거:
#     · auction/gmarket : ESM 실 상품경로 실측 = 상품당 순차 **0.68건/s**(=1.47s) ·
#                         동시호출은 400 충돌 → 1.5s (sell-status 67콜/s 는 다른 경로다)
#     · smartstore      : 계정별 실측 ~2.0콜/s(429 72%) → 0.5s
#     · coupang         : 실측 ~9.7콜/s 지만 문서 한도가 게이트웨이 토큰버킷 5req/s → 0.2s
#     · eleven11        : 단독 51.2콜/s 실측은 다른 경로. 이 상품조회 경로는 미측정 → 0.2s
#   ★ 실측을 새로 하기 전에는 이 값을 낮추지 말 것(속도보다 계정 정지가 비싸다).
OBSERVE_SLEEP = {'smartstore': 0.5, 'coupang': 0.2, 'auction': 1.5,
                 'gmarket': 1.5, 'eleven11': 0.2}
OBSERVE_SLEEP_DEFAULT = 1.0     # 미상 마켓은 보수적으로


def _active_env_prefixes(session, market):
    """그 마켓의 **활성 계정 전부**(등록 순). 없으면 빈 리스트."""
    from lemouton.sourcing.models_v2 import UploadAccount
    return [p for (p,) in (session.query(UploadAccount.env_prefix)
                           .filter_by(market=market, is_active=True)
                           .order_by(UploadAccount.id).all())]


def _observe_client(market, env_prefix):
    """마켓·계정별 클라이언트. (테스트가 갈아끼우는 경계)"""
    import lemouton.uploader.market_fetch as MF
    if market == 'smartstore':
        return MF._smartstore_client(env_prefix)
    if market == 'coupang':
        return MF._coupang_client(env_prefix)
    if market in ('auction', 'gmarket'):
        return MF._esm_client(market, env_prefix)
    if market == 'eleven11':
        return MF._eleven11_client(env_prefix)
    raise RuntimeError(f'회수 대상이 아닌 마켓: {market}')


def _observe_call(market, product_id, client):
    """마켓 1회 조회 → 카테고리 코드|None. (테스트가 갈아끼우는 경계)"""
    if market == 'smartstore':
        from shared.platforms.smartstore.get_options import fetch_product_options
        r = fetch_product_options(int(product_id), client=client)
        if not r.success:
            # 실패를 '카테고리 없음'으로 둔갑시키지 않는다 — 사유를 그대로 올린다.
            raise RuntimeError(r.error or '스마트스토어 상품조회 실패')
        return r.leaf_category_id
    if market == 'coupang':
        from shared.platforms.coupang.products import (
            get_product, extract_display_category_code)
        return extract_display_category_code(get_product(int(product_id), client=client))
    if market in ('auction', 'gmarket'):
        from shared.platforms.esm.products import get_goods_detail, extract_category_codes
        detail = get_goods_detail(str(product_id), client=client)
        # 맵핑에 박히는 값은 사이트 카테고리 코드 — 우리 사전(market_categories)의 code 와
        # 같은 축이어야 confirm 게이트를 통과한다(ESM 표준 sd 코드는 extra_code 쪽).
        return extract_category_codes(detail, market)['site_cat_code']
    if market == 'eleven11':
        from shared.platforms.eleven11.products import get_display_category_no
        return get_display_category_no(str(product_id), client=client)
    raise RuntimeError(f'회수 대상이 아닌 마켓: {market}')


def _observe_fetcher(notes):
    """`build_observed_map` 에 주입할 `f(market, product_id) -> 코드|None` 를 만든다.

    [2026-07-23 리뷰 I2] **마켓별 활성 계정을 순차로 시도해 첫 성공을 채택**한다.
      상품 조회는 계정에 매인다(ESM 6계정·쿠팡 vendor). 예전처럼 첫 계정 하나만 쓰면 2번
      계정 상품이 전부 errors 로 뭉개져 원인 판별이 불가능했다. 이 저장소는 '기본 계정
      폴백 금지'를 이미 못 박았다(send_more._env_prefix) — 그래서 **폴백이 아니라 순차 시도**다.
      · 실패 사유에는 어느 계정(env_prefix)인지 반드시 남긴다.
      · 마지막에 성공한 계정을 앞으로 당겨 다음 상품부터 헛콜을 줄인다.
      · 계정이 아예 없으면 그 마켓은 사유를 `notes` 에 한 번만 남기고 이후 호출은 같은
        사유로 예외 — 회수 엔진이 그 상품만 건너뛰고 집계한다(전체 중단·500 금지).
      · 모든 계정이 '코드 없음(None)'이면 예외가 아니라 None = '확인불가'(날조 금지).
    병렬 호출은 하지 않는다 — ESM 실경로는 동시호출이 400 충돌, 스스·쿠팡은 429다.
    """
    clients = {}     # (market, env_prefix) → client | Exception(사유)
    order = {}       # market → [env_prefix...] (마지막 성공이 맨 앞)

    def _prefixes(market):
        if market in order:
            return order[market]
        s = SessionLocal()
        try:
            prefixes = _active_env_prefixes(s, market)
        except Exception as e:   # noqa: BLE001 — 계정 조회 실패도 그 마켓만 사유로
            prefixes = []
            notes.append(f'{market}: 계정 목록 조회 실패 — {e}')
        finally:
            s.close()
        if prefixes:
            notes.append(f'{market}: 활성 계정 {len(prefixes)}개 순차 시도')
        elif not any(n.startswith(f'{market}: 계정 목록') for n in notes):
            notes.append(f'{market}: 활성 계정이 없음 — 판매처 계정 관리에서 먼저 등록')
        order[market] = prefixes
        return prefixes

    def _client(market, env_prefix):
        key = (market, env_prefix)
        if key not in clients:
            try:
                clients[key] = _observe_client(market, env_prefix)
            except Exception as e:   # noqa: BLE001 — 자격증명 로드 실패도 사유만 남기고 계속
                clients[key] = RuntimeError(f'{env_prefix} 자격증명 로드 실패 — {e}')
        return clients[key]

    def _fetch(market, product_id):
        prefixes = _prefixes(market)
        if not prefixes:
            raise RuntimeError(f'{market}: 활성 계정이 없음 — 판매처 계정 관리에서 먼저 등록')
        failures = []
        saw_none = False
        for env_prefix in list(prefixes):
            cli = _client(market, env_prefix)
            if isinstance(cli, Exception):
                failures.append(f'{env_prefix}: {cli}')
                continue
            time.sleep(OBSERVE_SLEEP.get(market, OBSERVE_SLEEP_DEFAULT))
            try:
                code = _observe_call(market, product_id, cli)
            except Exception as e:   # noqa: BLE001 — 계정별 실패는 모아서 함께 올린다
                failures.append(f'{env_prefix}: {e}')
                continue
            if not code:
                # 이 계정 상품이 아닐 수도 있다 — 남은 계정을 더 본다.
                saw_none = True
                continue
            cur = order.get(market) or []
            if cur and cur[0] != env_prefix:
                order[market] = [env_prefix] + [p for p in cur if p != env_prefix]
            return code
        if saw_none:
            return None      # 조회는 됐는데 카테고리가 없다 = 확인불가(추측 금지)
        raise RuntimeError(f'{market} {product_id} — 계정 {len(prefixes)}개 전부 실패: '
                           + ' | '.join(failures))

    return _fetch


def _observe_and_save():
    """백그라운드 스레드 본체 — 회수·맵핑 후 결과를 실행 상태 행에 남긴다(사유 삼키지 않음)."""
    from .categories import _finish_success, _finish_error, _make_progress_writer

    notes = []
    s = SessionLocal()
    try:
        on_progress = _make_progress_writer(OBSERVE_RUN_KEY)
        summary = om.build_observed_map(s, _observe_fetcher(notes), now=_now(),
                                        on_progress=on_progress)
        if notes:
            # [리뷰 I6] 엔진이 남긴 마켓 사유(사전 비어 있음 등)를 덮어쓰지 않는다 — 합친다.
            summary['market_notes'] = list(summary.get('market_notes') or []) + notes
        _finish_success(OBSERVE_RUN_KEY, summary)
    except Exception as e:  # noqa: BLE001 — 예상 밖 예외도 사유 원문을 상태에 남긴다
        s.rollback()
        _finish_error(OBSERVE_RUN_KEY, f'회수 실패 — {e!r}'[:500])
    finally:
        s.close()


@bp.post('/api/catmap/observe')
def catmap_observe():
    """등록 실적에서 카테고리 회수 시작 — 백그라운드(202/409). 결과는 status 로 읽는다.

    동기 처리 금지: 등록 상품 수백 건 × 마켓별 순차 호출이라 gunicorn `--timeout 60` 에
    걸려 요청도 응답도 증발한다(카테고리 수집 harvest 와 같은 이유·같은 패턴).
    """
    from .categories import _claim_run

    s = SessionLocal()
    try:
        claimed = _claim_run(s, OBSERVE_RUN_KEY)
    finally:
        s.close()
    if not claimed:
        return jsonify({'ok': False, 'error': '이미 회수가 진행 중입니다'}), 409
    threading.Thread(target=_observe_and_save, daemon=True).start()
    return jsonify({'ok': True, 'started': True}), 202


@bp.get('/api/catmap/observe/status')
def catmap_observe_status():
    """회수 실행 상태 — running/진행률/마지막 결과·사유. 어느 워커가 받아도 같은 답(DB 원천)."""
    s = SessionLocal()
    try:
        run = (s.query(MarketCategoryHarvestRun)
               .filter_by(market=OBSERVE_RUN_KEY).first())
        return jsonify({
            'ok': True,
            'running': bool(run.running) if run else False,
            'last_error': run.error if run else None,
            'last_summary': (json.loads(run.summary_json)
                             if (run is not None and run.summary_json) else None),
            'progress_count': (run.progress_count if run else None),
            'progress_at': (run.progress_at.isoformat(sep=' ') if (run and run.progress_at) else None),
            'started_at': (run.started_at.isoformat(sep=' ') if (run and run.started_at) else None),
            'finished_at': (run.finished_at.isoformat(sep=' ') if (run and run.finished_at) else None),
        })
    finally:
        s.close()


# ── 맵핑 현황 집계(status) ──────────────────────────────────────────────
@bp.get('/api/catmap/status')
def catmap_status():
    """소싱처별 suggested/confirmed/re_confirm 집계 — 설정 탭 카드용."""
    s = SessionLocal()
    try:
        counts = (s.query(CategoryMapRow.source_id, CategoryMapRow.status,
                          func.count(CategoryMapRow.id))
                  .group_by(CategoryMapRow.source_id, CategoryMapRow.status).all())
        agg = {}
        for source_id, status, cnt in counts:
            d = agg.setdefault(source_id, {'source_id': source_id, 'suggested': 0,
                                           'confirmed': 0, 're_confirm': 0})
            if status in d:
                d[status] = cnt
        rows = sorted(agg.values(), key=lambda r: r['source_id'])
        return jsonify({'ok': True, 'rows': rows})
    finally:
        s.close()


# ── 브랜드·지재권 제한표 CRUD ───────────────────────────────────────────
def _brand_row(r):
    return {'id': r.id, 'brand': r.brand, 'market': r.market,
            'category_prefix': r.category_prefix or '', 'reason': r.reason,
            'active': bool(r.active)}


@bp.route('/api/brand-limits', methods=['GET', 'POST', 'DELETE'])
def brand_limits():
    s = SessionLocal()
    try:
        if request.method == 'GET':
            rows = s.query(BrandRestriction).order_by(BrandRestriction.id.desc()).all()
            return jsonify({'ok': True, 'rows': [_brand_row(r) for r in rows]})

        if request.method == 'POST':
            p = request.get_json(silent=True) or {}
            brand = (p.get('brand') or '').strip()
            market = (p.get('market') or '').strip()
            reason = (p.get('reason') or '').strip()
            category_prefix = (p.get('category_prefix') or '').strip()
            if not brand:
                return _err('브랜드를 입력해 주세요.')
            allowed_markets = set(cs.MARKETS) | {'*'}
            if market not in allowed_markets:
                return _err(f'market 은 {sorted(allowed_markets)} 중 하나여야 해요.')
            if not reason:
                return _err('사유를 입력해 주세요.')
            # [2026-07-23 리뷰 수정 I4] 같은 (brand, market, category_prefix) 스코프면
            # 새 행을 또 만들지 않고 조회 후 갱신(upsert) — 중복행 방지(uq_brand_restrictions_scope).
            row = (s.query(BrandRestriction)
                   .filter_by(brand=brand, market=market, category_prefix=category_prefix).first())
            if row is None:
                row = BrandRestriction(brand=brand, market=market, category_prefix=category_prefix)
                s.add(row)
            row.reason = reason
            row.active = bool(p.get('active', True))
            s.commit()
            return jsonify({'ok': True, 'row': _brand_row(row)})

        # DELETE
        p = request.get_json(silent=True) or {}
        raw_id = p.get('id') or request.args.get('id')
        if not raw_id:
            return _err('id 가 필요합니다.')
        try:
            rid = int(raw_id)
        except (TypeError, ValueError):
            return _err('id 는 숫자여야 합니다.')
        row = s.query(BrandRestriction).filter_by(id=rid).first()
        if row is None:
            return _err('규칙을 찾을 수 없습니다.', 404)
        s.delete(row)
        s.commit()
        return jsonify({'ok': True})
    finally:
        s.close()
