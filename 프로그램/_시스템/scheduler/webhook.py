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
