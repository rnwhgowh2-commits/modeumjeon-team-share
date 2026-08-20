# -*- coding: utf-8 -*-
"""수수료율 13% 맞추기 — 먼저 재고, 그다음 고친다.

  GET  /api/admin/fee/audit    지금 저장된 수수료율 전부 + 13% 로 바꾸면 판매가 배수
  POST /api/admin/fee/apply    가격 정책(PriceTemplate)의 수수료율을 마켓별 기본값으로
                               body: {"confirm": true} 가 없으면 **재보기만** 한다
  POST /api/admin/fee/restore  apply 가 돌려준 「바꾸기 전 값」으로 되돌리기
                               body: {"before": [...]}

[주의] 판매가가 움직이는 일이다. 그래서 순서를 강제한다 — 재기(GET) → 눈으로 → 고치기.
   계산은 `lemouton/pricing/fee_audit.py` 가 단일 원천. 여기는 창구일 뿐이다.
"""
from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

from shared.db import SessionLocal

_log = logging.getLogger(__name__)

bp = Blueprint('admin_fee_audit', __name__, url_prefix='/api/admin/fee')


@bp.before_request
def _admin_only():
    if os.environ.get('ENVIRONMENT') != 'team-share-dev':
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


@bp.get('/audit')
def fee_audit():
    """읽기 전용 — 아무것도 고치지 않는다."""
    from lemouton.pricing.fee_audit import audit
    s = SessionLocal()
    try:
        return jsonify(audit(s))
    finally:
        s.close()


@bp.post('/apply')
def fee_apply():
    """수수료율을 마켓별 기본값으로. `{"confirm": true}` 가 없으면 재보기만 한다."""
    from lemouton.pricing.fee_audit import apply_defaults
    confirm = bool((request.get_json(silent=True) or {}).get('confirm'))
    s = SessionLocal()
    try:
        out = apply_defaults(s, dry_run=not confirm)
        if confirm:
            s.commit()
            _log.warning('[fee] 수수료율 마켓별 기본값 적용 — %s칸', out['changed'])
        else:
            s.rollback()
        out['hint'] = ('되돌리려면 이 응답의 before 를 그대로 /api/admin/fee/restore 로'
                       if confirm else
                       '아직 안 고쳤습니다 — {"confirm": true} 를 보내면 고칩니다')
        return jsonify(out)
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        _log.exception('수수료율 적용 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()


@bp.post('/restore')
def fee_restore():
    """apply 가 돌려준 before 목록으로 되돌린다."""
    from lemouton.pricing.fee_audit import restore
    before = (request.get_json(silent=True) or {}).get('before') or []
    if not before:
        return jsonify({'ok': False, 'error': 'before 가 비어 있습니다'}), 400
    s = SessionLocal()
    try:
        out = restore(s, before)
        s.commit()
        _log.warning('[fee] 수수료율 되돌림 — %s칸', out['restored'])
        return jsonify(out)
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        _log.exception('수수료율 되돌리기 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
