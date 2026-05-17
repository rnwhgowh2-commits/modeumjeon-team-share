"""[I] /inventory/webhooks + /inventory/alerts — Webhook + Alert 규칙.

PARITY_720 Tier 1:
  - G-3 Webhook in/out (이벤트 구독·송신)
  - N-9 Alert 규칙 (응답시간/에러율/재고 등)
"""
import json
from datetime import datetime, timezone

from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from sqlalchemy import desc

from shared.db import SessionLocal
from lemouton.inventory.models import WebhookEndpoint, AlertRule

from . import bp


# ============ Webhook (G-3) ============

@bp.get('/webhooks')
def webhooks_view():
    s = SessionLocal()
    try:
        items = (s.query(WebhookEndpoint)
                 .order_by(desc(WebhookEndpoint.created_at)).all())
        return render_template('inventory/webhooks.html',
                               active='webhooks', items=items)
    finally:
        s.close()


@bp.post('/webhooks/create')
def webhook_create():
    name = (request.form.get('name') or '').strip()
    url = (request.form.get('url') or '').strip()
    if not name or not url:
        flash('이름·URL 필요', 'error')
        return redirect(url_for('inventory.webhooks_view'))
    events = request.form.getlist('events')
    s = SessionLocal()
    try:
        s.add(WebhookEndpoint(
            name=name, url=url,
            events=json.dumps(events, ensure_ascii=False),
            secret=(request.form.get('secret') or '').strip() or None,
            active=True,
        ))
        s.commit()
        flash(f'webhook "{name}" 등록', 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.webhooks_view'))


@bp.post('/webhooks/<int:wid>/toggle')
def webhook_toggle(wid):
    s = SessionLocal()
    try:
        w = s.query(WebhookEndpoint).filter(WebhookEndpoint.id == wid).first()
        if w:
            w.active = not w.active
            s.commit()
        return redirect(url_for('inventory.webhooks_view'))
    finally:
        s.close()


@bp.post('/webhooks/<int:wid>/delete')
def webhook_delete(wid):
    s = SessionLocal()
    try:
        s.query(WebhookEndpoint).filter(WebhookEndpoint.id == wid).delete()
        s.commit()
        flash('webhook 삭제', 'success')
        return redirect(url_for('inventory.webhooks_view'))
    finally:
        s.close()


def fire_webhook(event_name, payload):
    """이벤트 발생 시 등록된 webhook 호출 (단순 동기 — 단독 운영 전제).

    Kill switch 'webhook_outbound' 가 켜있으면 무시.
    """
    try:
        if current_app.config.get('KILL_SWITCHES', {}).get('webhook_outbound'):
            return
    except Exception:
        pass
    try:
        import urllib.request
        s = SessionLocal()
        try:
            hooks = s.query(WebhookEndpoint).filter(
                WebhookEndpoint.active.is_(True)).all()
            for h in hooks:
                try:
                    events = json.loads(h.events or '[]')
                except (ValueError, TypeError):
                    events = []
                if events and event_name not in events:
                    continue
                try:
                    body = json.dumps({'event': event_name, 'data': payload},
                                      ensure_ascii=False).encode('utf-8')
                    req = urllib.request.Request(
                        h.url, data=body,
                        headers={'Content-Type': 'application/json',
                                 'X-Webhook-Event': event_name,
                                 'X-Webhook-Secret': h.secret or ''})
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        h.last_status_code = resp.status
                except Exception as e:
                    h.last_status_code = -1
                h.last_fired_at = datetime.now(timezone.utc)
            s.commit()
        finally:
            s.close()
    except Exception:
        pass  # webhook 실패가 본 작업을 막지 않도록 보호


# ============ Alert 규칙 (N-9) ============

@bp.get('/alert-rules')
def alert_rules_view():
    s = SessionLocal()
    try:
        items = (s.query(AlertRule)
                 .order_by(AlertRule.metric, AlertRule.name).all())
        return render_template('inventory/alerts.html',
                               active='alerts', items=items)
    finally:
        s.close()


@bp.post('/alert-rules/create')
def alert_create():
    name = (request.form.get('name') or '').strip()
    metric = (request.form.get('metric') or '').strip()
    if not name or not metric:
        flash('이름·메트릭 필요', 'error')
        return redirect(url_for('inventory.alert_rules_view'))
    s = SessionLocal()
    try:
        s.add(AlertRule(
            name=name, metric=metric,
            threshold=float(request.form.get('threshold') or 0),
            operator=(request.form.get('operator') or '>').strip(),
            notify_category=(request.form.get('notify_category') or 'system').strip(),
            active=True,
        ))
        s.commit()
        flash(f'Alert 규칙 "{name}" 추가', 'success')
    finally:
        s.close()
    return redirect(url_for('inventory.alert_rules_view'))


@bp.post('/alert-rules/<int:aid>/toggle')
def alert_toggle(aid):
    s = SessionLocal()
    try:
        a = s.query(AlertRule).filter(AlertRule.id == aid).first()
        if a:
            a.active = not a.active
            s.commit()
        return redirect(url_for('inventory.alert_rules_view'))
    finally:
        s.close()
