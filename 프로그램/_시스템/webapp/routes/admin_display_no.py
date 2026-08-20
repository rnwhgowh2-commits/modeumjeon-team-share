"""표시번호 부여 — 현황 조회 + 소급 부여 실행.

  GET  /api/admin/display-no/status        아직 번호 없는 행 수
  POST /api/admin/display-no/backfill      번호 부여 (기본 500건씩 · all=1 이면 전부)

사장님 확정 (2026-07-30): 기존 것도 전부 소급 부여, 옛날 것도 **현재 날짜 기준**,
순번은 **등록된 순서**대로. 이미 번호가 있는 행은 절대 다시 붙이지 않는다.

규칙은 shared/display_no.py · 부여는 lemouton/sourcing/display_no_assign.py 가 단일 원천.
여기는 창구일 뿐이다.
"""
from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

from shared.db import SessionLocal

_log = logging.getLogger(__name__)

bp = Blueprint('admin_display_no', __name__, url_prefix='/api/admin/display-no')


@bp.before_request
def _admin_only():
    if os.environ.get('ENVIRONMENT') != 'team-share-dev':
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


@bp.get('/status')
def status():
    from lemouton.sourcing.display_no_assign import pending_counts
    s = SessionLocal()
    try:
        left = pending_counts(s)
    finally:
        s.close()
    return jsonify({'ok': True, 'pending': left, 'total_pending': sum(left.values())})


@bp.post('/backfill')
def backfill():
    """한 번 호출에 종류별 limit 건씩. all=1 이면 남은 것이 없을 때까지 반복.

    [주의] 라이브에서 한 번에 다 돌리면 요청이 100초를 넘길 수 있다(CF 상한).
       기본은 500건씩 끊어 돌리고, 남으면 응답의 pending 을 보고 다시 부른다.
    """
    limit = request.args.get('limit', type=int) or 500
    run_all = request.args.get('all') in ('1', 'true', 'yes')
    from lemouton.matrix.service import ensure_all_origins
    from lemouton.sourcing.display_no_assign import assign_missing, pending_counts
    total = {'models': 0, 'source_products': 0, 'source_options': 0,
             'matrix_options': 0, 'skipped': 0}
    rounds = 0
    s = SessionLocal()
    try:
        # [2026-07-30] 브랜드 품번 정리 — 옛 데이터에 '-' 가 값으로 들어가 있어
        #   화면에 「브랜드 품번 -」로 보였다. 사장님 확정은 **없으면 공란**.
        from sqlalchemy import text as _sql
        cleaned = s.execute(_sql(
            "UPDATE models SET article_no = NULL "
            "WHERE article_no IS NOT NULL AND TRIM(article_no) IN ('-', '')")).rowcount or 0
        if cleaned:
            s.commit()
            _log.info('[display-no] 브랜드 품번 «-» %d건 비움', cleaned)

        # 모델마다 원본 매트릭스가 있어야 U 번호를 붙일 수 있다(멱등).
        made = ensure_all_origins(s, limit=None if run_all else limit)
        if made:
            s.commit()
            _log.info('[display-no] 원본 매트릭스 %d개 생성', made)
        while True:
            res = assign_missing(s, limit=limit)
            s.commit()
            rounds += 1
            for k in total:
                total[k] += res[k]
            done = (res['models'] + res['source_products']
                    + res['source_options'] + res['matrix_options'])
            if not run_all or done == 0 or rounds >= 200:
                break
        left = pending_counts(s)
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        _log.exception('[display-no] 소급 부여 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
    _log.info('[display-no] 부여 %s (남은 %s)', total, left)
    return jsonify({'ok': True, 'assigned': total, 'rounds': rounds,
                    'article_no_cleaned': cleaned,
                    'pending': left, 'total_pending': sum(left.values())})
