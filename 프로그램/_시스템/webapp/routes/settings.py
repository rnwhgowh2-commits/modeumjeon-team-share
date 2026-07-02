"""[E] 설정 페이지 — 박스히어로 / 알림 채널."""
import os

from flask import Blueprint, render_template, request, jsonify

from shared.db import SessionLocal
from lemouton.sourcing.models import Option

bp = Blueprint('settings', __name__)


@bp.route('/automation')
def automation_view():
    """[자동화 설정] 크롤 자동 주기 + 판매처 자동 전송 (팀 공유 단일 설정)."""
    from lemouton.pricing.settings import get_automation
    from lemouton.sets import change_service as cs
    s = SessionLocal()
    try:
        a = get_automation(s)
        try:
            logrows = cs.list_automation_log(s, limit=30)
        except Exception:
            logrows = []
        s.commit()
    finally:
        s.close()
    return render_template('automation/index.html', active='automation',
                           a=a, logrows=logrows)


@bp.post('/api/automation/save')
def automation_save():
    """자동화 설정 저장(토글 즉시 반영). 전달된 항목만 갱신."""
    from lemouton.pricing.settings import save_automation
    data = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        a = save_automation(s, data)
        s.commit()
        return jsonify({'ok': True, 'automation': a})
    finally:
        s.close()


# ─── 팀공유 모드: admin 전용 (시스템 설정 영역). 기존 모드 통과. ───
@bp.before_request
def _admin_only():
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


@bp.route('/boxhero')
def boxhero_view():
    s = SessionLocal()
    try:
        total_opts = s.query(Option).count()
        mapped = s.query(Option).filter(Option.boxhero_sku.isnot(None)).count()
        unmapped = total_opts - mapped
    finally:
        s.close()
    has_token = bool(os.environ.get('BOXHERO_API_TOKEN'))
    return render_template(
        'boxhero/index.html',
        active='boxhero',
        has_token=has_token,
        kpi={'total': total_opts, 'mapped': mapped, 'unmapped': unmapped, 'inventory': '—'},
    )


@bp.route('/alerts')
def alerts_view():
    has_telegram = bool(os.environ.get('TELEGRAM_BOT_TOKEN'))
    has_slack = bool(os.environ.get('SLACK_WEBHOOK'))
    # mockup 4 알림 종류 — DB 라우팅 테이블이 아직 없으므로 정적 default
    notifications = [
        {'key': 'guardrail', 'label': '하한가 미달', 'telegram': True, 'slack': False, 'kakao': False},
        {'key': 'api_fail', 'label': 'API 호출 실패', 'telegram': True, 'slack': True, 'kakao': False},
        {'key': 'winner_change', 'label': '위너매칭 변경', 'telegram': True, 'slack': False, 'kakao': False},
        {'key': 'dryrun_held', 'label': '드라이런 보류', 'telegram': True, 'slack': False, 'kakao': False},
    ]
    return render_template(
        'alerts/index.html',
        active='alerts',
        has_telegram=has_telegram,
        has_slack=has_slack,
        notifications=notifications,
    )
