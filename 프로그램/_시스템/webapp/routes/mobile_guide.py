# -*- coding: utf-8 -*-
"""폰 크롤 가이드 읽기 화면 — `/mobile/guide` (F-2 · 사장님 확정 「읽기용 목차」 fF2).

목차(검색칸 + 번호 줄) → 절 하나를 폰 글자 크기로 읽는다.

[중요] 내용의 단일 원천 = `docs/크롤링-가이드.md` (방향 복귀 정본). 이 모듈은
  **렌더 시점마다** 그 파일을 읽는다 — 여기 어떤 문장도 복사해 두지 않는다.
  md 가 바뀌면 폰 화면도 0수정으로 같이 바뀐다(시험이 경로 갈아끼우기로 못 박음).
  경로도 사본을 안 만든다 — sourcing_guide._GUIDE_MD 하나를 그대로 쓴다.

[중요] PC 렌더 재사용 조사 결과(정직 기록): /sourcing-guide/map 의 「보기」는
  md→HTML 변환이 아니라 **손으로 지은 203KB HTML**(정본과는 drift 검사로만 동기화)
  이고, 「원문」 토글은 /map.md 를 평문 그대로 보여줄 뿐이다 — 재사용할 md→HTML
  파이프라인이 저장소에 없다. 그래서 여기의 변환기는 **표시용 최소판**을 새로
  둔다(제목·코드 펜스·표·인용·목록·굵게·인라인 코드만 — 내용 로직 0, 문장 복제 0).

권한: PC 가이드 전체(/sourcing-guide/*)가 team-share-dev 에서 admin 게이트다
  (sourcing_guide._admin_only). 폰만 열면 두 화면이 다른 답을 낸다 — 같은 게이트.
"""
from __future__ import annotations

import html as _html
import os
import re

from flask import Blueprint, abort, render_template

bp = Blueprint("mobile_guide", __name__, url_prefix="/mobile/guide")


@bp.before_request
def _admin_only():
    """PC 원천(/sourcing-guide/*)과 같은 admin 정책.

    정직 정정(최종 검토 Minor 6): **공유되는 건 enforce_admin** 이고, 이 env
    체크 4줄은 sourcing_guide._admin_only 의 **패턴 사본**이다(blueprint
    before_request 는 blueprint 마다 달아야 해서 함수 자체는 공유가 안 된다).
    """
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


def _md_path() -> str:
    """정본 경로 — sourcing_guide 의 상수 하나만 원천으로 쓴다(경로 사본 금지)."""
    from webapp.routes import sourcing_guide as sg
    return sg._GUIDE_MD


# ════════════════════════════════════════════════════════════
#  md 구조 파싱 — 목차는 `## ` 헤딩에서 렌더 시점에 나온다
# ════════════════════════════════════════════════════════════

_H2 = re.compile(r'^## +(.+?)\s*$')
#: 절 키 = 헤딩의 § 토큰(§0·§2-b …) — 절 순서가 바뀌어도 주소가 안 썩는다.
_KEY = re.compile(r'§\s*([0-9][0-9a-zA-Z\-]*)')


def _inline_text(s: str) -> str:
    """요약 한 줄용 — 마크업만 벗긴 순수 글자."""
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'`([^`]*)`', r'\1', s)
    s = re.sub(r'~~(.+?)~~', r'\1', s)
    s = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', s)
    return s.strip()


def _first_desc(lines: list[str]) -> str:
    """절의 한 줄 요약 — 첫 산문 줄에서 유도한다(따로 지어 적지 않는다)."""
    for ln in lines:
        t = ln.strip()
        if (not t or t == '---' or t.startswith('#')
                or t.startswith('|') or t.startswith('```')):
            continue
        t = t.lstrip('> ').strip()
        if not t:
            continue
        t = _inline_text(t)
        # 「🟢 쉬운 설명 — …」 같은 머리 표식은 뒤쪽 본문만 남긴다.
        if '—' in t[:16]:
            t = t.split('—', 1)[1].strip()
        return (t[:48] + '…') if len(t) > 48 else t
    return ''


