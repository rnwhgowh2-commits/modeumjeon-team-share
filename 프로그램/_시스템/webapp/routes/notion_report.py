# -*- coding: utf-8 -*-
"""노션 투두 일일 보고 — 설정·미리보기·수동 발송.

**화면 구성(시안 C · 사장님 확정 2026-08-02)**
    왼쪽에 **일하는 순서 7단계**가 늘 보이고, 오른쪽에 그 단계 내용이 뜬다.
    기본은 5단계(오늘 나갈 것) — 매일 여는 목적이 「오늘 뭐가 나가나」이기 때문.

        1 무엇을 읽나   · 노션 문서 고르기 + 시크릿
        2 언제 보내나   · 발송 시각
        3 어디로 보내나 · 카카오 연결
        4 사진 준비     · PC 크롬 확장 캡처
        5 오늘 나갈 것  · 카톡 두 통 미리보기 + 요일 판정 + 어제 대비  ← 기본
        6 지금 보내보기 · 캡처하고 보내기(옛 「테스트 발송」 화면)
        7 지나간 기록   · 변경 이력(옛 「변경 이력」 화면)

    옛 주소(`/test`·`/history`)는 그대로 살아 있다 — 카톡 버튼이 그리로 온다.

**맨 위 신호등 4칸**이 「지금 보고가 나갈 상태인가」를 색으로 말한다. 하나만 꺼져도
그날 보고가 통째로 빠지는데, 옛 화면은 그걸 회색 JSON 덩어리로 보여줘 사람이
읽을 수 없었다.
"""
from __future__ import annotations

import html
import json
import logging

from flask import Blueprint, jsonify, redirect, request, send_file

logger = logging.getLogger(__name__)

bp = Blueprint('notion_report', __name__)

#: 왼쪽 단계 목록 — (번호, 이름, 곁들임말)
_STEPS = [
    ("1", "무엇을 읽나", "노션 문서"),
    ("2", "언제 보내나", "발송 시각"),
    ("3", "어디로 보내나", "카카오"),
    ("4", "사진 준비", "크롬 확장"),
    ("5", "오늘 나갈 것", "두 통"),
    ("6", "지금 보내보기", "테스트"),
    ("7", "지나간 기록", "변경 이력"),
]
_DEFAULT_STEP = "5"

