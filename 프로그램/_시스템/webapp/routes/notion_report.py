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
        return _page("카카오 연결 실패", f"<p>{html.escape(str(e))}</p>"), 500

    return _page(
        "카카오 연결 완료",
        "<p>이제 매일 09:30 에 카카오톡으로 보고가 갑니다. "
        "지금 바로 확인하려면 아래를 누르세요.</p>"
        "<p><a href='/reports/notion-todo/send'>지금 1건 보내보기</a></p>",
    )


# ──────────────────────────────────────────────────────────────
# 점검 화면
# ──────────────────────────────────────────────────────────────
@bp.route('/reports/notion-todo')
def preview():
    """설정 상태 + 오늘 보고 내용 미리보기. 카톡을 보내지 않는다."""
    from shared import kakao_token
    from lemouton.reports import notion_todo as nt

    kakao = kakao_token.status()
    body = ["<h3>1. 설정 상태</h3>", _pre(kakao)]
    if not kakao["refresh_token_set"]:
        body.append(
            "<p><b>카카오 최초 로그인이 아직입니다.</b> "
            "<a href='/oauth/kakao/start'>여기를 눌러 1회 로그인</a></p>"
        )

    report = nt.build_report()
    body.append("<h3>2. 오늘 보고 내용</h3>")
    if not report.get("ok"):
        body.append(f"<p style='color:#c00'>노션 읽기 실패 — "
                    f"{html.escape(str(report.get('error')))}</p>")
        return _page("노션 투두 보고 점검", "".join(body))

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
    body.append(_pre({k: len(v) for k, v in report["changes"].items()}))
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

    report = nt.build_report()
    if not report.get("ok"):
        return _page("발송 실패",
                     f"<p>노션 읽기 실패 — "
                     f"{html.escape(str(report.get('error')))}</p>"), 500
    ok = send_kakao_memo(report["message"], link_url=nt.page_url(),
                         button_title="노션에서 보기")
    return _page(
        "발송 " + ("완료" if ok else "실패"),
        f"<pre style='background:#FEE500;padding:16px;border-radius:12px;"
        f"white-space:pre-wrap'>{html.escape(report['message'])}</pre>"
        + ("<p>카카오톡을 확인해 주세요.</p>" if ok else
           "<p style='color:#c00'>발송에 실패했습니다. 서버 로그를 확인하세요.</p>"),
    ), (200 if ok else 500)


@bp.route('/api/reports/notion-todo')
def api_preview():
    """기계 판독용 — 미리보기 내용을 JSON 으로."""
    from lemouton.reports import notion_todo as nt

    report = nt.build_report()
    report.pop("todos", None)   # 700건은 응답에 싣지 않는다
    return jsonify(report), (200 if report.get("ok") else 500)
