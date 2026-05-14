"""[I] /inventory/settings — 재고관리 설정.

ai-workflow STEP 7 Sprint 3 Task 3.8
"""
import json
from pathlib import Path
from flask import render_template, request, redirect, url_for, flash

from shared.db import SessionLocal
from lemouton.inventory.locations import list_active

from . import bp


PREF_FILE = Path(__file__).resolve().parents[3] / 'data' / 'notification_prefs.json'


def _load_prefs() -> dict:
    if PREF_FILE.exists():
        try:
            return json.loads(PREF_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        'channel_email': False,
        'channel_push': False,
        'email_to': '',
        'quiet_from': '22:00',
        'quiet_to': '08:00',
        'cats': {},
    }


def _save_prefs(p: dict) -> None:
    PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
    PREF_FILE.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding='utf-8')


_TEAM_FILE = Path(__file__).resolve().parents[3] / 'data' / 'team_settings.json'
_PS_FILE = Path(__file__).resolve().parents[3] / 'data' / 'purchase_sale_settings.json'
_INT_FILE = Path(__file__).resolve().parents[3] / 'data' / 'integration_settings.json'


def _load_json(p: Path, default: dict) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            pass
    return dict(default)


def _save_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


@bp.get('/settings')
def settings_view():
    """재고관리 설정 — 팀 정보 + 자동 정책 + 위치 요약."""
    team = _load_json(_TEAM_FILE, {'team_name': '모음전', 'industry': 'fashion', 'currency': 'KRW', 'tz': 'Asia/Seoul'})
    s = SessionLocal()
    try:
        locations = list_active(s)
        return render_template('inventory/settings.html',
                               active='settings', locations=locations, team=team)
    finally:
        s.close()


@bp.post('/settings/team/save')
def settings_team_save():
    team = _load_json(_TEAM_FILE, {})
    team.update({
        'team_name': (request.form.get('team_name') or '').strip(),
        'industry': request.form.get('industry'),
        'currency': request.form.get('currency'),
        'tz': request.form.get('tz'),
    })
    try:
        _save_json(_TEAM_FILE, team)
        flash('팀 설정 저장됨', 'success')
    except Exception as e:
        flash(f'저장 실패: {e}', 'error')
    return redirect(url_for('inventory.settings_view'))


@bp.get('/settings/purchase-sale')
def settings_purchase_sale_view():
    pref = _load_json(_PS_FILE, {
        'po_prefix': 'PO', 'po_start': 1,
        'so_prefix': 'SO', 'so_start': 1,
        'ro_prefix': 'RO', 'ro_start': 1,
        'tax_default': 'vat10_excl', 'currency': 'KRW',
        'custom_fields': [],
    })
    return render_template('inventory/settings/purchase_sale.html',
                           active='settings', pref=pref)


@bp.post('/settings/purchase-sale/save')
def settings_purchase_sale_save():
    pref = _load_json(_PS_FILE, {})
    for code in ('po', 'so', 'ro'):
        pref[f'{code}_prefix'] = (request.form.get(f'{code}_prefix') or code.upper()).strip()
        try:
            pref[f'{code}_start'] = int(request.form.get(f'{code}_start') or 1)
        except ValueError:
            pref[f'{code}_start'] = 1
    pref['tax_default'] = request.form.get('tax_default')
    pref['currency'] = request.form.get('currency')

    cf_names = request.form.getlist('cf_name')
    cf_defaults = request.form.getlist('cf_default')
    cf_targets = request.form.getlist('cf_target')
    pref['custom_fields'] = [
        {'name': n.strip(), 'default': (d or '').strip(), 'target': (t or 'all')}
        for n, d, t in zip(cf_names, cf_defaults, cf_targets)
        if (n or '').strip()
    ]

    try:
        _save_json(_PS_FILE, pref)
        flash('구매·판매 설정 저장됨', 'success')
    except Exception as e:
        flash(f'저장 실패: {e}', 'error')
    return redirect(url_for('inventory.settings_purchase_sale_view'))


@bp.get('/settings/integration')
def settings_integration_view():
    pref = _load_json(_INT_FILE, {
        'smartstore_active': False, 'coupang_active': False,
        'bh_active': True, 'bh_last_import': '',
        'excel_api': True,
    })
    return render_template('inventory/settings/integration.html',
                           active='settings', pref=pref)


@bp.post('/settings/integration/save')
def settings_integration_save():
    pref = _load_json(_INT_FILE, {})
    pref['smartstore_active'] = bool(request.form.get('smartstore_active'))
    pref['coupang_active'] = bool(request.form.get('coupang_active'))
    pref['bh_active'] = bool(request.form.get('bh_active'))
    pref['excel_api'] = bool(request.form.get('excel_api'))
    try:
        _save_json(_INT_FILE, pref)
        flash('연동 설정 저장됨', 'success')
    except Exception as e:
        flash(f'저장 실패: {e}', 'error')
    return redirect(url_for('inventory.settings_integration_view'))


@bp.get('/settings/notifications')
def settings_notifications_view():
    """박스히어로 1:1 알림 설정 — 채널 (인앱/이메일/푸시) + 카테고리별 토글."""
    pref = _load_prefs()
    return render_template('inventory/settings/notifications.html',
                           active='settings', pref=pref)


@bp.post('/settings/notifications/save')
def settings_notifications_save():
    pref = _load_prefs()
    pref['channel_email'] = bool(request.form.get('channel_email'))
    pref['channel_push'] = bool(request.form.get('channel_push'))
    pref['email_to'] = (request.form.get('email_to') or '').strip()
    pref['quiet_from'] = request.form.get('quiet_from') or '22:00'
    pref['quiet_to'] = request.form.get('quiet_to') or '08:00'

    cats: dict = {}
    cat_codes = ['low_stock', 'po_partial', 'po_completed', 'so_completed',
                 'penalty', 'sync', 'system']
    for code in cat_codes:
        cats[code] = {
            'inapp': True,  # 항상 활성
            'email': bool(request.form.get(f'cat_{code}_email')),
            'push': bool(request.form.get(f'cat_{code}_push')),
        }
    pref['cats'] = cats

    try:
        _save_prefs(pref)
        flash('알림 설정 저장됨', 'success')
    except Exception as e:
        flash(f'저장 실패: {e}', 'error')
    return redirect(url_for('inventory.settings_notifications_view'))


@bp.get('/settings/notifications/test')
def settings_notifications_test():
    pref = _load_prefs()
    channels = ['인앱']
    if pref.get('channel_email'):
        channels.append(f"이메일 ({pref.get('email_to') or '주소 미설정'})")
    if pref.get('channel_push'):
        channels.append('푸시')
    flash(f"테스트 알림 발송 — {' / '.join(channels)} (실제 SMTP·WebPush 연동은 다음 단계)", 'success')
    return redirect(url_for('inventory.settings_notifications_view'))