_CSS = """
:root{--c-bg:#F2F4F6;--c-card:#fff;--c-line:#E5E8EB;--c-line2:#D1D6DB;
--c-text:#191F28;--c-sub:#6B7684;--c-mute:#8B95A1;--c-primary:#3182F6;
--c-ok:#00B368;--c-warn:#F59E0B;--c-danger:#F04452;--c-kakao:#FEE500;
--r:12px;--r-s:8px}
*{box-sizing:border-box}
/* [중요] [2026-08-03] 이 화면만 「맑은 고딕」으로 그려지고 있었다(라이브 실측).
   규칙서가 정한 글꼴은 Pretendard 하나다(tokens.css --글꼴).
   줄간격 1.6 도 규칙값(1.57)이 아니었다 — 같이 맞춘다. */
body{margin:0;background:var(--c-bg);color:var(--c-text);font-size:15px;
line-height:1.57;font-family:'Pretendard','Pretendard Variable',-apple-system,
BlinkMacSystemFont,'Apple SD Gothic Neo','Segoe UI',system-ui,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 72px}
h1{font-size:40px;font-weight:600;margin:0 0 4px}
.pg-s{margin:0 0 18px;color:var(--c-sub);font-size:14px}
.sec-t{font-size:13px;font-weight:700;color:var(--c-sub);margin:22px 0 10px}
.foot{margin-top:28px;color:var(--c-mute);font-size:13px}
a{color:var(--c-primary)}
.lights{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;
background:var(--c-card);border:1px solid var(--c-line);border-radius:var(--r);
padding:14px 16px;margin-bottom:18px}
.light{display:flex;align-items:center;gap:10px;min-width:0}
.light .dot{width:10px;height:10px;border-radius:50%;flex:none}
.light--ok .dot{background:var(--c-ok)}
.light--warn .dot{background:var(--c-warn)}
.light--danger .dot{background:var(--c-danger)}
.lt{display:flex;flex-direction:column;line-height:1.35;min-width:0}
.lt b{font-size:13.5px;font-weight:600}
.lt span{font-size:12px;color:var(--c-sub);white-space:nowrap;overflow:hidden;
text-overflow:ellipsis}
.flow-wrap{display:grid;grid-template-columns:236px 1fr;gap:18px;
align-items:start}
.flow{background:var(--c-card);border:1px solid var(--c-line);
border-radius:var(--r);padding:8px;position:sticky;top:12px}
.flow a{display:grid;grid-template-columns:26px 1fr 10px;gap:9px;
align-items:center;padding:9px 10px;border-radius:var(--r-s);
text-decoration:none;color:inherit}
.flow a:hover{background:#F7F8FA}
.flow a.on{background:#F4F8FF}
.flow-n{width:26px;height:26px;border-radius:50%;background:#EEF2F6;
display:flex;align-items:center;justify-content:center;font-size:12px;
font-weight:700;color:var(--c-sub)}
.flow a.on .flow-n{background:var(--c-primary);color:#fff}
.flow-t b{display:block;font-size:13.5px}
.flow-t span{font-size:11.5px;color:var(--c-mute)}
.flow-d{width:8px;height:8px;border-radius:50%;background:#E5E8EB}
.flow a.s-ok .flow-d{background:var(--c-ok)}
.flow a.s-warn .flow-d{background:var(--c-warn)}
.flow a.s-danger .flow-d{background:var(--c-danger)}
.body{min-width:0}
.card{background:var(--c-card);border:1px solid var(--c-line);
border-radius:var(--r);padding:16px 18px;margin-bottom:14px}
.card--hero{border-color:#CFE0FB}
.card-h{display:flex;align-items:center;gap:10px;margin-bottom:12px;
flex-wrap:wrap}
.card-h b{font-size:15.5px;font-weight:700}
.card-h .sub{font-size:12px;color:var(--c-mute)}
.card-h .right{margin-left:auto}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:start}
.kk-row{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}
.kk{min-width:0}
.kk-head{display:flex;align-items:baseline;gap:8px;margin-bottom:6px;
flex-wrap:wrap}
.kk-head b{font-size:13.5px;font-weight:700}
.kk-meta{font-size:11.5px;color:var(--c-sub)}
.kk-bubble{background:var(--c-kakao);border-radius:14px;padding:12px;
max-width:440px}
.kk-bubble img{max-width:100%;border-radius:10px;border:1px solid #EBD400;
display:block;margin-bottom:8px;background:#fff}
.kk-text{margin:0;font-size:13px;line-height:1.55;color:var(--c-text);
white-space:pre-wrap;font-family:inherit}
.kk-btns{display:flex;gap:6px;margin-top:10px}
.kk-btn{flex:1;background:#fff;border:1px solid #EBD400;border-radius:8px;
padding:7px 6px;font-size:12px;font-weight:600;color:var(--c-text);
text-align:center;text-decoration:none}
.kv{display:grid;gap:6px}
/* 숫자 칸을 1fr 로 두고 단위 칸을 고정폭으로 — 값 폭이 행마다 달라도
   숫자 오른쪽 끝이 세로로 맞는다. max-content 로 두면 「37건」과 「2개」의
   오른쪽 끝이 어긋난다(2026-08-02 라이브 실측). */
.kv-r{display:grid;grid-template-columns:150px 1fr 2em;
gap:8px;align-items:baseline}
.kv-r--wide{grid-template-columns:150px 1fr}
.kv-k{font-size:13px;color:var(--c-sub)}
.kv-v{font-size:13.5px;font-weight:600;text-align:right}
.kv-v--txt{text-align:left;font-weight:400}
.kv-u{font-size:12px;color:var(--c-sub)}
.num{font-variant-numeric:tabular-nums}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px;
color:var(--c-sub);word-break:break-all}
.dl{display:grid;gap:4px}
.dl-r{display:grid;grid-template-columns:28px 1fr max-content max-content;
gap:8px;align-items:baseline;padding:5px 8px;border-radius:6px}
.dl-r:nth-child(odd){background:#FAFBFC}
.dl-m{text-align:center;font-size:13px}
.dl-k{font-size:13px}
.dl-v{text-align:right;font-weight:700;font-size:13.5px;
font-variant-numeric:tabular-nums}
.dl-u{font-size:12px;color:var(--c-sub)}
.hist-h{font-size:12.5px;color:var(--c-sub);margin:14px 0 4px}
.hist{display:grid;gap:3px}
.hist-r{display:grid;grid-template-columns:28px 64px 1fr;gap:8px;
align-items:baseline;font-size:12.5px}
.hist-k{font-weight:600;text-align:center}
.hist-t{color:var(--c-sub)}
.hist-t s{color:var(--c-mute)}
.badge{font-size:11.5px;font-weight:600;border-radius:999px;padding:2px 9px}
.badge--ok{background:#E6F8F0;color:#00875A}
.badge--warn{background:#FEF3E2;color:#B25E09}
.badge--danger{background:#FFECEE;color:#C9252D}
.btn{background:#EEF2F6;border:1px solid var(--c-line);border-radius:var(--r-s);
padding:8px 14px;font-size:13px;font-weight:600;color:var(--c-text);
cursor:pointer;font-family:inherit;text-decoration:none;display:inline-block}
.btn--primary{background:var(--c-primary);border-color:var(--c-primary);
color:#fff}
.btn--line{background:#fff}
.btn-row{display:flex;gap:8px;margin:10px 0;flex-wrap:wrap}
.form{display:grid;gap:10px;margin-top:4px}
.form label{display:grid;gap:5px;font-size:13px;font-weight:600}
.form input,.form textarea,.swap input{border:1px solid var(--c-line2);
border-radius:var(--r-s);padding:9px 11px;font-size:13px;font-family:inherit;
width:100%}
.form .ok-t{font-size:11.5px;color:var(--c-ok);font-weight:600}
.form .sub{font-size:11.5px;color:var(--c-mute);font-weight:400}
.note{margin:8px 0 0;font-size:12.5px;color:var(--c-sub);line-height:1.55}
.note--todo{background:#FFF7E6;border-radius:var(--r-s);padding:8px 10px;
color:#8A5A00}
.note--info{background:#EEF4FF;border-radius:var(--r-s);padding:8px 10px;
color:#1B4FA0}
.note--bad{background:#FFF1F2;border-radius:var(--r-s);padding:8px 10px;
color:#C9252D}
.raw{margin-top:10px}
.raw summary{font-size:12px;color:var(--c-mute);cursor:pointer}
.raw pre,pre.box{background:#F7F8FA;border-radius:var(--r-s);padding:10px 12px;
font-size:11.5px;line-height:1.5;overflow:auto;margin:6px 0 0;
font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap}
code{background:#F0F2F5;border-radius:4px;padding:1px 5px;font-size:12px}
.swap{display:grid;grid-template-columns:1fr max-content;gap:8px;margin-top:10px}
.pick{display:grid;gap:6px;margin-top:4px}
.pick-r{display:grid;grid-template-columns:18px 1fr max-content;gap:10px;
align-items:center;border:1px solid var(--c-line);border-radius:var(--r-s);
padding:9px 12px;font-size:13px;cursor:pointer}
.pick-r.on{border-color:var(--c-primary);background:#F4F8FF}
.pick-n{font-weight:600}
.pick-s{font-size:12px;color:var(--c-sub)}
@media (max-width:860px){.flow-wrap{grid-template-columns:1fr}
.flow{position:static}.grid2,.kk-row,.lights{grid-template-columns:1fr}}
/* [3단계 배치2 · 2026-08-04] 폰(≤768px) 덧붙임 — 860px 블록(위)이 이미 한 줄로
   접어 준다. 여기선 손끝 목표·글자 크기·여백만 다듬는다. PC 렌더는 안 바뀐다.
    이 화면은 base.html 밖 독립 화면이라 껍데기(노란 띠)가 애초에 안 뜬다 —
     MOBILE_READY 등록은 메뉴 배지(폰 전용) 몫이다. */
@media (max-width: 768px) {
.wrap{padding:16px 12px 56px}
.card{padding:14px 14px}
.btn{display:inline-flex;align-items:center;min-height:44px;font-size:14px}
.flow a{min-height:44px}
.form input,.form textarea,.swap input{min-height:44px;font-size:16px}
.pick-r{min-height:44px;font-size:14px}
.kv-r{grid-template-columns:110px 1fr 2em}
.kv-r--wide{grid-template-columns:110px 1fr}
.kv-k,.kv-v,.dl-k,.dl-v,.note,.hist-r,.kk-text{font-size:14px}
.kk-bubble{max-width:100%}
}
"""


