# -*- coding: utf-8 -*-
"""노션 투두 일일 보고 — 설정·미리보기·수동 발송.

화면은 **점검용 평문 페이지**다(디자인 요소 없음). 목적은 딱 둘:
    ① 카카오 최초 로그인 1회를 끝내는 것
    ② 「오늘 요일 블록을 제대로 골랐는지」를 사장님이 눈으로 확인하는 것
보기 좋은 화면이 필요해지면 그때 design-mockup 게이트를 태워 따로 만든다.
"""
from __future__ import annotations

import html
import json
import logging

from flask import Blueprint, jsonify, redirect, request, send_file

logger = logging.getLogger(__name__)

bp = Blueprint('notion_report', __name__)


def _page(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title></head>"
        "<body style=\"font-family:-apple-system,'Malgun Gothic',sans-serif;"
        "max-width:820px;margin:40px auto;padding:0 20px;line-height:1.7\">"
        f"<h2>{html.escape(title)}</h2>{body}"
        "<p style='margin-top:32px'><a href='/reports/notion-todo'>← 보고 점검 화면</a></p>"
        "</body></html>"
    )


def _pre(obj) -> str:
    dumped = json.dumps(obj, ensure_ascii=False, indent=2)
    return (
        "<pre style='background:#f6f6f6;padding:16px;border-radius:8px;"
        f"overflow:auto;white-space:pre-wrap'>{html.escape(dumped)}</pre>"
    )


# ──────────────────────────────────────────────────────────────
# 카카오 최초 로그인 1회
# ──────────────────────────────────────────────────────────────
@bp.route('/oauth/kakao/start')
def kakao_start():
    """카카오 로그인 화면으로 보낸다. 사장님이 1번만 누르면 된다."""
    from shared import kakao_token

    try:
        return redirect(kakao_token.authorize_url())
    except Exception as e:  # noqa: BLE001
        return _page("카카오 연결 실패", f"<p>{html.escape(str(e))}</p>"), 500


@bp.route('/oauth/kakao')
def kakao_callback():
    """카카오가 인가 코드를 들고 돌아오는 자리. 코드를 토큰으로 바꿔 저장한다."""
    from shared import kakao_token

    err = request.args.get('error')
    if err:
        desc = request.args.get('error_description') or ''
        return _page("카카오 연결 거부됨",
                     f"<p>{html.escape(err)} — {html.escape(desc)}</p>"), 400

    code = request.args.get('code')
    if not code:
        return _page("카카오 연결 실패", "<p>인가 코드가 없습니다.</p>"), 400

    try:
        kakao_token.exchange_code(code)
    except Exception as e:  # noqa: BLE001
        logger.exception("카카오 인가 코드 교환 실패")
        raw = str(e)
        # 카카오 오류코드는 그대로 보여줘봐야 뭘 해야 할지 알 수 없다 — 할 일로 번역한다.
        hints = {
            "KOE010": "카카오에서 <b>Client Secret 을 「사용함」</b>으로 켜 두셨습니다. "
                      "「카카오 로그인 &gt; 고급 &gt; Client Secret」의 코드를 복사해 "
                      "점검 화면 <b>「카카오 Client Secret」</b> 칸에 저장한 뒤 다시 시도하세요. "
                      "(끄고 싶으시면 거기서 「사용안함」으로 바꿔도 됩니다)",
            "KOE006": "카카오에 등록한 <b>Redirect URI 가 다릅니다.</b> "
                      "「앱 &gt; 플랫폼 키 &gt; REST API 키 &gt; 리다이렉트 URI」가 "
                      "<code>https://mou-m.com/oauth/kakao</code> 인지 확인하세요.",
            "KOE003": "인가 코드가 이미 쓰였거나 만료됐습니다. 로그인을 처음부터 다시 하세요.",
            "talk_message": "카카오 <b>동의항목에서 「카카오톡 메시지 전송」</b>이 꺼져 있습니다. "
                            "「카카오 로그인 &gt; 동의항목」에서 <b>선택 동의</b>로 켜 주세요.",
        }
        hint = next((v for k, v in hints.items() if k in raw), "")
        body = (f"<p style='background:#fee;padding:12px;border-radius:8px'>{hint}</p>"
                if hint else "")
        body += ("<details><summary>카카오가 보낸 원문</summary>"
                 f"<pre style='white-space:pre-wrap'>{html.escape(raw)}</pre></details>")
        return _page("카카오 연결 실패", body), 500

    return _page(
        "카카오 연결 완료",
        "<p>이제 매일 09:30 에 카카오톡으로 보고가 갑니다. "
        "지금 바로 확인하려면 아래를 누르세요.</p>"
        "<p><a href='/reports/notion-todo/send'>지금 1건 보내보기</a></p>",
    )


