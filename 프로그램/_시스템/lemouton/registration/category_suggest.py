# -*- coding: utf-8 -*-
"""맵핑 자동 제안 — 이름 유사도(순수함수) + 쿠팡 추천 앵커 오케스트레이션 (스펙 §C).

제안은 제안일 뿐이다: confidence 가 얼마든 자동 확정하지 않는다(정직성 원칙).
"""
from __future__ import annotations

import datetime
import json

# 등록 흐름 전체(bulk_manual.js 카테고리 검색)에서 다루는 6마켓과 동일 순서·코드
# (webapp/routes/bulk/categories.py::MARKETS 와 중복 — lemouton 쪽이 webapp 을
#  import 하면 순환참조가 나서, 6마켓 코드표라는 짧고 안정적인 상수만 복제한다).
MARKETS = ('smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon')


def _tokens(path):
    out = set()
    for part in str(path or '').split('>'):
        part = part.strip()
        if part:
            out.add(part)
    return out


def rank_candidates(source_path, market_leaves, top=3):
    """source_path 의 리프명·경로 토큰으로 market_leaves 후보 상위 top 개.

    점수: 리프명 정확일치 1.0 / 리프명이 후보명에 포함(또는 역포함) 0.7
          / 경로 토큰 겹침 0.4×(겹친 토큰 비율). 0 은 제외.
    """
    parts = [p for p in str(source_path or '').split('>') if p.strip()]
    if not parts:
        return []
    leaf = parts[-1].strip()
    stoks = _tokens(source_path)
    ranked = []
    for cand in market_leaves:
        name = str(cand.get('name') or '').strip()
        score = 0.0
        if name == leaf:
            score = 1.0
        elif leaf and (leaf in name or name in leaf) and name:
            score = 0.7
        else:
            ctoks = _tokens(cand.get('full_path'))
            inter = stoks & ctoks
            if inter:
                score = 0.4 * (len(inter) / max(len(stoks), 1))
        if score > 0:
            ranked.append({'code': cand['code'], 'path': cand.get('full_path'),
                           'name': name, 'score': round(score, 3)})
    ranked.sort(key=lambda r: (-r['score'], r['path'] or ''))
    return ranked[:top]


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def generate_suggestions(session, source_id, coupang_predict=None, now=None):
    """source_categories(source_id) 의 각 경로 × 6마켓으로 category_map 제안을 채운다.

    - status='confirmed' 행은 절대 건드리지 않는다(코드·상태 불변) — skipped_confirmed 로 집계.
    - suggested/re_confirm 행은 후보·1등코드·confidence 를 갱신한다. **status 는 바꾸지 않는다**
      (re_confirm 을 suggested 로 되돌리면 「재확정 필요」 표시가 지워져 조용히 묻힌다).
    - 후보가 0개면 행을 만들지 않는다. 기존 행이 있어도 지우지 않는다(조용한 삭제 금지) —
      그냥 건드리지 않고 넘어간다.
    - 쿠팡은 `coupang_predict(name=리프명, brand=None)` 콜러블(주입식)이 SUCCESS 를 반환하면
      그 카테고리를 1등 후보로 앵커한다(method='coupang_reco', confidence=0.95). 미주입이거나
      FAILURE/INSUFFICIENT_INFORMATION 이면 이름 유사도 후보만 쓴다 — 추측 금지.
      실제 `shared/platforms/coupang/categories.py::predict` 는 성공 시 카테고리ID(int),
      실패 시 None 만 돌려주는 얇은 래퍼라 — 여기서는 그 값이나(정수/문자열),
      더 풍부한 `{'result': 'SUCCESS'|'FAILURE'|'INSUFFICIENT_INFORMATION',
      'predictedCategoryId': ...}` 딕셔너리 어느 쪽을 돌려줘도 인식한다(Task 5 라우트가
      실래퍼를 감싸 어느 모양으로 주입하든 이 함수가 그대로 받게).

    Returns: {'sources': n, 'suggested': n, 'skipped_confirmed': n}
    """
    from lemouton.registration.models import SourceCategory, CategoryMapRow, MarketCategory

    now = now or _utcnow()
    src_rows = (session.query(SourceCategory)
                .filter(SourceCategory.source_id == source_id)
                .all())

    # 마켓별 리프 카테고리를 소스 루프 밖에서 딱 1회씩만 로딩한다(6쿼리, 소스 경로
    # 개수와 무관 — 예전엔 소스경로×마켓마다 재질의해 500경로×6마켓=3000쿼리였다).
    # code_to_path 는 쿠팡 앵커의 경로 조회용 — 매번 leaves 를 선형 스캔(next())하던
    # 것을 여기서 미리 만든 dict 조회 O(1) 로 바꾼다.
    leaves_by_market = {}
    code_to_path = {}
    for market in MARKETS:
        leaves = (session.query(MarketCategory)
                  .filter(MarketCategory.market == market,
                          MarketCategory.is_leaf.is_(True),
                          MarketCategory.removed_at.is_(None))
                  .all())
        leaves_by_market[market] = [{'code': m.code, 'name': m.name, 'full_path': m.full_path}
                                    for m in leaves]
        code_to_path[market] = {str(m.code): m.full_path for m in leaves}

    # 이 source_id 의 기존 category_map 행 전체를 1쿼리로 로딩(소스경로×마켓마다
    # 재질의하던 것 제거). confirmed 게이트를 여기서 먼저 걸어 rank_candidates·
    # coupang_predict 호출까지 건너뛴다(전엔 confirmed 여부와 무관하게 항상 계산했다).
    existing_rows = (session.query(CategoryMapRow)
                      .filter(CategoryMapRow.source_id == source_id)
                      .all())
    existing_map = {(row.source_path, row.market): row for row in existing_rows}

    suggested = 0
    skipped_confirmed = 0

    for src in src_rows:
        for market in MARKETS:
            existing = existing_map.get((src.path, market))

            if existing and existing.status == 'confirmed':
                skipped_confirmed += 1
                continue

            market_leaves = leaves_by_market[market]
            candidates = rank_candidates(src.path, market_leaves, top=3)
            method = 'name_sim' if candidates else None

            if market == 'coupang' and coupang_predict is not None:
                result = coupang_predict(name=src.leaf_name, brand=None)
                pred_code = None
                if isinstance(result, dict):
                    if (result.get('result') == 'SUCCESS'
                            and result.get('predictedCategoryId')):
                        pred_code = str(result['predictedCategoryId'])
                elif result:
                    pred_code = str(result)
                if pred_code:
                    pred_path = code_to_path[market].get(pred_code)
                    if pred_path is not None:
                        coupang_cand = {'code': pred_code, 'path': pred_path,
                                        'name': None, 'score': 0.95}
                        candidates = ([coupang_cand]
                                     + [c for c in candidates if c['code'] != pred_code])[:3]
                        method = 'coupang_reco'
                    # else: 예측 코드가 로컬 사전(market_categories)에 없다 — 확정
                    # 게이트가 400 으로 거부할 코드를 1등 제안으로 주지 않는다.
                    # 앵커를 버리고 이름 유사도 후보만 쓴다(method 는 'name_sim' 유지).

            if not candidates:
                # 후보 0개 — 새로 만들지 않는다. 기존 suggested/re_confirm 행이 있어도
                # 조용히 지우지 않고 그대로 둔다(없음=검색 유도, 삭제=데이터 손실).
                continue

            top = candidates[0]
            candidates_json = json.dumps(candidates, ensure_ascii=False)

            if existing:
                existing.market_cat_code = top['code']
                existing.market_cat_path = top.get('path')
                existing.method = method
                existing.confidence = top['score']
                existing.candidates_json = candidates_json
                existing.updated_at = now
                # status(suggested|re_confirm) 는 의도적으로 건드리지 않는다.
            else:
                session.add(CategoryMapRow(
                    source_id=source_id, source_path=src.path, market=market,
                    market_cat_code=top['code'], market_cat_path=top.get('path'),
                    method=method, confidence=top['score'],
                    candidates_json=candidates_json, updated_at=now,
                ))
            suggested += 1

    session.commit()
    return {'sources': len(src_rows), 'suggested': suggested,
            'skipped_confirmed': skipped_confirmed}