def _shell(title: str, body: str) -> str:
    """모든 화면의 겉껍데기. 결과 화면(발송 완료 등)도 같은 옷을 입는다."""
    return (
        "<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title>"
        # 글꼴을 이름만 적어 두면 그 글꼴이 없는 컴퓨터에서는 안 걸린다 — 같이 내려받는다.
        "<link rel='stylesheet' href='https://cdn.jsdelivr.net/gh/orioncactus/"
        "pretendard@v1.3.9/dist/web/static/pretendard.min.css'>"
        f"<style>{_CSS}</style></head>"
        f"<body><div class='wrap'>{body}</div></body></html>"
    )


def _page(title: str, body: str) -> str:
    """결과 알림 한 장(저장 완료·발송 완료 등). 되돌아갈 길을 항상 남긴다."""
    return _shell(
        title,
        f"<h1>{html.escape(title)}</h1>"
        f"<div class='card'>{body}</div>"
        "<p class='foot'><a href='/reports/notion-todo'>← 보고 점검 화면</a></p>"
    )


def _pre(obj) -> str:
    dumped = json.dumps(obj, ensure_ascii=False, indent=2)
    return f"<pre class='box'>{html.escape(dumped)}</pre>"


def _raw(label: str, obj) -> str:
    """원본 값 그대로 보기 — 사람이 읽는 줄 아래에 근거를 남긴다."""
    return (f"<details class='raw'><summary>{html.escape(label)}</summary>"
            f"{_pre(obj)}</details>")


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
        body = (f"<p class='note note--bad'>{hint}</p>" if hint else "")
        body += ("<details class='raw'><summary>카카오가 보낸 원문</summary>"
                 f"<pre class='box'>{html.escape(raw)}</pre></details>")
        return _page("카카오 연결 실패", body), 500

    return _page(
        "카카오 연결 완료",
        "<p>이제 매일 09:30 에 카카오톡으로 보고가 갑니다. "
        "지금 바로 확인하려면 아래를 누르세요.</p>"
        "<p><a href='/reports/notion-todo/send'>지금 1건 보내보기</a></p>",
    )


# ──────────────────────────────────────────────────────────────
# 키 저장 · 문서 갈아타기
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
                 "<p><a href='/reports/notion-todo?step=1'>← 점검 화면으로 돌아가 확인</a></p>")


@bp.route('/reports/notion-todo/page', methods=['POST'])
def save_page():
    """읽을 노션 문서 갈아타기.

    [중요] **번호만 바꾸면 안 된다.** 어제 기준선이 남의 문서 것이라 다음 회차가
    「전부 신규」로 잡혀 수백 건짜리 거짓 보고가 나간다 → `set_page` 가 기준선을
    같이 비운다. 비운 뒤 첫 회차는 발송 없이 기준선만 저장한다.
    """
    from lemouton.reports import notion_todo as nt

    raw = (request.form.get('page') or request.form.get('page_url') or '').strip()
    title = (request.form.get('title') or '').strip()
    if not raw:
        return _page("바꿀 문서가 없음",
                     "<p>고르거나 주소를 붙여넣어 주세요.</p>"), 400

    res = nt.set_page(raw, title=title)
    if not res.get("ok"):
        return _page("문서 바꾸기 실패",
                     f"<p class='note note--bad'>{html.escape(str(res.get('error')))}</p>"), 400

    nt.start_refresh()
    name = res.get("title") or res["id"]
    return _page(
        "읽을 문서를 바꿨습니다",
        f"<p>이제 <b>{html.escape(name)}</b> 를 읽습니다.</p>"
        "<p>어제 기준선을 비웠습니다 — 다음 회차는 <b>발송 없이 기준선만</b> 저장하고, "
        "그다음 회차부터 변경분이 나갑니다. (그러지 않으면 「전부 신규」로 잡혀 "
        "거짓 보고가 나갑니다)</p>"
        "<p>지금 새 문서를 읽는 중입니다 — 몇 분 걸립니다.</p>"
        "<p><a href='/reports/notion-todo'>← 오늘 나갈 것 보기</a></p>")


def _key_form(kakao: dict, notion_set: bool) -> str:
    # Client Secret 은 카카오에서 「사용함」으로 켠 앱만 필요하다. 켜 놓고 안 보내면
    #   토큰 교환이 KOE010(Bad client credentials) 로 떨어진다 — 로그인 화면은
    #   통과하고 마지막 단계에서만 실패해서 원인을 찾기 어렵다.
    return (
        "<form method='post' action='/reports/notion-todo/keys' class='form'>"
        "<label>노션 시크릿 "
        f"<span class='{'ok-t' if notion_set else 'sub'}'>"
        f"{'(등록됨 — 바꿀 때만 입력)' if notion_set else '(미등록)'}</span>"
        "<input type='password' name='notion_token' autocomplete='off' "
        "placeholder='ntn_...'></label>"
        "<label>카카오 REST API 키 "
        f"<span class='{'ok-t' if kakao['rest_key_set'] else 'sub'}'>"
        f"{'(등록됨 — 바꿀 때만 입력)' if kakao['rest_key_set'] else '(미등록)'}</span>"
        "<input type='password' name='kakao_rest_key' autocomplete='off' "
        "placeholder='카카오 REST API 키'></label>"
        "<label>카카오 Client Secret "
        f"<span class='{'ok-t' if kakao.get('client_secret_set') else 'sub'}'>"
        f"{'(등록됨)' if kakao.get('client_secret_set') else '(비어 있음 — 카카오에서 「사용안함」이면 그대로 두세요)'}</span>"
        "<input type='password' name='kakao_client_secret' autocomplete='off' "
        "placeholder='카카오 로그인 > 고급 > Client Secret (사용함일 때만)'></label>"
        "<div><button type='submit' class='btn'>저장</button></div>"
        "</form>"
    )


def _schedule_form(times: list[str]) -> str:
    return (
        "<form method='post' action='/reports/notion-todo/schedule' class='form'>"
        "<p class='note'>한 줄에 하나씩 <code>HH:MM</code> (24시간). 예: 09:30</p>"
        "<textarea name='times' rows='4' style='font-family:monospace'>"
        f"{html.escape(chr(10).join(times))}</textarea>"
        "<div><button type='submit' class='btn'>시각 저장</button></div>"
        "</form>"
    )