# ──────────────────────────────────────────────────────────────
# 점검 화면
# ──────────────────────────────────────────────────────────────
@bp.route('/reports/notion-todo/keys', methods=['POST'])
def save_keys():
    """노션·카카오 키를 영속 .env 에 저장. SSH 없이 화면에서 넣기 위한 것.

    값은 저장만 하고 **화면에 되돌려 보여주지 않는다**(앞 4글자만 확인용).
    """
    import os as _os
    from lemouton.auth import secrets as _S
    from lemouton.auth.env_writer import update_env_keys, EnvWriteError

    pairs = {}
    for field, env_key in (("notion_token", "NOTION_TOKEN"),
                           ("kakao_rest_key", "KAKAO_REST_KEY"),
                           ("kakao_client_secret", "KAKAO_CLIENT_SECRET")):
        val = (request.form.get(field) or "").strip()
        if val:
            pairs[env_key] = val
    if not pairs:
        return _page("저장할 값 없음", "<p>둘 다 비어 있습니다.</p>"), 400

    try:
        update_env_keys(_S.secrets_env_path(), pairs, require_non_empty=True)
    except EnvWriteError as e:
        return _page("저장 실패", f"<p>{html.escape(str(e))}</p>"), 500
    # 저장을 처리한 이 워커에도 즉시 반영(나머지는 읽기 직전 refresh_env 가 맞춘다).
    for k, v in pairs.items():
        _os.environ[k] = v

    saved = ", ".join(f"{k} (앞 4글자 {v[:4]}…)" for k, v in pairs.items())
    return _page("저장 완료",
                 f"<p>{html.escape(saved)}</p>"
                 "<p><a href='/reports/notion-todo'>← 점검 화면으로 돌아가 확인</a></p>")


def _key_form(kakao: dict, notion_set: bool) -> str:
    # Client Secret 은 카카오에서 「사용함」으로 켠 앱만 필요하다. 켜 놓고 안 보내면
    #   토큰 교환이 KOE010(Bad client credentials) 로 떨어진다 — 로그인 화면은
    #   통과하고 마지막 단계에서만 실패해서 원인을 찾기 어렵다.
    return (
        "<form method='post' action='/reports/notion-todo/keys' "
        "style='background:#f6f6f6;padding:16px;border-radius:8px'>"
        "<p><b>노션 시크릿</b> "
        f"{'(등록됨 — 바꿀 때만 입력)' if notion_set else '(미등록)'}<br>"
        "<input type='password' name='notion_token' autocomplete='off' "
        "placeholder='ntn_...' style='width:100%;padding:8px'></p>"
        "<p><b>카카오 REST API 키</b> "
        f"{'(등록됨 — 바꿀 때만 입력)' if kakao['rest_key_set'] else '(미등록)'}<br>"
        "<input type='password' name='kakao_rest_key' autocomplete='off' "
        "placeholder='카카오 REST API 키' style='width:100%;padding:8px'></p>"
        "<p><b>카카오 Client Secret</b> "
        f"{'(등록됨)' if kakao.get('client_secret_set') else '(비어 있음 — 카카오에서 「사용안함」이면 그대로 두세요)'}<br>"
        "<input type='password' name='kakao_client_secret' autocomplete='off' "
        "placeholder='카카오 로그인 > 고급 > Client Secret (사용함일 때만)' "
        "style='width:100%;padding:8px'></p>"
        "<button type='submit' style='padding:8px 16px'>저장</button>"
        "</form>"
    )


