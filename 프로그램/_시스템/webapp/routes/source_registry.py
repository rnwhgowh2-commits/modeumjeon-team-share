"""[v3] 소싱처 사전 (/source-registry) — SourceRegistry CRUD.

기존 /sources (URL 운영센터) 와 분리:
  · /sources         = URL 모니터링 (기존)
  · /source-registry = 소싱처 사전 (이름·메인URL 등록·정렬)
"""
from flask import Blueprint, jsonify, render_template, request

from shared.db import SessionLocal
from lemouton.sourcing.models_pricing import SourceRegistry, OptionSourceUrl

bp = Blueprint('source_registry', __name__)


# ─── 팀공유 모드: admin 전용 (소싱처 등록·삭제 = 운영 영향). 기존 모드 통과. ───
@bp.before_request
def _admin_only():
    import os
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
    """소싱처 사전 페이지."""
    s = SessionLocal()
    try:
        sources = (
            s.query(SourceRegistry)
            .order_by(SourceRegistry.sort_order, SourceRegistry.id)
            .all()
        )
        from sqlalchemy import func
        usage_rows = (
            s.query(OptionSourceUrl.source_id,
                    func.count(OptionSourceUrl.id))
            .group_by(OptionSourceUrl.source_id)
            .all()
        )
        usage = {sid: cnt for sid, cnt in usage_rows}
        items = [{
            'id': src.id,
            'name': src.name,
            'main_url': src.main_url or '',
            'sort_order': src.sort_order,
            'usage_count': usage.get(src.id, 0),
        } for src in sources]
    finally:
        s.close()
    return render_template('source_registry/list.html', active='source_registry',
                           items=items)


@bp.post('/api/source-registry')
def api_create():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    main_url = (data.get('main_url') or '').strip() or None
    if not name:
        return _err('소싱처 이름을 입력하세요.')
    if len(name) > 64:
        return _err('이름은 64자 이내.')
    s = SessionLocal()
    try:
        if s.query(SourceRegistry).filter_by(name=name).first():
            return _err(f"'{name}' 은 이미 등록된 소싱처에요.")
        max_order = s.query(SourceRegistry).count()
        src = SourceRegistry(name=name, main_url=main_url, sort_order=max_order)
        s.add(src)
        s.commit()
        return _ok(id=src.id, name=src.name, main_url=src.main_url or '')
    finally:
        s.close()


@bp.put('/api/source-registry/<int:src_id>')
def api_update(src_id: int):
    data = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        src = s.query(SourceRegistry).filter_by(id=src_id).first()
        if not src:
            return _err('소싱처를 찾을 수 없어요.', 404)
        if 'name' in data:
            new_name = (data['name'] or '').strip()
            if not new_name:
                return _err('이름을 비울 수 없어요.')
            dupe = s.query(SourceRegistry).filter(
                SourceRegistry.name == new_name,
                SourceRegistry.id != src_id,
            ).first()
            if dupe:
                return _err(f"'{new_name}' 은 다른 소싱처가 사용 중이에요.")
            src.name = new_name
        if 'main_url' in data:
            src.main_url = (data['main_url'] or '').strip() or None
        s.commit()
        return _ok(id=src.id, name=src.name, main_url=src.main_url or '')
    finally:
        s.close()


@bp.delete('/api/source-registry/<int:src_id>')
def api_delete(src_id: int):
    """소싱처 삭제 + 옵션×소싱처 매핑 전체 삭제."""
    s = SessionLocal()
    try:
        src = s.query(SourceRegistry).filter_by(id=src_id).first()
        if not src:
            return _err('소싱처를 찾을 수 없어요.', 404)
        usage = s.query(OptionSourceUrl).filter_by(source_id=src_id).count()
        s.query(OptionSourceUrl).filter_by(source_id=src_id).delete()
        s.delete(src)
        s.commit()
        return _ok(deleted_id=src_id, deleted_url_links=usage)
    finally:
        s.close()


@bp.post('/api/source-registry/reorder')
def api_reorder():
    """드래그 정렬 — id 리스트 순서대로 sort_order 일괄 update."""
    data = request.get_json(silent=True) or {}
    ids = data.get('ids') or []
    if not isinstance(ids, list):
        return _err('ids 는 리스트여야 해요.')
    s = SessionLocal()
    try:
        srcs = {x.id: x for x in s.query(SourceRegistry).all()}
        for order, sid in enumerate(ids):
            try:
                sid = int(sid)
            except (ValueError, TypeError):
                continue
            if sid in srcs:
                srcs[sid].sort_order = order
        s.commit()
        return _ok(reordered=len(ids))
    finally:
        s.close()
