# -*- coding: utf-8 -*-
"""옵션 주인 이관 — 기준 지문 조회 (읽기 전용).

  GET /api/admin/option-owner/snapshot          전체 지문 + 묶음별 지문
  GET /api/admin/option-owner/snapshot/<code>   한 묶음을 한 줄씩 (달라진 곳 찾을 때)

⚠️ **아무것도 고치지 않는다.** 이관(2단계) 전후로 두 번 불러 대조하는 용도다.
   로컬에서는 라이브 DB 에 붙을 수 없어(.env 없음) 이 창구가 유일한 방법이다.

계산은 lemouton/matrix/owner_snapshot.py 가 단일 원천. 여기는 창구일 뿐이다.
"""
from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify

from shared.db import SessionLocal

_log = logging.getLogger(__name__)

bp = Blueprint('admin_owner_snapshot', __name__,
               url_prefix='/api/admin/option-owner')


@bp.before_request
def _admin_only():
    if os.environ.get('ENVIRONMENT') != 'team-share-dev':
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


@bp.get('/snapshot')
def snapshot():
    from lemouton.matrix.owner_snapshot import collect
    s = SessionLocal()
    try:
        out = collect(s)
    except Exception as e:                              # noqa: BLE001
        _log.exception('[option-owner] 지문 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
    _log.info('[option-owner] 지문 %s · %s', out['overall'], out['counts'])
    return jsonify({'ok': True, **out})


@bp.get('/snapshot/<path:model_code>')
def snapshot_model(model_code: str):
    from lemouton.matrix.owner_snapshot import model_rows
    s = SessionLocal()
    try:
        out = model_rows(s, model_code)
    except Exception as e:                              # noqa: BLE001
        _log.exception('[option-owner] 묶음 상세 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
    if not out['options']:
        return jsonify({'ok': False, 'error': f'그런 묶음이 없습니다: {model_code}'}), 404
    return jsonify({'ok': True, **out})