def load_sections() -> list[dict]:
    """정본 md → 절 목록 [{key, num, title, desc, body}] — 매 요청 파일에서."""
    with open(_md_path(), encoding='utf-8') as f:
        text = f.read()

    intro: list[str] = []
    secs: list[dict] = []
    cur: dict | None = None
    for ln in text.splitlines():
        m = _H2.match(ln)
        if m:
            cur = {'title_raw': m.group(1).strip(), 'lines': []}
            secs.append(cur)
        elif cur is None:
            intro.append(ln)
        else:
            cur['lines'].append(ln)

    out: list[dict] = []
    if any(l.strip() for l in intro):
        # 머리말 — 제목도 파일의 `# ` 줄에서 온다.
        t = next((l.lstrip('#').strip() for l in intro if l.startswith('# ')), '머리말')
        out.append({'key': 'intro', 'title': t,
                    'desc': _first_desc(intro), 'body': '\n'.join(intro)})
    used: set[str] = set()
    for i, s in enumerate(secs):
        km = _KEY.search(s['title_raw'])
        key = km.group(1) if km else f'sec{i}'
        if key in used:                      # 같은 § 가 두 번이면 뒤엣것에 번호 접미
            key = f'{key}-{i}'
        used.add(key)
        title = re.sub(r'^§\s*[0-9][0-9a-zA-Z\-]*\.?\s*', '', s['title_raw']).strip() \
            or s['title_raw']
        out.append({'key': key, 'title': title,
                    'desc': _first_desc(s['lines']), 'body': '\n'.join(s['lines'])})
    for n, s in enumerate(out, 1):
        s['num'] = n
    return out


# ════════════════════════════════════════════════════════════
#  표시용 최소 변환 — 코드 펜스·표는 자기 그릇 안에서 가로 스크롤
# ════════════════════════════════════════════════════════════

def _inline_html(s: str) -> str:
    # 🔴 quote=True — 아래 링크 처리가 이 결과를 href="…" **속성 안**에도 넣는다.
    #   quote=False 면 URL 의 " 가 속성을 탈출해 onclick 같은 임의 속성이 주입된다
    #   (최종 검토에서 실행으로 확인된 구멍 — 시험이 속성 파싱으로 못 박음).
    s = _html.escape(s, quote=True)
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'~~(.+?)~~', r'<del>\1</del>', s)

    def _lnk(m: re.Match) -> str:
        # u 는 위 escape(quote=True)를 이미 거쳤다 — " 는 &quot; 라 속성 탈출 불가.
        t, u = m.group(1), m.group(2)
        if u.startswith(('http://', 'https://', '/')):
            return f'<a href="{u}" target="_blank" rel="noopener">{t}</a>'
        return t                              # 저장소 상대경로 — 폰에선 링크가 못 된다

    return re.sub(r'\[([^\]]*)\]\(([^)\s]+)\)', _lnk, s)


def _table_html(rows: list[str]) -> str:
    """셀 나누기는 생 `|` 기준 — 인라인 코드 속 | 는 셀이 갈릴 수 있다(표시용 한계)."""
    trs: list[str] = []
    for r_i, r in enumerate(rows):
        cells = [c.strip() for c in r.strip().strip('|').split('|')]
        if cells and all(re.fullmatch(r':?-{2,}:?', c or '---') for c in cells):
            continue                          # 헤더 구분줄(---)은 그리지 않는다
        tag = 'th' if r_i == 0 else 'td'
        trs.append('<tr>' + ''.join(f'<{tag}>{_inline_html(c)}</{tag}>'
                                    for c in cells) + '</tr>')
    return '<div class="mg-tblwrap"><table class="mg-tbl">' + ''.join(trs) \
        + '</table></div>'