@bp.route('/reports/notion-todo')
def preview():
    """설정 상태 + 오늘 보고 내용 미리보기. 카톡을 보내지 않는다."""
    from shared import kakao_token, state_store
    from lemouton.reports import notion_todo as nt

    kakao = kakao_token.status()
    notion_set = bool(nt._token())
    body = ["<h3>1. 설정 상태</h3>", _pre(dict(kakao, notion_token_set=notion_set))]

    if state_store.is_ephemeral():
        body.append(
            "<p style='background:#fee;padding:12px;border-radius:8px'>"
            "<b>경고 — 저장 위치가 임시입니다.</b> 배포할 때마다 카카오 로그인이 풀리고 "
            "그날 보고가 빠집니다. 서버에 <code>MOUM_SECRETS_ENV</code> 또는 "
            "<code>MOUM_STATE_DIR</code> 이 설정돼 있어야 합니다.</p>"
        )

    body.append("<h3>1-1. 키 입력</h3>")
    body.append(_key_form(kakao, notion_set))

    from lemouton.reports import report_schedule, shot_store
    body.append("<h3>1-2. 발송 시각</h3>")
    body.append(_schedule_form(report_schedule.times()))

    body.append("<h3>1-3. 노션 캡처 (사장님 PC 크롬 확장이 올림)</h3>")
    body.append(_pre(shot_store.status()))
    body.append(
        "<p>캡처가 <b>신선하지 않으면 사진 없이 글만</b> 나갑니다 — PC 가 꺼져 있어도 "
        "보고 자체는 빠지지 않습니다.</p>"
        "<p><a href='/reports/notion-todo/history'>→ 언제 무엇이 바뀌었나 (변경 이력)</a></p>"
    )

    if not kakao["refresh_token_set"]:
        body.append(
            "<p><b>카카오 최초 로그인이 아직입니다.</b> "
            "<a href='/oauth/kakao/start'>여기를 눌러 1회 로그인</a> "
            "(카카오 REST API 키를 먼저 저장해야 열립니다)</p>"
        )

    # ★ 노션 한 바퀴는 몇 분 걸린다(블록마다 자식 조회 + 초당 3회 제한).
    #   요청 안에서 돌리면 Cloudflare 100초 상한에 걸려 화면이 죽는다 → 저장된
    #   마지막 결과만 즉시 보여주고, 새로 읽는 건 백그라운드로 돌린다.
    body.append("<h3>2. 오늘 보고 내용</h3>")
    report = nt.load_last_report()

    if nt.is_refreshing():
        body.append(
            "<p style='background:#eef;padding:12px;border-radius:8px'>"
            "<b>노션을 읽는 중입니다.</b> 항목이 많아 몇 분 걸립니다. "
            "이 화면은 자동으로 새로고침됩니다.</p>"
            "<script>setTimeout(function(){location.reload()},15000)</script>"
        )
    else:
        body.append(
            "<form method='post' action='/reports/notion-todo/refresh' "
            "style='margin:0 0 12px'>"
            "<button type='submit' style='padding:8px 16px'>노션 지금 다시 읽기</button>"
            "</form>"
        )

    if report is None:
        body.append("<p>아직 한 번도 읽지 않았습니다. 위 버튼을 눌러주세요.</p>")
        return _page("노션 투두 보고 점검", "".join(body))
    if not report.get("ok"):
        body.append(f"<p style='color:#c00'>노션 읽기 실패 — "
                    f"{html.escape(str(report.get('error')))}</p>")
        return _page("노션 투두 보고 점검", "".join(body))
    body.append(f"<p style='color:#666'>마지막으로 읽은 시각: "
                f"{html.escape(str(report.get('collected_at')))}</p>")

    body.append("<p>카톡으로 나갈 문구:</p>")
    body.append(
        "<pre style='background:#FEE500;padding:16px;border-radius:12px;"
        f"white-space:pre-wrap'>{html.escape(report['message'])}</pre>"
    )
    body.append(f"<p>글자 수: {len(report['message'])} / 200</p>")

    body.append("<h3>3. 오늘 요일 블록을 제대로 골랐나 (★확인 필요)</h3>")
    body.append(_pre(report["picked"]))
    body.append(
        "<p>위 <code>first_item</code> 이 <b>이번 주 해당 요일</b>의 첫 항목이 맞는지 "
        "노션과 대조해 주세요. 다르면 알려주시면 고르는 규칙을 바꾸겠습니다.</p>"
    )

    body.append("<h3>4. 어제 대비 변경</h3>")
    body.append(_pre({k: (len(v) if isinstance(v, list) else v)
                      for k, v in (report.get("changes") or {}).items()}))
    if report.get("first_run"):
        body.append("<p>아직 기준선이 없습니다(첫 실행). 첫 실행은 발송 없이 "
                    "기준선만 저장하고, 다음 날부터 변경분이 나갑니다.</p>")

    body.append("<h3>5. 지금 보내보기</h3>")
    body.append("<p><a href='/reports/notion-todo/send'>카카오톡 1건 발송</a> "
                "(하루 1회 제한과 무관하게 강제 발송)</p>")
    return _page("노션 투두 보고 점검", "".join(body))


