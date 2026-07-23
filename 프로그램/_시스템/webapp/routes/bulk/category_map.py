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

from flask import jsonify, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from shared.db import SessionLocal
from lemouton.registration.models import (
    SourceCategory, CategoryMapRow, MarketCategory, BrandRestriction,
)
from lemouton.registration import category_suggest as cs
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
            if not brand:
                return _err('브랜드를 입력해 주세요.')
            allowed_markets = set(cs.MARKETS) | {'*'}
            if market not in allowed_markets:
                return _err(f'market 은 {sorted(allowed_markets)} 중 하나여야 해요.')
            if not reason:
                return _err('사유를 입력해 주세요.')
            row = BrandRestriction(
                brand=brand, market=market,
                category_prefix=(p.get('category_prefix') or '').strip(),
                reason=reason, active=bool(p.get('active', True)))
            s.add(row)
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