def render_md(body: str) -> str:
    """절 본문 md → 폰 표시 HTML.

    내용은 전부 escape(quote=True) 를 거친다 — 본문 컨텍스트(원문 HTML 실행)와
    속성 컨텍스트(링크 href 의 " 탈출) **둘 다** 막는다.
    """
    out: list[str] = []
    para: list[str] = []
    lines = body.splitlines()
    i, n = 0, len(lines)

    def flush() -> None:
        if para:
            out.append('<p>' + '<br>'.join(_inline_html(x) for x in para) + '</p>')
            para.clear()

    while i < n:
        t = lines[i].strip()
        if t.startswith('```'):               # 코드 펜스 → <pre> (가로 스크롤 그릇)
            flush()
            i += 1
            code: list[str] = []
            while i < n and not lines[i].strip().startswith('```'):
                code.append(lines[i])
                i += 1
            i += 1                            # 닫는 펜스
            out.append('<pre class="mg-code">' + _html.escape('\n'.join(code))
                       + '</pre>')
            continue
        if t.startswith('|'):                 # 표 → 가로 스크롤 그릇
            flush()
            rows: list[str] = []
            while i < n and lines[i].strip().startswith('|'):
                rows.append(lines[i])
                i += 1
            out.append(_table_html(rows))
            continue
        if not t:
            flush()
            i += 1
            continue
        if t == '---':
            flush()
            out.append('<hr>')
            i += 1
            continue
        m = re.match(r'^(#{3,6}) +(.*)$', t)
        if m:
            flush()
            lvl = len(m.group(1))
            out.append(f'<h{lvl} class="mg-h">{_inline_html(m.group(2))}</h{lvl}>')
            i += 1
            continue
        if t.startswith('>'):                 # 인용 덩어리
            flush()
            q: list[str] = []
            while i < n and lines[i].strip().startswith('>'):
                q.append(lines[i].strip().lstrip('>').strip())
                i += 1
            out.append('<blockquote class="mg-q">'
                       + '<br>'.join(_inline_html(x) for x in q) + '</blockquote>')
            continue
        if re.match(r'^[-*] +', t):           # 목록
            flush()
            items: list[str] = []
            while i < n and re.match(r'^\s*[-*] +', lines[i]):
                items.append(re.sub(r'^\s*[-*] +', '', lines[i].strip()))
                i += 1
            out.append('<ul class="mg-ul">'
                       + ''.join(f'<li>{_inline_html(x)}</li>' for x in items)
                       + '</ul>')
            continue
        para.append(t)
        i += 1
    flush()
    return '\n'.join(out)


# ════════════════════════════════════════════════════════════
#  라우트
# ════════════════════════════════════════════════════════════

@bp.route("")
def toc():
    """목차 — 검색칸 + 번호 줄(fF2 구조). 검색은 이 목록의 클라이언트 필터다."""
    secs = load_sections()
    return render_template(
        'mobile/guide_toc.html',
        sections=[{k: s[k] for k in ('key', 'num', 'title', 'desc')} for s in secs])


@bp.route("/s/<key>")
def section(key: str):
    """절 하나 읽기 — 본문은 지금 이 순간의 정본 md 에서 온다."""
    secs = load_sections()
    idx = next((i for i, s in enumerate(secs) if s['key'] == key), None)
    if idx is None:
        abort(404)
    cur = secs[idx]
    prev_s = ({'key': secs[idx - 1]['key'], 'title': secs[idx - 1]['title']}
              if idx > 0 else None)
    next_s = ({'key': secs[idx + 1]['key'], 'title': secs[idx + 1]['title']}
              if idx + 1 < len(secs) else None)
    return render_template('mobile/guide_section.html',
                           sec={'key': cur['key'], 'num': cur['num'],
                                'title': cur['title']},
                           body_html=render_md(cur['body']),
                           prev_s=prev_s, next_s=next_s,
                           back_url='/mobile/guide')