@bp.route('/reports/notion-todo/send')
def send_now():
    """지금 즉시 1건 발송. 하루 1회 게이트를 우회한다(수동 확인용)."""
    from shared.notifier import send_kakao_memo_detailed
    from lemouton.reports import notion_todo as nt

    report = nt.load_last_report()
    if report is None or not report.get("ok"):
        return _page(
            "발송 실패",
            "<p>보낼 내용이 없습니다. 점검 화면에서 "
            "<b>「노션 지금 다시 읽기」</b>를 먼저 눌러 수집이 끝난 뒤 다시 시도하세요.</p>"
            + (f"<p>마지막 오류: {html.escape(str(report.get('error')))}</p>"
               if report else "")), 400
    res = send_kakao_memo_detailed(report["message"], link_url=nt.page_url(),
                                   button_title="노션에서 보기")
    bubble = (f"<pre style='background:#FEE500;padding:16px;border-radius:12px;"
              f"white-space:pre-wrap'>{html.escape(report['message'])}</pre>")

    if res["ok"]:
        note = "<p>카카오톡 <b>나와의 채팅</b>을 확인해 주세요.</p>"
        if res.get("dropped_link"):
            note += ("<p style='color:#a60'>노션 링크 버튼은 빼고 보냈습니다 — "
                     "카카오가 등록되지 않은 도메인 링크를 거부했습니다. "
                     "글 내용은 그대로입니다.</p>")
        return _page("발송 완료", bubble + note), 200

    raw = str(res.get("error") or "")
    # 카카오 오류를 그대로 보여줘봐야 뭘 해야 할지 알 수 없다 — 할 일로 번역한다.
    hints = [
        ("insufficient scopes", "카카오 <b>동의항목의 「카카오톡 메시지 전송」</b>이 "
                                "꺼져 있거나 로그인 때 동의되지 않았습니다. "
                                "「카카오 로그인 &gt; 동의항목」에서 <b>선택 동의</b>로 켠 뒤, "
                                "점검 화면에서 <b>카카오 로그인을 한 번 더</b> 하세요."),
        ("-402", "메시지 형식이 카카오 규격과 맞지 않습니다. 이 문구를 그대로 알려주세요."),
        ("-401", "카카오톡 계정이 연결돼 있지 않습니다. 카카오톡에 로그인된 계정인지 확인하세요."),
        ("not exist kakao account", "이 카카오계정에 <b>카카오톡이 연결돼 있지 않습니다.</b> "
                                    "카카오톡을 쓰는 계정으로 다시 로그인해 주세요."),
        ("invalid_grant", "로그인이 만료됐습니다. 점검 화면에서 카카오 로그인을 다시 하세요."),
    ]
    hint = next((v for k, v in hints if k in raw), "")
    body = bubble
    if hint:
        body += f"<p style='background:#fee;padding:12px;border-radius:8px'>{hint}</p>"
    else:
        body += ("<p style='color:#c00'>발송에 실패했습니다. 아래 원문을 "
                 "그대로 알려주시면 원인을 짚어드리겠습니다.</p>")
    body += (f"<p>카카오 응답 코드: <b>{res.get('status')}</b></p>"
             f"<pre style='white-space:pre-wrap;background:#f6f6f6;padding:12px;"
             f"border-radius:8px'>{html.escape(raw)}</pre>")
    return _page("발송 실패", body), 500