# ──────────────────────────────────────────────────────────────
# 단계별 내용
# ──────────────────────────────────────────────────────────────
def _step_docs(kakao: dict, notion_set: bool) -> str:
    """1단계 — 무엇을 읽나. 문서 목록에서 클릭 1번(없으면 주소 붙여넣기)."""
    from lemouton.reports import notion_todo as nt

    out = ["<div class='card'><div class='card-h'><b>읽을 노션 문서 고르기</b>"
           "<span class='sub'>노션에서 우리에게 열어준 문서만 보입니다</span></div>"]
    out.append("<div class='kv'>"
               "<div class='kv-r kv-r--wide'><span class='kv-k'>지금 읽는 문서</span>"
               f"<span class='kv-v kv-v--txt'>{html.escape(nt.page_title())}</span></div>"
               "<div class='kv-r kv-r--wide'><span class='kv-k'>문서 번호</span>"
               f"<span class='kv-v kv-v--txt mono'>{html.escape(nt.page_id())}</span>"
               "</div></div>")

    if not notion_set:
        out.append("<p class='note note--todo'>노션 시크릿이 아직 없어 문서 목록을 "
                   "불러올 수 없습니다. 아래 <b>「노션 시크릿」</b>을 먼저 저장해 주세요.</p>")
    elif request.args.get('docs'):
        listed = nt.list_pages()
        if not listed.get("ok"):
            out.append("<p class='note note--bad'>목록을 못 불러왔습니다 — "
                       f"{html.escape(str(listed.get('error')))}</p>")
        elif not listed.get("pages"):
            out.append("<p class='note note--todo'>노션이 열어준 문서가 하나도 "
                       "없습니다. 노션에서 문서 <b>⋯ &gt; 연결</b>에 우리 연결을 "
                       "추가해 주세요.</p>")
        else:
            out.append("<form method='post' action='/reports/notion-todo/page'>"
                       "<div class='pick'>")
            for pg in listed["pages"]:
                on = " on" if pg["is_current"] else ""
                checked = " checked" if pg["is_current"] else ""
                out.append(
                    f"<label class='pick-r{on}'>"
                    f"<input type='radio' name='page' value='{html.escape(pg['id'])}'{checked}>"
                    f"<span class='pick-n'>{html.escape(pg['title'])}</span>"
                    f"<span class='pick-s'>{'지금 읽는 중' if pg['is_current'] else ''}</span>"
                    "</label>")
            out.append("</div><div class='btn-row'>"
                       "<button type='submit' class='btn btn--primary'>이 문서로 바꾸기</button>"
                       "<a class='btn btn--line' href='/reports/notion-todo?step=1&docs=1'>"
                       "목록 새로 불러오기</a></div></form>")
    else:
        out.append("<div class='btn-row'>"
                   "<a class='btn btn--primary' href='/reports/notion-todo?step=1&docs=1'>"
                   "문서 목록 불러오기</a></div>")

    out.append("<p class='note'>고르면 <b>어제 기준선을 비우고</b> 새 문서를 한 번 "
               "읽습니다 — 다음 보고가 「전부 신규」로 터지지 않게.</p>")
    out.append(
        "<details class='raw'><summary>목록에 없어요 — 주소로 넣기</summary>"
        "<form method='post' action='/reports/notion-todo/page' class='swap'>"
        "<input name='page' placeholder='노션 주소 붙여넣기'>"
        "<button type='submit' class='btn btn--primary'>바꾸기</button></form>"
        "<p class='note'>주소만 붙여넣으면 문서 번호를 알아서 뽑습니다.</p></details>")
    out.append("<p class='note note--todo'>목록에 안 보이면 노션에서 그 문서 "
               "<b>⋯ &gt; 연결</b>에 우리 연결을 추가해 주세요 — 안 하면 노션이 "
               "문서를 아예 안 보여줍니다.</p></div>")

    out.append("<div class='card'><div class='card-h'><b>키 입력</b>"
               "<span class='sub'>서버에 들어가지 않고 여기서 넣습니다</span></div>")
    out.append(_key_form(kakao, notion_set))
    out.append(_raw("설정 상태 — 원본 값 그대로 보기",
                    dict(kakao, notion_token_set=notion_set)))
    out.append("</div>")
    return "".join(out)


def _step_time(times: list[str]) -> str:
    from lemouton.reports import report_schedule

    st = report_schedule.status()
    return ("<div class='card'><div class='card-h'><b>발송 시각</b>"
            f"<span class='sub'>{'하루 ' + str(len(times)) + '회' if times else '없음'}"
            "</span></div>"
            + _schedule_form(times)
            + ("" if times else
               "<p class='note note--bad'>시각이 하나도 없으면 보고가 나가지 "
               "않습니다.</p>")
            + _raw("발송 기록 — 원본 값 그대로 보기", st)
            + "</div>")


def _step_kakao(kakao: dict) -> str:
    from shared import state_store

    out = ["<div class='card'><div class='card-h'><b>카카오 연결</b>"]
    if kakao["refresh_token_set"]:
        out.append("<span class='badge badge--ok'>로그인 되어 있음</span></div>")
        out.append("<p class='note'>카카오톡 <b>나와의 채팅</b>으로 갑니다. "
                   "단톡방에는 봇이 글을 쓸 수 없어(카카오 정책) 받으신 뒤 "
                   "전달 1터치가 필요합니다.</p>")
    else:
        out.append("<span class='badge badge--danger'>로그인 필요</span></div>")
        out.append("<p class='note note--todo'><b>카카오 최초 로그인이 아직입니다.</b> "
                   "<a href='/oauth/kakao/start'>여기를 눌러 1회 로그인</a> "
                   "(카카오 REST API 키를 먼저 저장해야 열립니다)</p>")
    out.append("<div class='btn-row'>"
               "<a class='btn btn--line' href='/oauth/kakao/start'>카카오 다시 로그인</a>"
               "</div>")
    if state_store.is_ephemeral():
        out.append("<p class='note note--bad'><b>경고 — 저장 위치가 임시입니다.</b> "
                   "배포할 때마다 카카오 로그인이 풀리고 그날 보고가 빠집니다. "
                   "서버에 <code>MOUM_SECRETS_ENV</code> 또는 "
                   "<code>MOUM_STATE_DIR</code> 이 설정돼 있어야 합니다.</p>")
    out.append(_raw("카카오 상태 — 원본 값 그대로 보기", kakao))
    out.append("</div>")
    return "".join(out)


