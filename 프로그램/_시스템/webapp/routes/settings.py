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
    from lemouton.uploader.runtime import live_upload_enabled, real_upload_armed
    s = SessionLocal()
    try:
        a = get_automation(s)
        # 두 겹 잠금 상태 — 화면이 서버 열쇠/무장 여부를 정직하게 보여주도록.
        server_unlocked = live_upload_enabled()   # 서버 열쇠(MOUM_LIVE_UPLOAD)
        armed = real_upload_armed(s)              # 둘 다 켜져 실제 나가는 중인가
        s.commit()
    finally:
        s.close()
    # 미리보기 결과(지난 사이클 '나갈 값') — 켜기 전에 무엇이 나갈지 먼저 보기.
    try:
        from scheduler.jobs import load_upload_preview
        preview = load_upload_preview()
    except Exception:   # noqa: BLE001
        preview = {"at": None, "markets": {}}
    return render_template('automation/index.html', active='automation', a=a,
                           server_unlocked=server_unlocked, armed=armed, preview=preview)


@bp.route('/automation/weights')
def automation_weights_view():
    """[크롤 계수] 소싱처>브랜드>모음전>URL 드릴다운 파인더 — 계수(주기 배수) 설정."""
    return render_template('automation/weights.html', active='automation')


@bp.route('/automation/log')
def automation_log_view():
    """[자동화 로그기록] 상품단위(모음전×마켓) 자동 감지·실행 내역."""
    from lemouton.sets import change_service as cs
    s = SessionLocal()
    try:
        try:
            logrows = cs.list_automation_log(s, limit=200)
        except Exception:
            logrows = []
        s.commit()
    finally:
        s.close()
    return render_template('automation/log.html', active='automation_log',
                           logrows=logrows)


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
