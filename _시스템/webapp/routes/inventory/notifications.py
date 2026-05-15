"""[I] /inventory/notifications — 인앱 알림 + 자동완성 + 첨부파일.

PARITY_720 Tier 1:
  - I-6  알림 벨 (헤더) + 알림 센터 페이지
  - I-11 알림 설정 (settings 통합 — 채널별 on/off)
  - K-7  자동완성 (거래처·SKU)
  - K-11 검색 분석 (no-result 추적)
  - A4-51 첨부파일 업로드 (드래그앤드롭)
"""
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from sqlalchemy import desc, func, or_

from shared.db import SessionLocal
from lemouton.inventory.models import (
    NotificationLog, PurchaseOrder, SalesOrder, ReturnOrder, InventoryTx,
    SearchLog,
)
from lemouton.sourcing.models import Option

from . import bp


def _log_search(s, query, scope, result_count):
    """검색 분석 — PARITY_720 Tier 1 (K-11)."""
    if not query:
        return
    try:
        s.add(SearchLog(
            query=query[:255], scope=scope,
            result_count=result_count,
            no_result=(result_count == 0),
            user_agent=request.headers.get('User-Agent', '')[:255],
        ))
        s.commit()
    except Exception:
        s.rollback()


# ============ 첨부파일 디렉토리 ============
ATTACHMENT_DIR = Path(__file__).resolve().parents[3] / 'data' / 'attachments'
ALLOWED_EXT = {'pdf', 'png', 'jpg', 'jpeg', 'webp', 'xlsx', 'xls',
               'docx', 'doc', 'csv', 'txt'}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB


@bp.post('/api/upload-attachment')
def upload_attachment():
    """드래그앤드롭 업로드 — PARITY_720 Tier 1 (A4-51)."""
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify(error='파일이 없습니다'), 400
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXT:
        return jsonify(error=f'허용되지 않는 형식 (.{ext})'), 400
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_BYTES:
        return jsonify(error='10MB 초과'), 400
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = secrets.token_hex(8) + '.' + ext
    file.save(str(ATTACHMENT_DIR / safe_name))
    return jsonify(
        url=f'/inventory/api/attachment/{safe_name}',
        name=file.filename,
        size=size,
        stored=safe_name,
    )


@bp.get('/api/attachment/<path:filename>')
def get_attachment(filename):
    """첨부파일 다운로드."""
    return send_from_directory(str(ATTACHMENT_DIR), filename)


def _utcnow():
    return datetime.now(timezone.utc)


# ============ 알림 센터 (I-6, I-11) ============

@bp.get('/notifications')
def notifications_view():
    """알림 센터 페이지 — 카테고리·읽음 필터, 일괄 읽음."""
    s = SessionLocal()
    try:
        category = (request.args.get('category') or '').strip()
        unread_only = request.args.get('unread') == '1'
        q = s.query(NotificationLog)
        if category:
            q = q.filter(NotificationLog.category == category)
        if unread_only:
            q = q.filter(NotificationLog.is_read.is_(False))
        items = q.order_by(desc(NotificationLog.created_at)).limit(200).all()
        # 카테고리 카운트 (전체 / 미읽음)
        cat_counts = dict(
            s.query(NotificationLog.category, func.count(NotificationLog.id))
            .group_by(NotificationLog.category).all()
        )
        unread_total = s.query(func.count(NotificationLog.id)).filter(
            NotificationLog.is_read.is_(False)).scalar() or 0
        return render_template(
            'inventory/notifications.html',
            active='notifications', items=items,
            category=category, unread_only=unread_only,
            cat_counts=cat_counts, unread_total=unread_total,
        )
    finally:
        s.close()


@bp.post('/notifications/<int:nid>/read')
def notification_mark_read(nid):
    s = SessionLocal()
    try:
        n = s.query(NotificationLog).filter(NotificationLog.id == nid).first()
        if n and not n.is_read:
            n.is_read = True
            n.read_at = _utcnow()
            s.commit()
        next_url = request.form.get('next') or url_for('inventory.notifications_view')
        return redirect(next_url)
    finally:
        s.close()


@bp.post('/notifications/read-all')
def notification_mark_all_read():
    s = SessionLocal()
    try:
        rows = s.query(NotificationLog).filter(
            NotificationLog.is_read.is_(False)).all()
        for n in rows:
            n.is_read = True
            n.read_at = _utcnow()
        s.commit()
        flash(f'{len(rows)}개 알림 읽음 처리', 'success')
        return redirect(url_for('inventory.notifications_view'))
    finally:
        s.close()


@bp.get('/api/notifications/unread-count')
def notification_unread_count_api():
    """헤더 벨 배지용 JSON — 미읽음 개수."""
    s = SessionLocal()
    try:
        n = s.query(func.count(NotificationLog.id)).filter(
            NotificationLog.is_read.is_(False)).scalar() or 0
        return jsonify(unread=n)
    finally:
        s.close()


@bp.get('/api/notifications/recent')
def notification_recent_api():
    """헤더 벨 드롭다운 — 최근 5개."""
    s = SessionLocal()
    try:
        rows = (s.query(NotificationLog)
                .order_by(desc(NotificationLog.created_at)).limit(5).all())
        return jsonify(items=[{
            'id': n.id, 'category': n.category, 'severity': n.severity,
            'title': n.title, 'body': (n.body or '')[:80],
            'is_read': n.is_read,
            'link_url': n.link_url,
            'created_at': n.created_at.strftime('%Y-%m-%d %H:%M') if n.created_at else '',
        } for n in rows])
    finally:
        s.close()


# ============ 자동완성 (K-7) ============

@bp.get('/api/autocomplete/partner')
def autocomplete_partner():
    """거래처 자동완성 — PO/SO/RO/Tx partner_label DISTINCT (다중 키워드 AND)."""
    from shared.search import split_tokens, apply_and_filter
    q = (request.args.get('q') or '').strip()
    if len(q) < 1:
        return jsonify(items=[])
    tokens = split_tokens(q)
    s = SessionLocal()
    try:
        labels = set()
        for model in (PurchaseOrder, SalesOrder, InventoryTx):
            base = (s.query(model.partner_label)
                    .filter(model.partner_label.isnot(None)))
            base = apply_and_filter(base, tokens, model.partner_label)
            rows = base.distinct().limit(20).all()
            for (lbl,) in rows:
                if lbl and lbl.strip():
                    labels.add(lbl.strip())
        result = sorted(labels)[:15]
        _log_search(s, q, 'partner', len(result))
        return jsonify(items=result)
    finally:
        s.close()


@bp.get('/api/autocomplete/sku')
def autocomplete_sku():
    """SKU 자동완성 — Option canonical_sku/boxhero_sku 매칭 (다중 키워드 AND)."""
    from shared.search import split_tokens, apply_and_filter
    q = (request.args.get('q') or '').strip()
    if len(q) < 1:
        return jsonify(items=[])
    tokens = split_tokens(q)
    s = SessionLocal()
    try:
        query = s.query(Option)
        query = apply_and_filter(query, tokens, Option.canonical_sku, Option.boxhero_sku)
        rows = query.order_by(Option.canonical_sku).limit(15).all()
        result = [{
            'sku': o.canonical_sku,
            'color': o.color_display or o.color_code or '',
            'size': o.size_display or o.size_code or '',
            'stock': o.boxhero_stock_total or 0,
        } for o in rows]
        _log_search(s, q, 'sku', len(result))
        return jsonify(items=result)
    finally:
        s.close()