def _step_shot() -> str:
    from lemouton.reports import shot_store

    st = shot_store.status()
    live = shot_store.public_url()
    age = shot_store.age_minutes()
    badge = ("<span class='badge badge--ok'>붙습니다</span>" if live else
             "<span class='badge badge--danger'>캡처 없이 글만 나갑니다</span>")
    out = ["<div class='card'><div class='card-h'>"
           "<b>노션 캡처 (사장님 PC 크롬 확장이 올림)</b>" + badge + "</div>"]
    out.append("<div class='kv'><div class='kv-r'><span class='kv-k'>마지막 캡처</span>"
               + (f"<span class='kv-v num'>{int(age)}</span>"
                  "<span class='kv-u'>분 전</span>" if age is not None else
                  "<span class='kv-v'>찍은 적 없음</span><span class='kv-u'></span>")
               + "</div>"
               f"<div class='kv-r'><span class='kv-k'>신선 기준</span>"
               f"<span class='kv-v num'>{shot_store.STALE_MINUTES}</span>"
               "<span class='kv-u'>분</span></div></div>")
    out.append("<p class='note'>캡처가 <b>신선하지 않으면 사진 없이 글만</b> 나갑니다 "
               "— PC 가 꺼져 있어도 보고 자체는 빠지지 않습니다.</p>")
    if st.get("file"):
        out.append("<p><img src='/reports/notion-todo/shot/"
                   f"{html.escape(st['file'])}' style='max-width:100%;"
                   "border:1px solid #ddd;border-radius:8px'></p>")
    out.append("<div class='btn-row'>"
               "<a class='btn' href='/reports/notion-todo?step=6'>"
               "→ 지금 캡처하고 지금 보내보기</a></div>")
    out.append(_raw("캡처 상태 — 원본 값 그대로 보기", st))
    out.append("</div>")
    return "".join(out)


def _bubbles(report: dict) -> str:
    """카톡 두 통 — 폰에 뜨는 모양 그대로(사진·버튼 포함)."""
    from lemouton.reports import shot_store
    from lemouton.reports import notion_todo as nt

    # ★버튼·사진 여부를 **고정 문구로 적지 않는다**. 사진이 없어도 「캡처 크게 보기」라고
    #   적어놨다가 「왜 캡처로 안 가느냐」는 오해를 만들었다(2026-08-02).
    #   실제 발송이 쓰는 것과 **같은 판정**(shot_store.public_url)으로 표시한다.
    shot_live = shot_store.public_url()
    if shot_live:
        photo_note = "「캡처 크게 보기」+「노션에서 보기」 · 캡처 붙어서 나갑니다"
        photo_btns = [("캡처 크게 보기", nt.shot_url()),
                      ("노션에서 보기", nt.link_url())]
    else:
        age = shot_store.age_minutes()
        why = ("찍은 적 없음" if age is None
               else f"{int(age)}분 전 것이라 오래됨(기준 {shot_store.STALE_MINUTES}분)")
        photo_note = ("「노션에서 보기」 · <b style='color:#C9252D'>캡처 없이 글만 "
                      f"나갑니다</b> — {why}")
        photo_btns = [("노션에서 보기", nt.link_url())]

    out = ["<div class='kk-row'>"]
    for label, key, note, btns in (
            ("① 사진 통", "photo_message", photo_note, photo_btns),
            ("② 변경 통", "change_message", "「변경 이력 전체」",
             [("변경 이력 전체", nt.history_url())])):
        msg = report.get(key) or ""
        if not msg:
            if key == "change_message":
                out.append("<div class='kk'><p class='note'>② 변경 통 — 바뀐 게 없어 "
                           "보내지 않습니다. (사진 통에 「바뀐 것 없음」이 적혀 "
                           "나갑니다)</p></div>")
            else:
                out.append("<div class='kk'><p class='note note--bad'>① 사진 통 — "
                           "<b>비어 있습니다. 정상이 아닙니다.</b> 저장된 문구가 옛 "
                           "형식일 수 있으니 「노션 지금 다시 읽기」를 한 번 "
                           "눌러주세요.</p></div>")
            continue
        out.append(f"<div class='kk'><div class='kk-head'><b>{label}</b>"
                   f"<span class='kk-meta'>버튼 {note} · "
                   f"<b class='num'>{len(msg)}</b> / 200자</span></div>"
                   "<div class='kk-bubble'>")
        if key == "photo_message" and shot_live:
            out.append("<img src='/reports/notion-todo/shot/latest'>")
        out.append(f"<pre class='kk-text'>{html.escape(msg)}</pre>"
                   "<div class='kk-btns'>")
        for name, url in btns:
            out.append(f"<a class='kk-btn' href='{html.escape(url)}'>"
                       f"{html.escape(name)}</a>")
        out.append("</div></div></div>")
    out.append("</div>")
    return "".join(out)


_CHANGE_LABELS = [("completed", "✅", "완료"), ("added", "🆕", "신규"),
                  ("edited", "✏️", "문구수정"), ("removed", "🗑", "삭제"),
                  ("reopened", "↩", "체크해제")]