@bp.route('/reports/notion-todo/refresh', methods=['POST'])
def refresh():
    """노션 재수집을 백그라운드로 시작하고 점검 화면으로 되돌린다."""
    from lemouton.reports import notion_todo as nt

    nt.start_refresh()
    return redirect('/reports/notion-todo')


# ──────────────────────────────────────────────────────────────
# 발송 시각표 · 캡처 · 변경 이력
# ──────────────────────────────────────────────────────────────
@bp.route('/reports/notion-todo/schedule', methods=['POST'])
def save_schedule():
    """발송 시각 교체. 한 줄에 하나씩(HH:MM)."""
    from lemouton.reports import report_schedule

    raw = (request.form.get('times') or '').replace(',', '\n')
    good, bad = report_schedule.set_times(raw.splitlines())
    body = f"<p>저장된 시각: <b>{html.escape(', '.join(good)) or '없음'}</b></p>"
    if bad:
        body += ("<p style='color:#c00'>형식이 아니라 버린 값: "
                 f"{html.escape(', '.join(bad))} — <code>09:30</code> 처럼 적어주세요.</p>")
    if not good:
        body += "<p style='color:#c00'>시각이 하나도 없으면 보고가 나가지 않습니다.</p>"
    return _page("발송 시각 저장", body)


def _schedule_form(times: list[str]) -> str:
    return (
        "<form method='post' action='/reports/notion-todo/schedule' "
        "style='background:#f6f6f6;padding:16px;border-radius:8px'>"
        "<p>한 줄에 하나씩 <code>HH:MM</code> (24시간). 예: 09:30</p>"
        "<textarea name='times' rows='4' style='width:100%;padding:8px;"
        f"font-family:monospace'>{html.escape(chr(10).join(times))}</textarea>"
        "<p><button type='submit' style='padding:8px 16px'>시각 저장</button></p>"
        "</form>"
    )


@bp.route('/api/reports/notion-todo/shot', methods=['POST'])
def upload_shot():
    """크롬 확장이 캡처한 노션 요일 칸을 받는다(사장님 PC 에서 올라옴)."""
    from lemouton.reports import shot_store

    blob = request.files.get('shot')
    data = blob.read() if blob else request.get_data()
    try:
        meta = shot_store.save(data or b'',
                               weekday=(request.args.get('weekday') or ''),
                               note=(request.args.get('note') or ''))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:  # noqa: BLE001
        logger.exception("캡처 저장 실패")
        return jsonify(ok=False, error=str(e)), 500
    return jsonify(ok=True, **meta)


