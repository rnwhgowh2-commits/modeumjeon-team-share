"""[E] 설정 페이지 — 박스히어로 / 알림 채널."""
import os

from flask import Blueprint, render_template, request, jsonify

from shared.db import SessionLocal
from lemouton.sourcing.models import Option

bp = Blueprint('settings', __name__)


# ── [2026-07-30] 없앤 화면에서 옮겨온 두 가지 ──────────────────────────────
#   · 「미맵핑 큐」(/queue)      → 소싱처 수집 쪽 「매칭 실패 목록」
#   · 「업로드 실패함」(/dlq)    → 판매처 전송 쪽 「실패 내역」
#   화면만 없애고 내용은 여기로. 분류 기준은 옛 queue_dlq.py 와 동일하게 유지.
_MATCH_FAIL_CATS = ('신규 모델', '신규 색상', '옵션 매핑', 'URL 미등록')


def _match_fail_cat(item) -> str:
    if not item.suggested_model_code:
        return '신규 모델'
    if not item.suggested_color_code:
        return '신규 색상'
    if not item.resolved_canonical_sku:
        return '옵션 매핑'
    return 'URL 미등록'


def _collect_reports(s) -> tuple[dict, dict]:
    """(매칭 실패, 업로드 실패) — 0건이면 화면에서 한 줄로만 접힌다."""
    from lemouton.sourcing.models import DiscoveryQueueItem
    from lemouton.uploader.models import MarketRegistration
    match_fail = {'total': 0, 'cats': {c: 0 for c in _MATCH_FAIL_CATS}, 'rows': []}
    upload_fail = {'total': 0, 'top_reason': None, 'rows': []}
    try:
        items = (s.query(DiscoveryQueueItem).filter_by(status='pending')
                 .order_by(DiscoveryQueueItem.created_at.desc()).all())
        match_fail['total'] = len(items)
        for it in items:
            cat = _match_fail_cat(it)
            match_fail['cats'][cat] = match_fail['cats'].get(cat, 0) + 1
            if len(match_fail['rows']) < 100:
                match_fail['rows'].append({
                    'id': it.id, 'cat': cat, 'where': it.source,
                    'what': it.raw_text, 'model': it.suggested_model_code or '—'})
    except Exception:   # noqa: BLE001 — 보고서 하나가 죽어도 자동화 화면은 떠야 한다
        pass
    try:
        rows = (s.query(MarketRegistration).filter(MarketRegistration.status == 'failed')
                .order_by(MarketRegistration.last_attempt_at.desc().nullslast()).all())
        upload_fail['total'] = len(rows)
        errs = [r.sync_error for r in rows if r.sync_error]
        if errs:
            upload_fail['top_reason'] = max(set(errs), key=errs.count)
        elif rows:
            upload_fail['top_reason'] = '원인 미상'
        for r in rows[:100]:
            upload_fail['rows'].append({
                'market': r.market, 'sku': r.canonical_sku,
                'at': r.last_attempt_at, 'error': r.sync_error or '원인 미상'})
    except Exception:   # noqa: BLE001
        pass
    return match_fail, upload_fail


@bp.route('/automation')
def automation_view():
    """[자동화] 소싱처 수집 + 판매처 전송 (팀 공유 단일 설정) + 이력 보고서."""
    from lemouton.pricing.settings import get_automation
    from lemouton.uploader.runtime import live_upload_enabled, real_upload_armed
    s = SessionLocal()
    try:
        a = get_automation(s)
        # 두 겹 잠금 상태 — 화면이 서버 열쇠/무장 여부를 정직하게 보여주도록.
        server_unlocked = live_upload_enabled()   # 서버 열쇠(MOUM_LIVE_UPLOAD)
        armed = real_upload_armed(s)              # 둘 다 켜져 실제 나가는 중인가
        match_fail, upload_fail = _collect_reports(s)
        s.commit()
    finally:
        s.close()
    # 미리보기 결과(지난 사이클 '나갈 값') — 켜기 전에 무엇이 나갈지 먼저 보기.
    try:
        from scheduler.jobs import load_upload_preview
        preview = load_upload_preview()
    except Exception:   # noqa: BLE001
        preview = {"at": None, "markets": {}}
    # [2026-08-02] 「상품수집&전송」 하위탭 ② — 탭 목록의 원천은 market_send 한 곳이다.
    #   여기서 목록을 다시 적으면 두 화면의 탭이 갈린다.
    from webapp.routes.market_send import SUBTABS as SEND_SUBTABS
    return render_template('automation/index.html', active='automation', a=a,
                           active_app='send', send_subtabs=SEND_SUBTABS,
                           server_unlocked=server_unlocked, armed=armed, preview=preview,
                           match_fail=match_fail, upload_fail=upload_fail)


@bp.route('/automation/weights')
def automation_weights_view():
    """[크롤 계수] 소싱처>브랜드>모음전>URL 드릴다운 파인더 — 계수(주기 배수) 설정."""
    return render_template('automation/weights.html', active='automation')


# [2026-07-30] 「자동화 로그기록」(/automation/log) 삭제 — 사장님 확정.
#   실행 이력은 자동화 화면의 수집·전송 보고서로 일원화.


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