def _step_today(report, refreshing: bool) -> str:
    """5단계 — 오늘 나갈 것. 이 화면의 주인공."""
    out = ["<div class='card card--hero'><div class='card-h'><b>오늘 보고 내용</b>"]
    if report and report.get("ok"):
        out.append("<span class='sub'>마지막으로 읽은 시각: "
                   f"{html.escape(str(report.get('collected_at')))}</span>")
    out.append("<span class='right'></span>")
    if refreshing:
        out.append("</div><p class='note note--info'><b>노션을 읽는 중입니다.</b> "
                   "항목이 많아 몇 분 걸립니다. 이 화면은 자동으로 새로고침됩니다.</p>"
                   "<script>setTimeout(function(){location.reload()},15000)</script>")
    else:
        out.append("<form method='post' action='/reports/notion-todo/refresh' "
                   "style='margin:0'>"
                   "<button type='submit' class='btn'>노션 지금 다시 읽기</button>"
                   "</form></div>")

    if report is None:
        out.append("<p class='note note--todo'><b>저장된 내용이 없거나 옛 형식입니다.</b> "
                   "위 <b>「노션 지금 다시 읽기」</b>를 눌러주세요. 문구 형식이 바뀌면 "
                   "예전에 읽어둔 것은 쓰지 않습니다 — 그대로 쓰면 옛 문구가 카톡으로 "
                   "나갑니다.</p></div>")
        return "".join(out)
    if not report.get("ok"):
        out.append("<p class='note note--bad'>노션 읽기 실패 — "
                   f"{html.escape(str(report.get('error')))}</p></div>")
        return "".join(out)

    out.append("<p class='note'>카톡으로 나갈 문구 — <b>두 통</b>으로 갑니다</p>")
    out.append(_bubbles(report))
    out.append("<div class='btn-row'>"
               "<a class='btn btn--primary' href='/reports/notion-todo/send'>"
               "카카오톡 1건 발송</a>"
               "<span class='note'>(하루 1회 제한과 무관하게 강제 발송)</span>"
               "</div></div>")

    # ── 요일 판정 · 어제 대비 변경 ──
    picked = report.get("picked") or {}
    out.append("<div class='grid2'><div class='card'><div class='card-h'>"
               "<b>오늘 요일 블록을 제대로 골랐나 (확인 필요)</b>"
               "<span class='badge badge--warn'>눈으로 확인</span></div>"
               "<div class='kv'>"
               "<div class='kv-r'><span class='kv-k'>고른 요일</span>"
               f"<span class='kv-v'>{html.escape(str(picked.get('weekday') or '-'))}</span>"
               "<span class='kv-u'></span></div>"
               "<div class='kv-r'><span class='kv-k'>그 칸의 할 일</span>"
               f"<span class='kv-v num'>{picked.get('count', 0)}</span>"
               "<span class='kv-u'>건</span></div>"
               "<div class='kv-r'><span class='kv-k'>문서에 쌓인 같은 요일 칸</span>"
               f"<span class='kv-v num'>{picked.get('total_blocks_for_weekday', 0)}</span>"
               "<span class='kv-u'>개</span></div>"
               "<div class='kv-r kv-r--wide'><span class='kv-k'>그 칸의 첫 항목</span>"
               f"<span class='kv-v kv-v--txt'>"
               f"{html.escape(str(picked.get('first_item') or '-'))}</span></div>"
               "</div>"
               "<p class='note'>위 「그 칸의 첫 항목」이 <b>이번 주 해당 요일</b>의 "
               "첫 항목이 맞는지 노션과 대조해 주세요. 다르면 알려주시면 고르는 규칙을 "
               "바꾸겠습니다.</p>"
               + _raw("원본 값 그대로 보기", picked) + "</div>")

    changes = report.get("changes") or {}
    rows = "".join(
        "<div class='dl-r'>"
        f"<span class='dl-m'>{mark}</span><span class='dl-k'>{name}</span>"
        f"<span class='dl-v num'>{len(changes.get(key) or []):,}</span>"
        "<span class='dl-u'>건</span></div>"
        for key, mark, name in _CHANGE_LABELS)
    out.append("<div class='card'><div class='card-h'><b>어제 대비 변경</b>"
               "<span class='sub'>사진과 같은 기준 — 오늘 요일 칸만</span></div>"
               f"<div class='dl'>{rows}</div>")
    if report.get("changed_all") is not None:
        out.append(f"<p class='note'>페이지 전체로는 "
                   f"<b>{report['changed_all']}건</b>이 바뀌었고, 그중 "
                   "<b>오늘 요일 칸</b> 것만 보고합니다.</p>")
    if report.get("first_run"):
        out.append("<p class='note note--info'>아직 기준선이 없습니다(첫 실행). "
                   "첫 실행은 발송 없이 기준선만 저장하고, 다음 날부터 변경분이 "
                   "나갑니다.</p>")
    out.append("</div></div>")
    return "".join(out)


def _step_test(report) -> str:
    """6단계 — 지금 보내보기(옛 「테스트 발송」 화면)."""
    from lemouton.reports import shot_store

    st = shot_store.status()
    out = ["<div class='card'><div class='card-h'><b>지금 보내보기</b>"
           "<span class='sub'>지금 붙일 사진 · 무엇을 보낼까</span></div>"]

    if st["capture_requested"]:
        out.append("<p class='note note--info'><b>캡처를 요청했습니다.</b> 크롬 확장이 "
                   "최대 1분 안에 노션을 열어 찍습니다. (크롬에 탭이 잠깐 떴다 "
                   "사라집니다) 이 화면은 자동으로 새로고침됩니다.</p>"
                   "<script>setTimeout(function(){location.reload()},10000)</script>")
    elif st["fresh"] and st.get("file"):
        out.append("<p class='note'>사진이 준비돼 있습니다. 아래가 카톡에 붙을 "
                   "사진입니다.</p>"
                   f"<p><img src='/reports/notion-todo/shot/{html.escape(st['file'])}' "
                   "style='max-width:100%;border:1px solid #ddd;border-radius:8px'></p>")
    else:
        out.append("<p class='note note--todo'>아직 사진이 없습니다(또는 오래됐습니다). "
                   "아래 ①을 누르세요.</p>")

    out.append("<div class='btn-row'>"
               "<form method='post' action='/reports/notion-todo/test/capture' "
               "style='display:inline'>"
               "<button type='submit' class='btn'>① 지금 노션 캡처</button></form>"
               "<form method='post' action='/reports/notion-todo/test/send' "
               "style='display:inline'>"
               "<button type='submit' class='btn btn--primary'>② 지금 카톡 발송</button>"
               "</form></div>")
    out.append("<p class='note'>①을 누르고 사진이 뜬 뒤 ②를 누르면 <b>사진까지</b> "
               "갑니다. ①을 건너뛰고 ②만 누르면 <b>글만</b> 갑니다.</p>"
               "<p class='note'>테스트 발송은 <b>정해진 시각 발송과 무관</b>합니다 — "
               "테스트했다고 그날 회차가 건너뛰어지지 않습니다.</p>")
    out.append(_raw("캡처 상태 — 원본 값 그대로 보기", st))
    out.append("</div>")

    if report and report.get("ok"):
        out.append("<div class='card'><div class='card-h'><b>무엇을 보낼까</b>"
                   "<span class='sub'>노션을 마지막으로 읽은 시각: "
                   f"{html.escape(str(report.get('collected_at')))}</span></div>"
                   + _bubbles(report) + "</div>")
    else:
        out.append("<div class='card'><p class='note note--bad'>보낼 내용이 아직 "
                   "없습니다. <a href='/reports/notion-todo'>오늘 나갈 것</a>에서 "
                   "「노션 지금 다시 읽기」를 먼저 눌러주세요.</p></div>")
    return "".join(out)


