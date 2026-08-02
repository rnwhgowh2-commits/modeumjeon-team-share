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

from flask import Blueprint, jsonify, redirect, request

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
    from shared.notifier import send_kakao_memo
    from lemouton.reports import notion_todo as nt

    report = nt.load_last_report()
    if report is None or not report.get("ok"):
        return _page(
            "발송 실패",
            "<p>보낼 내용이 없습니다. 점검 화면에서 "
            "<b>「노션 지금 다시 읽기」</b>를 먼저 눌러 수집이 끝난 뒤 다시 시도하세요.</p>"
            + (f"<p>마지막 오류: {html.escape(str(report.get('error')))}</p>"
               if report else "")), 400
    ok = send_kakao_memo(report["message"], link_url=nt.page_url(),
                         button_title="노션에서 보기")
    return _page(
        "발송 " + ("완료" if ok else "실패"),
        f"<pre style='background:#FEE500;padding:16px;border-radius:12px;"
        f"white-space:pre-wrap'>{html.escape(report['message'])}</pre>"
        + ("<p>카카오톡을 확인해 주세요.</p>" if ok else
           "<p style='color:#c00'>발송에 실패했습니다. 서버 로그를 확인하세요.</p>"),
    ), (200 if ok else 500)


@bp.route('/reports/notion-todo/refresh', methods=['POST'])
def refresh():
    """노션 재수집을 백그라운드로 시작하고 점검 화면으로 되돌린다."""
    from lemouton.reports import notion_todo as nt

    nt.start_refresh()
    return redirect('/reports/notion-todo')


@bp.route('/api/reports/notion-todo')
def api_preview():
    """기계 판독용 — 미리보기 내용을 JSON 으로."""
    from lemouton.reports import notion_todo as nt

    report = nt.load_last_report() or {"ok": False, "error": "아직 수집 전"}
    report["refreshing"] = nt.is_refreshing()
    return jsonify(report), (200 if report.get("ok") else 503)
