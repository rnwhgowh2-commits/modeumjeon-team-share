"""[E] T12 — 박스히어로 webhook 라우트.

Bearer/secret 검증 → 변동 SKU 추출 → 부분 사이클 트리거.
"""
from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

bp = Blueprint('webhook', __name__)


@bp.post('/webhook/boxhero')
def boxhero_webhook():
    expected = os.environ.get('BOXHERO_WEBHOOK_SECRET', '')
    received = request.headers.get('X-Webhook-Secret', '')
    if not expected or received != expected:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    # 박스히어로 webhook 페이로드 형식은 SKU 변동 리스트 가정
    changed = payload.get('changed_skus') or []
    if not isinstance(changed, list):
        return jsonify({'ok': False, 'error': 'changed_skus must be a list'}), 400

    from scheduler.jobs import boxhero_partial_cycle
    result = boxhero_partial_cycle(changed_skus=changed)
    return jsonify({'ok': bool(result.get('ok', True)), 'result': result})


@bp.post('/webhook/source-stage')
def source_stage_webhook():
    """CLAUDE 단계 진행상태 찍기(옵션1, CLAUDE→프로그램 소통).

    add-source 스킬이 단계(S1~S6/U1~U4)마다 호출 → 카드에 진행 표시.
    로그인 면제(/webhook/) + 토큰 인증이라 CLAUDE 가 라이브에 직접 찍을 수 있다.
    토큰(MOUM_STAGE_TOKEN) 미설정이면 기능 비활성(503) — 나머지는 영향 없음(graceful).
    body: {source_id, kind('new'|'update'), stage('S3' 등 | null), note?, complete?}
    """
    expected = os.environ.get('MOUM_STAGE_TOKEN', '')
    if not expected:
        return jsonify({'ok': False, 'error': 'stage progress disabled (no token)'}), 503
    if request.headers.get('X-Webhook-Secret', '') != expected:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401

    body = request.get_json(silent=True) or {}
    try:
        sid = int(body.get('source_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'source_id required'}), 400
    kind = 'update' if body.get('kind') == 'update' else 'new'
    stage = body.get('stage')
    complete = bool(body.get('complete'))
    note = str(body.get('note', ''))

    from datetime import datetime, timezone
    from shared.db import SessionLocal
    from lemouton.sourcing.models_pricing import SourceRegistry
    from lemouton.sourcing import crawl_guide as cg
    s = SessionLocal()
    try:
        src = s.query(SourceRegistry).get(sid)
        if not src:
            return jsonify({'ok': False, 'error': 'source not found'}), 404
        guide = cg.loads(src.crawl_guide)
        guide = cg.advance_stage(guide, kind, stage, note=note,
                                 updated_at=datetime.now(timezone.utc).isoformat(),
                                 complete=complete)
        src.crawl_guide = cg.dumps(guide)
        s.commit()
        return jsonify({'ok': True, 'stage_progress': guide['stage_progress']})
    finally:
        s.close()