def _step_history(days: int) -> str:
    """7단계 — 지나간 기록. 언제 무엇이 어떻게 바뀌었나."""
    from lemouton.reports import report_history

    labels = {"added": ("신규", "#1b6"), "completed": ("완료", "#1a7"),
              "reopened": ("체크해제", "#a60"), "removed": ("삭제", "#c00"),
              "edited": ("문구수정", "#06c")}
    grouped = report_history.by_day(days=days)
    out = ["<div class='card'><div class='card-h'><b>지나간 기록</b>"
           f"<span class='sub'>최근 {days}일</span>"
           "<span class='right'></span>"
           "<a class='btn btn--line' href='/reports/notion-todo?step=7&days=30'>"
           "30일치 보기</a></div>"]
    if not grouped:
        out.append("<p class='note'>아직 쌓인 이력이 없습니다. 발송이 한 번 이상 "
                   "돌면 여기에 쌓입니다.</p></div>")
        return "".join(out)

    for day, rows in grouped:
        total = sum(len(r.get('entries') or []) for r in rows)
        out.append(f"<div class='hist-h'><b>{html.escape(day)}</b> ({total}건)</div>")
        for row in rows:
            out.append("<div class='hist-h'>"
                       f"{html.escape(row.get('slot') or '')} 회차"
                       + ("" if row.get('sent') else
                          " <span class='badge badge--danger'>발송 실패</span>")
                       + "</div><div class='hist'>")
            for e in row.get('entries') or []:
                name, color = labels.get(e.get('kind'), ("변경", "#666"))
                when = e.get('edited_at')
                stamp = (f"<span style='color:#8B95A1'>{html.escape(when)}</span> "
                         if when else "")
                if e.get('kind') == 'edited':
                    detail = (f"<s>{html.escape(e.get('before') or '')}</s>"
                              f" → {html.escape(e.get('after') or '')}")
                else:
                    detail = html.escape(e.get('text') or '(빈 항목)')
                out.append("<div class='hist-r'><span class='dl-m'></span>"
                           f"<span class='hist-k' style='color:{color}'>{name}</span>"
                           f"<span class='hist-t'>{stamp}{detail}</span></div>")
            out.append("</div>")
    out.append("</div>")
    return "".join(out)


# ──────────────────────────────────────────────────────────────
# 점검 화면 — 왼쪽 7단계 + 오른쪽 내용
# ──────────────────────────────────────────────────────────────
def _lights(kakao: dict, notion_set: bool, times: list[str]) -> tuple[str, dict]:
    """맨 위 신호등 4칸 + 단계별 색 점.

    하나만 꺼져도 그날 보고가 통째로 빠진다 — 그걸 색 하나로 보이게 한다.
    """
    from lemouton.reports import shot_store
    from lemouton.reports import notion_todo as nt

    age = shot_store.age_minutes()
    fresh = bool(shot_store.public_url())
    cells = [
        ("노션 문서", "ok" if notion_set else "danger",
         nt.page_title() if notion_set else "시크릿이 없습니다"),
        ("카카오", "ok" if kakao["refresh_token_set"] else "danger",
         "로그인됨" if kakao["refresh_token_set"] else "로그인 필요"),
        ("발송 시각", "ok" if times else "danger",
         ", ".join(times) if times else "없음 — 보고가 안 나갑니다"),
        ("사진", "ok" if fresh else "warn",
         "붙습니다" if fresh else
         (f"{int(age)}분 전 것이라 오래됨" if age is not None else "찍은 적 없음")),
    ]
    html_ = ["<div class='lights'>"]
    for name, state, sub in cells:
        html_.append(f"<div class='light light--{state}'><span class='dot'></span>"
                     f"<div class='lt'><b>{html.escape(name)}</b>"
                     f"<span>{html.escape(sub)}</span></div></div>")
    html_.append("</div>")
    states = {"1": cells[0][1], "2": cells[2][1], "3": cells[1][1],
              "4": cells[3][1], "5": "ok", "6": "", "7": ""}
    return "".join(html_), states


def _flow(active: str, states: dict) -> str:
    out = ["<nav class='flow'>"]
    for no, name, sub in _STEPS:
        cls = " on" if no == active else ""
        st = states.get(no) or ""
        out.append(f"<a class='{('s-' + st) if st else ''}{cls}' "
                   f"href='/reports/notion-todo?step={no}'>"
                   f"<span class='flow-n'>{no}</span>"
                   f"<span class='flow-t'><b>{html.escape(name)}</b>"
                   f"<span>{html.escape(sub)}</span></span>"
                   "<span class='flow-d'></span></a>")
    out.append("</nav>")
    return "".join(out)


def _render(step: str) -> str:
    from shared import kakao_token
    from lemouton.reports import notion_todo as nt
    from lemouton.reports import report_schedule

    kakao = kakao_token.status()
    notion_set = bool(nt._token())
    times = report_schedule.times()
    lights, states = _lights(kakao, notion_set, times)

    # ★ 노션 한 바퀴는 몇 분 걸린다(블록마다 자식 조회 + 초당 3회 제한).
    #   요청 안에서 돌리면 Cloudflare 100초 상한에 걸려 화면이 죽는다 → 저장된
    #   마지막 결과만 즉시 보여주고, 새로 읽는 건 백그라운드로 돌린다.
    report = nt.load_last_report()
    refreshing = nt.is_refreshing()

    if step == "1":
        inner = _step_docs(kakao, notion_set)
    elif step == "2":
        inner = _step_time(times)
    elif step == "3":
        inner = _step_kakao(kakao)
    elif step == "4":
        inner = _step_shot()
    elif step == "6":
        inner = _step_test(report)
    elif step == "7":
        inner = _step_history(int(request.args.get('days') or 7))
    else:
        step = _DEFAULT_STEP
        inner = _step_today(report, refreshing)

    body = ("<h1>노션 일일보고</h1>"
            "<p class='pg-s'>"
            + (f"매일 {', '.join(times)} 에 카카오톡으로 나갑니다"
               if times else "발송 시각이 아직 없습니다")
            + "</p>"
            + lights
            + "<div class='flow-wrap'>" + _flow(step, states)
            + "<div class='body'>" + inner + "</div></div>")
    return _shell("노션 일일보고", body)


@bp.route('/reports/notion-todo')
def preview():
    """일하는 순서 7단계. 기본은 5단계(오늘 나갈 것). 카톡을 보내지 않는다."""
    return _render((request.args.get('step') or _DEFAULT_STEP).strip())


@bp.route('/reports/notion-todo/test')
def test_page():
    """옛 주소 — 6단계로 그대로 이어준다(북마크·옛 링크 보호)."""
    return _render("6")


@bp.route('/reports/notion-todo/history')
def history():
    """옛 주소 — 7단계. 카톡 「변경 이력 전체」 버튼이 여기로 온다."""
    return _render("7")