@bp.route('/api/reports/notion-todo/shot/needed')
def shot_needed():
    """확장이 물어보는 자리 — 지금 캡처를 올려야 하나.

    다음 발송 시각이 `lead` 분 안으로 다가왔고 아직 신선한 캡처가 없으면 True.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    from lemouton.reports import report_schedule, shot_store
    from lemouton.reports import notion_todo as nt

    try:
        from zoneinfo import ZoneInfo
        now = _dt.now(ZoneInfo('Asia/Seoul'))
    except Exception:  # noqa: BLE001
        now = _dt.now(_tz(_td(hours=9)))

    lead = int(request.args.get('lead') or 10)
    upcoming = None
    for slot in report_schedule.times():
        hh, mm = (int(x) for x in slot.split(':'))
        at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        mins = (at - now).total_seconds() / 60.0
        if 0 <= mins <= lead:
            upcoming = slot
            break
    return jsonify(
        needed=bool(upcoming) and not shot_store.is_fresh(),
        slot=upcoming,
        page_url=nt.page_url(),
        weekday=nt.weekday_label(),
        shot=shot_store.status(),
    )


@bp.route('/reports/notion-todo/shot/<name>')
def serve_shot(name: str):
    """카카오가 읽어갈 캡처. 공개 주소여야 카카오 서버가 가져갈 수 있다."""
    from lemouton.reports import shot_store

    path = shot_store.path_of(name)
    if not path:
        return _page("캡처 없음", "<p>그런 캡처가 없습니다.</p>"), 404
    return send_file(path, mimetype='image/png')


@bp.route('/reports/notion-todo/history')
def history():
    """언제 무엇이 어떻게 바뀌었나 — 날짜별 타임라인."""
    from lemouton.reports import report_history

    labels = {"added": ("신규", "#1b6"), "completed": ("완료", "#1a7"),
              "reopened": ("체크해제", "#a60"), "removed": ("삭제", "#c00"),
              "edited": ("문구수정", "#06c")}
    days = int(request.args.get('days') or 7)
    grouped = report_history.by_day(days=days)
    if not grouped:
        return _page("변경 이력",
                     "<p>아직 쌓인 이력이 없습니다. 발송이 한 번 이상 돌면 여기에 쌓입니다.</p>")

    out = []
    for day, rows in grouped:
        total = sum(len(r.get('entries') or []) for r in rows)
        out.append(f"<h3>{html.escape(day)} <span style='color:#888;"
                   f"font-weight:400'>({total}건)</span></h3>")
        for row in rows:
            out.append(f"<p style='color:#666;margin:12px 0 4px'>"
                       f"{html.escape(row.get('slot') or '')} 회차"
                       + ("" if row.get('sent') else " · <span style='color:#c00'>발송 실패</span>")
                       + "</p><ul style='margin:0'>")
            for e in row.get('entries') or []:
                name, color = labels.get(e.get('kind'), ("변경", "#666"))
                when = e.get('edited_at')
                stamp = (f"<span style='color:#888'>{html.escape(when)}</span> "
                         if when else "")
                if e.get('kind') == 'edited':
                    detail = (f"<s style='color:#999'>{html.escape(e.get('before') or '')}</s>"
                              f" → {html.escape(e.get('after') or '')}")
                else:
                    detail = html.escape(e.get('text') or '(빈 항목)')
                out.append(f"<li>{stamp}<b style='color:{color}'>{name}</b> {detail}</li>")
            out.append("</ul>")
    return _page("변경 이력", "".join(out))


@bp.route('/api/reports/notion-todo')
def api_preview():
    """기계 판독용 — 미리보기 내용을 JSON 으로."""
    from lemouton.reports import notion_todo as nt

    report = nt.load_last_report() or {"ok": False, "error": "아직 수집 전"}
    report["refreshing"] = nt.is_refreshing()
    return jsonify(report), (200 if report.get("ok") else 503)
