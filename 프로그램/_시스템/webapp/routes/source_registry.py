# -*- coding: utf-8 -*-
"""[v4 2026-06-30 단일명부] 소싱처 사전 (/source-registry) — 명부(SourcingSource) 관리 지점.

이전엔 SourceRegistry(별도 명부)를 CRUD 했으나, 단일 명부 통합으로 **roster(SourcingSource)**
를 관리한다. source_key=불변 정체 / label=수정 껍데기 / 로고=URL→favicon 자동.
빌트인은 삭제 불가(숨김만). 모든 화면이 이 명부에서 이름·로고를 읽는다.
"""
import os
import re

from flask import Blueprint, jsonify, render_template, request

from lemouton.sourcing import roster
from lemouton.sourcing import source_registry as sr

bp = Blueprint('source_registry', __name__)


# ─── 팀공유 모드: admin 전용 (소싱처 등록·삭제 = 운영 영향). 기존 모드 통과. ───
@bp.before_request
def _admin_only():
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


def _err(msg: str, code: int = 400):
    return jsonify(ok=False, error=msg), code


def _ok(**kw):
    return jsonify(ok=True, **kw)


@bp.get('/source-registry')
def page_list():
    """소싱처 사전 = 단일 명부 관리. 빌트인+커스텀, 숨김 포함."""
    items = roster.list_all()
    usage = roster.usage_by_key()
    for it in items:
        it['usage_count'] = usage.get(it['key'], 0)
        it['main_url'] = (('https://' + it['domain']) if it['domain'] else '')
    return render_template('source_registry/list.html', active='source_registry',
                           items=items)


@bp.post('/api/source-registry')
def api_create():
    """신규 소싱처 — 이름 + URL. URL 도메인에서 source_key·favicon 자동 도출."""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    main_url = (data.get('main_url') or '').strip()
    if not name:
        return _err('소싱처 이름을 입력하세요.')
    if len(name) > 64:
        return _err('이름은 64자 이내.')
    domain = sr.domain_of(main_url) if main_url else ''
    if not domain:
        return _err('소싱처 URL(주소)을 입력하세요 — 로고를 자동으로 가져옵니다.')
    # 이미 그 도메인의 소싱처가 있으면 중복 방지(존재검사)
    for x in roster.list_all():
        if x['domain'] and x['domain'].lower() == domain.lower():
            return _err(f"같은 도메인이 이미 '{x['label']}' 로 등록돼 있어요.")
    base = re.sub(r'[^a-z0-9]', '', domain.split('.')[0].lower()) or 'src'
    existing = {x['key'] for x in roster.list_all()}
    key, i = base, 2
    while key in existing:
        key, i = f"{base}{i}", i + 1
    try:
        roster.add(key, name, domain, favicon_url=f"https://{domain}/favicon.ico")
    except ValueError as e:
        return _err(str(e))
    return _ok(key=key, name=name)


@bp.put('/api/source-registry/<key>')
def api_update(key):
    """이름변경(label) / 로고·도메인(URL) / 숨김(is_active)."""
    data = request.get_json(silent=True) or {}
    try:
        if 'name' in data:
            roster.rename(key, data['name'])
        if 'main_url' in data:
            dom = sr.domain_of((data.get('main_url') or '').strip())
            roster.set_logo(key, domain=(dom or None),
                            favicon_url=(f"https://{dom}/favicon.ico" if dom else None))
        if 'is_active' in data:
            roster.set_active(key, bool(data['is_active']))
    except ValueError as e:
        return _err(str(e))
    return _ok(key=key)


@bp.delete('/api/source-registry/<key>')
def api_delete(key):
    """커스텀 + 참조 0 일 때만 삭제. 빌트인은 숨김(PUT is_active=false) 사용."""
    try:
        roster.delete(key)
    except ValueError as e:
        return _err(str(e))
    return _ok(deleted=key)


@bp.post('/api/source-registry/reorder')
def api_reorder():
    """드래그 정렬 — key 리스트 순서대로 sort_order 일괄 update."""
    data = request.get_json(silent=True) or {}
    keys = data.get('keys') or data.get('ids') or []
    if not isinstance(keys, list):
        return _err('keys 는 리스트여야 해요.')
    from shared.db import SessionLocal
    from lemouton.sourcing.models import SourcingSource
    s = SessionLocal()
    try:
        rows = {r.source_key: r for r in s.query(SourcingSource).all()}
        for order, k in enumerate(keys):
            if k in rows:
                rows[k].sort_order = order
        s.commit()
        return _ok(reordered=len(keys))
    finally:
        s.close()