@bp.route('/reports/notion-todo/send')
def send_now():
    """지금 즉시 1건 발송. 정해진 시각 발송 기록은 건드리지 않는다(수동 확인용)."""
    return _do_send()


def _do_send():
    from shared.notifier import send_kakao_memo_detailed
    from lemouton.reports import notion_todo as nt
    from lemouton.reports import shot_store

    report = nt.load_last_report()
    if report is None or not report.get("ok"):
        return _page(
            "발송 실패",
            "<p>보낼 내용이 없습니다. 점검 화면에서 "
            "<b>「노션 지금 다시 읽기」</b>를 먼저 눌러 수집이 끝난 뒤 다시 시도하세요.</p>"
            + (f"<p>마지막 오류: {html.escape(str(report.get('error')))}</p>"
               if report else "")), 400
    image_url = shot_store.public_url() or ""
    if image_url:
        photo_link = nt.shot_url()
        photo_buttons = [("캡처 크게 보기", nt.shot_url()),
                         ("노션에서 보기", nt.link_url())]
    else:
        photo_link = nt.link_url()
        photo_buttons = [("노션에서 보기", nt.link_url())]
    res = send_kakao_memo_detailed(report["photo_message"], link_url=photo_link,
                                   buttons=photo_buttons, image_url=image_url)
    second = None
    if report.get("change_message"):
        second = send_kakao_memo_detailed(
            report["change_message"], link_url=nt.history_url(),
            button_title="변경 이력 전체")
        if not second["ok"]:
            res = second

    def _bubble(msg: str) -> str:
        return ("<pre class='kk-text' style='background:#FEE500;padding:16px;"
                f"border-radius:12px;margin:0 0 10px'>{html.escape(msg)}</pre>")

    # 보낸 것을 **둘 다** 보여준다. 한 통만 보여주면 나머지가 갔는지 알 수 없다.
    bubble = _bubble(report["photo_message"])
    if report.get("change_message"):
        bubble += _bubble(report["change_message"])

    if res["ok"]:
        note = ("<p>카카오톡 <b>나와의 채팅</b>을 확인해 주세요."
                + (" (사진 포함)" if image_url and not res.get("dropped_image") else " (글만)")
                + "</p>")
        if res.get("dropped_image"):
            note += ("<p class='note note--todo'>사진은 빼고 보냈습니다 — 카카오가 그 사진을 "
                     "거부했습니다. 글 내용은 그대로입니다.</p>")
        if res.get("dropped_link"):
            note += ("<p class='note note--todo'>노션 링크 버튼은 빼고 보냈습니다 — "
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
        body += f"<p class='note note--bad'>{hint}</p>"
    else:
        body += ("<p class='note note--bad'>발송에 실패했습니다. 아래 원문을 "
                 "그대로 알려주시면 원인을 짚어드리겠습니다.</p>")
    body += (f"<p>카카오 응답 코드: <b>{res.get('status')}</b></p>"
             f"<pre class='box'>{html.escape(raw)}</pre>")
    return _page("발송 실패", body), 500


@bp.route('/reports/notion-todo/refresh', methods=['POST'])
def refresh():
    """노션 재수집을 백그라운드로 시작하고 점검 화면으로 되돌린다."""
    from lemouton.reports import notion_todo as nt

    nt.start_refresh()
    return redirect('/reports/notion-todo')


# ──────────────────────────────────────────────────────────────
# 발송 시각표 · 캡처
# ──────────────────────────────────────────────────────────────
@bp.route('/reports/notion-todo/schedule', methods=['POST'])
def save_schedule():
    """발송 시각 교체. 한 줄에 하나씩(HH:MM)."""
    from lemouton.reports import report_schedule

    raw = (request.form.get('times') or '').replace(',', '\n')
    good, bad = report_schedule.set_times(raw.splitlines())
    body = f"<p>저장된 시각: <b>{html.escape(', '.join(good)) or '없음'}</b></p>"
    if bad:
        body += ("<p class='note note--bad'>형식이 아니라 버린 값: "
                 f"{html.escape(', '.join(bad))} — <code>09:30</code> 처럼 적어주세요.</p>")
    if not good:
        body += "<p class='note note--bad'>시각이 하나도 없으면 보고가 나가지 않습니다.</p>"
    body += "<p><a href='/reports/notion-todo?step=2'>← 발송 시각으로</a></p>"
    return _page("발송 시각 저장", body)


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
    requested = shot_store.is_requested()
    return jsonify(
        # 화면에서 「지금 찍어줘」를 눌렀으면 신선도와 무관하게 새로 찍는다
        #   (테스트는 방금 화면 상태를 보고 싶은 것).
        needed=bool(requested or (upcoming and not shot_store.is_fresh())),
        requested=requested,
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


@bp.route('/reports/notion-todo/test/capture', methods=['POST'])
def test_capture():
    """확장에게 「지금 찍어줘」 표시를 남기고 6단계로 되돌린다."""
    from lemouton.reports import shot_store

    shot_store.request_capture()
    return redirect('/reports/notion-todo?step=6')


@bp.route('/reports/notion-todo/test/send', methods=['POST'])
def test_send():
    """지금 1건 발송(테스트). 시각별 발송 기록은 건드리지 않는다."""
    return _do_send()


@bp.route('/reports/notion-todo/open')
def open_notion():
    """카톡에서 눌렀을 때 노션으로 넘겨주는 자리.

    카카오가 등록된 웹 도메인의 링크만 살려두기 때문에, 우리 도메인으로 한 번 받고
    노션으로 보낸다 — 사장님 도메인 하나만 등록하면 된다.
    """
    from lemouton.reports import notion_todo as nt

    return redirect(nt.page_url())


@bp.route('/reports/notion-todo/shot/latest')
def latest_shot():
    """방금 보낸 사진을 크게 보는 자리(카톡 버튼이 여기로 온다)."""
    from lemouton.reports import shot_store

    meta = shot_store.load_meta()
    path = shot_store.path_of((meta or {}).get("file") or "")
    if not path:
        return _page("사진 없음", "<p>아직 캡처가 없습니다.</p>"), 404
    return send_file(path, mimetype='image/png')


@bp.route('/api/reports/notion-todo')
def api_preview():
    """기계 판독용 — 미리보기 내용을 JSON 으로."""
    from lemouton.reports import notion_todo as nt

    report = nt.load_last_report() or {"ok": False, "error": "아직 수집 전"}
    report["refreshing"] = nt.is_refreshing()
    return jsonify(report), (200 if report.get("ok") else 503)
