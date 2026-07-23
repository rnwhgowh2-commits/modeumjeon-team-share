# -*- coding: utf-8 -*-
"""⚙️ 설정 — 「📋 고시정보 기본값」 카드 라우트 (M4 Task 3).

스마트스토어 고시 13~14칸은 크롤로 안 나오는 값이라 지금까지 드래프트마다 손으로
채워야 했다. 여기서 스코프(전역/소싱처) × 고시유형별로 한 번 저장해 두면, 등록·사전
점검이 **컴파일 직전에만** 병합해 쓴다(저장된 드래프트는 그대로 — notice_defaults.py).

폼에 그릴 칸 목록은 notice.py 규격을 **읽어서** 내려준다(하드코딩 금지) —
고시 규격이 바뀌면 화면이 자동으로 따라간다.
"""
# [2026-07-23] M4 Task 3
from flask import jsonify, request

from shared.db import SessionLocal
from lemouton.registration import notice_defaults as ND
from lemouton.registration.notice import NOTICE_TYPES

from . import bp


def _err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


@bp.get('/api/notice-defaults')
def get_notice_defaults():
    """폼 재료 — 칸 목록 + 저장된 값 + 고를 수 있는 스코프.

    query: scope(기본 'global'), notice_type(기본 'WEAR')
    """
    scope = (request.args.get('scope') or ND.GLOBAL_SCOPE).strip()
    notice_type = (request.args.get('notice_type') or 'WEAR').strip()
    s = SessionLocal()
    try:
        try:
            ND.parse_scope(scope)
            nt = ND.check_notice_type(notice_type)
            fields = ND.field_specs(nt)
            values = ND.get_values(s, scope, nt)
        except ND.NoticeDefaultsError as e:
            return _err(str(e))
        return jsonify({
            'ok': True,
            'scope': scope,
            'notice_type': nt,
            'notice_types': list(NOTICE_TYPES),
            'fields': fields,
            'values': values,
            # 전역 값도 함께 준다 — 소싱처 스코프를 볼 때 "이 칸은 전역이 이미 채운다"를
            # 화면에서 그대로 보여주려면 필요하다(같은 값을 소싱처마다 또 넣지 않게).
            'global_values': (ND.get_values(s, ND.GLOBAL_SCOPE, nt)
                              if scope != ND.GLOBAL_SCOPE else None),
            'sources': ND.known_source_ids(s),
        })
    finally:
        s.close()


@bp.post('/api/notice-defaults')
def save_notice_defaults():
    """기본값 저장(upsert). body: {scope, notice_type, values:{키:값}}

    빈 칸은 저장하지 않는다 = 그 칸 기본값 해제(빈 문자열을 남기면 「설정했는데 빈 값」과
    「설정 안 함」이 구분되지 않는다). 모르는 키는 400 — 오타를 조용히 삼키지 않는다.
    """
    p = request.get_json(silent=True) or {}
    scope = (p.get('scope') or ND.GLOBAL_SCOPE).strip()
    notice_type = (p.get('notice_type') or '').strip()
    values = p.get('values')
    s = SessionLocal()
    try:
        try:
            clean = ND.save_values(s, scope, notice_type, values if values is not None else {})
        except ND.NoticeDefaultsError as e:
            s.rollback()
            return _err(str(e))
        s.commit()
        return jsonify({'ok': True, 'scope': scope,
                        'notice_type': notice_type, 'values': clean})
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return _err(str(e)[:300], 500)
    finally:
        s.close()
