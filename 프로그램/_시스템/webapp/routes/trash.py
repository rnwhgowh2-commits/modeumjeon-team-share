"""[v2] 휴지통 + 변경 이력 페이지 — `/trash`, `/audit`."""
from flask import Blueprint, render_template, jsonify, request, abort
from datetime import datetime, timezone

from shared.db import SessionLocal
from lemouton.audit.models import AuditLog
from lemouton.audit.service import history, recent_activity, restore as audit_restore


bp = Blueprint('trash', __name__)


# ─── 팀공유 모드: admin 전용 (휴지통 영구삭제 = 복구 불가). 기존 모드 통과. ───
@bp.before_request
def _admin_only():
    import os
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


TABLE_LABELS = {
    'models': '모음전',
    'options': '옵션',
    'combo_sets': '콤보 조합',
    'price_templates': '가격 템플릿',
    'color_templates': '색상 템플릿',
    'size_templates': '사이즈 템플릿',
    'market_accounts': '마켓 계정',
    'source_products': '소싱처 URL',
    'source_options': '소싱처 옵션',
}


@bp.route('/trash')
def trash_index():
    """soft-delete 된 항목 목록 — 최근 100개 (action='delete')."""
    s = SessionLocal()
    try:
        rows = (s.query(AuditLog)
                .filter_by(action='delete')
                .order_by(AuditLog.at.desc())
                .limit(100).all())
        # 같은 (target_table, target_id) 가 다시 restore 됐으면 휴지통에서 제외
        restored = set()
        for r in (s.query(AuditLog).filter_by(action='restore').all()):
            restored.add((r.target_table, r.target_id))
        items = []
        for r in rows:
            if (r.target_table, r.target_id) in restored:
                continue
            items.append({
                'log_id': r.id,
                'target_table': r.target_table,
                'target_label': TABLE_LABELS.get(r.target_table, r.target_table),
                'target_id': r.target_id,
                'actor': r.actor,
                'at': r.at,
                'reason': r.reason,
            })
    finally:
        s.close()
    return render_template('trash/index.html', active='trash', items=items)


@bp.post('/trash/<int:log_id>/restore')
def trash_restore(log_id: int):
    """soft-delete 복원 — target_table 별 분기."""
    s = SessionLocal()
    try:
        log = s.get(AuditLog, log_id)
        if log is None or log.action != 'delete':
            return jsonify({'ok': False, 'error': '로그 없음'}), 404
        # 모델 매핑
        tbl_to_model = {
            'market_accounts': 'lemouton.multitenancy.models.MarketAccount',
            'source_products': 'lemouton.sources.models.SourceProduct',
            'source_options': 'lemouton.sources.models.SourceOption',
        }
        path = tbl_to_model.get(log.target_table)
        if path is None:
            return jsonify({'ok': False,
                            'error': f'{log.target_table} 복원 미지원'}), 400
        mod_path, cls_name = path.rsplit('.', 1)
        import importlib
        mod = importlib.import_module(mod_path)
        Cls = getattr(mod, cls_name)
        try:
            obj = s.get(Cls, int(log.target_id))
        except (ValueError, TypeError):
            obj = s.get(Cls, log.target_id)
        if obj is None:
            return jsonify({'ok': False, 'error': '대상 행 없음'}), 404
        audit_restore(s, obj, actor='web_user', reason='휴지통에서 복구')
        s.commit()
        return jsonify({'ok': True, 'restored_id': log.target_id})
    finally:
        s.close()


@bp.route('/audit')
def audit_index():
    """전체 변경 이력 (최근 200건)."""
    s = SessionLocal()
    try:
        target_table = request.args.get('table')
        target_id = request.args.get('id')
        if target_table or target_id:
            rows = history(s, target_table=target_table, target_id=target_id, limit=200)
        else:
            rows = recent_activity(s, limit=200)
        items = [{
            'id': r.id, 'actor': r.actor,
            'target_table': r.target_table,
            'target_label': TABLE_LABELS.get(r.target_table, r.target_table),
            'target_id': r.target_id,
            'action': r.action, 'at': r.at, 'reason': r.reason,
            'before_json': r.before_json, 'after_json': r.after_json,
        } for r in rows]
    finally:
        s.close()
    return render_template('trash/audit.html', active='trash', items=items,
                           filter_table=request.args.get('table'),
                           filter_id=request.args.get('id'))
