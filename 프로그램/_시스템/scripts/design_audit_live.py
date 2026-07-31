# -*- coding: utf-8 -*-
"""디자인 전수 감사 — 실브라우저로 화면마다 「눈에 보이는 것」을 직접 잰다.

왜 만들었나
    화면이 113개, 타입이 4개다. 눈으로는 452번을 못 본다. 지난 대비 보정이
    `/orders` 한 화면 실측만으로 이뤄져서, 나머지 화면에 결함이 그대로 남았다
    (사장님이 마진계산기의 흰 카드 잔재·검정 배경의 검정 글씨를 발견).

무엇을 재나 — 사장님 지적 4가지를 한 번에 잡는다
    a. 어두운 타입인데 밝은(흰) 배경이 남은 곳       → 「화이트 타입 잔재」
    b. 문서 폭이 창 폭을 넘어 화면 틀이 통째로 밀림  → 「가로 넘침」
    c. 글자색과 배경색 대비가 모자라 안 읽힘         → 「대비 미달」(4.5 기준)
    d. 규칙에 없는 글자 크기(11px 미만 등)           → 「너무 작은 글자」

★ 정확도의 핵심 — 배경은 「역산」해야 한다.
    요소의 background-color 만 읽으면 안 된다. 반투명이면 그 밑에 깔린 색이
    비쳐 보이므로, 조상 쪽으로 올라가며 알파를 합성해 **눈에 실제로 보이는 색**을
    구해야 한다. 이걸 안 하면 실제 대비 16.9 인 자리가 1.09 로 잘못 나온다
    (2026-07-31 실측에서 확인).

쓰는 법
    # 라이브 (실제 데이터가 있어야 표 안의 결함이 보인다)
    python scripts/design_audit_live.py --기준 https://mou-m.com

    # 로컬
    python scripts/design_audit_live.py --기준 http://localhost:5099

    python scripts/design_audit_live.py --기준 ... --타입 mono,layer   # 일부만
    python scripts/design_audit_live.py --기준 ... --화면 /orders/,/    # 일부만
    python scripts/design_audit_live.py --기준 ... --대조 이전결과폴더   # 무손실 대조

결과
    _design_audit/<타입>.json  — 화면별 원자료(결함 목록·최악 사례)
    _design_audit/요약.txt      — 사람이 읽는 요약
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

_시스템 = pathlib.Path(__file__).resolve().parents[1]
if str(_시스템) not in sys.path:
    sys.path.insert(0, str(_시스템))

_결과폴더 = _시스템.parents[1] / '_design_audit'

# 대비 합격선 — docs/디자인-규칙.md 정본. 큰 글자는 3.0 (WCAG AA)
_대비기준 = 4.5
_대비기준_큰글자 = 3.0
_최소글자 = 11          # 애플 실측 하한(법적 고지)
_화면당_표본 = 40        # 화면마다 최악 몇 개까지 남길지


# ══════════════════════════════════════════════════════════════════════════
# 화면 목록 — Flask 라우트 표에서 뽑는다(사람이 손으로 적으면 반드시 빠진다)
# ══════════════════════════════════════════════════════════════════════════
def 화면목록() -> list[str]:
    os.environ.setdefault('ENVIRONMENT', 'team-share-dev')
    from app import create_app
    app = create_app()
    길 = set()
    for r in app.url_map.iter_rules():
        if 'GET' not in (r.methods or set()):
            continue
        if r.arguments:                     # <id> 같은 인자가 필요한 길은 건너뛴다
            continue
        p = str(r.rule)
        if p.startswith('/static') or p.startswith('/api'):
            continue
        if '/api/' in p or p.endswith('.json') or p.endswith('.md'):
            continue
        if '.xlsx' in p or '/download' in p or '/export' in p:
            continue
        길.add(p)
    # 주문관리는 탭마다 화면이 다르다 — 탭도 따로 본다
    길.update(['/orders/?tab=list', '/orders/?tab=cs',
               '/orders/?tab=margin', '/orders/?tab=ship'])
    return sorted(길)


# ══════════════════════════════════════════════════════════════════════════
# 측정 JS — 브라우저 안에서 도는 부분
# ══════════════════════════════════════════════════════════════════════════
_측정JS = r"""
(옵션) => {
  const 대비기준 = 옵션.대비기준, 대비기준_큰글자 = 옵션.대비기준_큰글자;
  const 최소글자 = 옵션.최소글자, 표본수 = 옵션.표본수, 어두운타입 = 옵션.어두운타입;

  // ── 색 파싱 ────────────────────────────────────────────────────────
  function 색분해(s) {
    if (!s) return null;
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const v = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    if (v.length < 3 || v.some(isNaN)) return null;
    return { r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1 };
  }
  // 위 색(알파 있음)을 아래 색(불투명) 위에 얹었을 때 눈에 보이는 색
  function 겹치기(위, 아래) {
    const a = 위.a;
    return { r: 위.r * a + 아래.r * (1 - a),
             g: 위.g * a + 아래.g * (1 - a),
             b: 위.b * a + 아래.b * (1 - a), a: 1 };
  }
  function 밝기(c) {
    const f = x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }
  function 대비(c1, c2) {
    const a = 밝기(c1), b = 밝기(c2);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  }

  // ★ 핵심 — 조상을 거슬러 올라가며 반투명을 합성해 「실제로 보이는 배경」을 구한다.
  //   그림(background-image)이 깔려 있으면 색으로 판정할 수 없으므로 그렇게 표시한다.
  function 보이는배경(el) {
    let 쌓임 = [];      // 위에서 아래로
    let n = el;
    let 그림있음 = false;
    while (n && n.nodeType === 1) {
      const cs = getComputedStyle(n);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') 그림있음 = true;
      const c = 색분해(cs.backgroundColor);
      if (c && c.a > 0) {
        쌓임.push(c);
        if (c.a >= 0.999) break;     // 불투명 — 여기서 끝
      }
      n = n.parentElement;
    }
    // 맨 밑바탕: 못 찾았으면 흰색으로 본다(브라우저 기본)
    let 바탕 = { r: 255, g: 255, b: 255, a: 1 };
    if (쌓임.length && 쌓임[쌓임.length - 1].a >= 0.999) 바탕 = 쌓임.pop();
    for (let i = 쌓임.length - 1; i >= 0; i--) 바탕 = 겹치기(쌓임[i], 바탕);
    return { 색: 바탕, 그림있음 };
  }

  // 이모지·그림문자는 글꼴이 제 색으로 그린다 — color 를 안 따르므로 대비를 잴 수 없다.
  // (이걸 안 빼면 재고 목록의 '👟' 하나가 9,996곳으로 불어나 진짜 문제를 덮는다.)
  const 그림문자만 = (s) => !/[\p{L}\p{N}]/u.test(s) || !/[^\p{Emoji_Presentation}\p{Extended_Pictographic}\s]/u.test(s);

  function 길찾기(el) {
    const 조각 = [];
    let n = el;
    for (let i = 0; n && n.nodeType === 1 && i < 4; i++, n = n.parentElement) {
      let s = n.tagName.toLowerCase();
      if (n.id) { 조각.unshift(s + '#' + n.id); break; }
      const cls = (n.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
      if (cls.length) s += '.' + cls.join('.');
      조각.unshift(s);
    }
    return 조각.join(' > ');
  }

  // ★ 원인별로 묶는다 — 같은 규칙 하나가 수천 곳으로 불어나므로,
  //   「곳 수」가 아니라 「원인 수」로 봐야 실제로 고칠 수 있다.
  //   묶는 열쇠 = 요소의 정체(태그+클래스) + 글자색 + 배경색
  const 원인묶음 = new Map();
  function 원인담기(열쇠, 표본) {
    let v = 원인묶음.get(열쇠);
    if (!v) { v = { 열쇠, 수: 0, 표본 }; 원인묶음.set(열쇠, v); }
    v.수++;
    if (표본.대비 !== undefined && 표본.대비 < (v.표본.대비 ?? 99)) v.표본 = 표본;  // 최악을 대표로
  }
  function 정체(el) {
    const cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 3);
    return el.tagName.toLowerCase() + (cls.length ? '.' + cls.join('.') : '');
  }

  // ── 1) 글자 대비 · 글자 크기 ────────────────────────────────────────
  const 대비미달 = [], 작은글자 = [];
  let 글자수 = 0, 그림문자건너뜀 = 0;
  const 걷기 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const 본요소 = new Set();
  let t;
  while ((t = 걷기.nextNode())) {
    const 글 = (t.nodeValue || '').trim();
    if (!글) continue;
    if (그림문자만(글)) { 그림문자건너뜀++; continue; }
    const el = t.parentElement;
    if (!el) continue;
    if (본요소.has(el)) continue;
    본요소.add(el);

    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;      // 안 보이는 것은 안 센다

    const 크기 = parseFloat(cs.fontSize) || 0;
    const 굵기 = parseInt(cs.fontWeight, 10) || 400;
    글자수++;

    if (크기 && 크기 < 최소글자) {
      작은글자.push({ 길: 길찾기(el), 글: 글.slice(0, 40), 크기: Math.round(크기 * 10) / 10 });
    }

    const 글자색 = 색분해(cs.color);
    if (!글자색) continue;
    const 배경 = 보이는배경(el);
    // 글자색 자체가 반투명이면 배경 위에 얹어 실제 보이는 색으로
    const 실제글자색 = 글자색.a < 0.999 ? 겹치기(글자색, 배경.색) : 글자색;
    const 값 = 대비(실제글자색, 배경.색);
    const 큰글자 = 크기 >= 24 || (크기 >= 18.66 && 굵기 >= 700);
    const 기준 = 큰글자 ? 대비기준_큰글자 : 대비기준;
    if (값 < 기준) {
      const 배경글 = `rgb(${Math.round(배경.색.r)}, ${Math.round(배경.색.g)}, ${Math.round(배경.색.b)})`;
      const 한건 = {
        길: 길찾기(el), 글: 글.slice(0, 40),
        대비: Math.round(값 * 100) / 100, 기준,
        글자색: cs.color, 배경색: 배경글,
        크기: Math.round(크기 * 10) / 10, 굵기,
        배경에그림: 배경.그림있음,
      };
      대비미달.push(한건);
      원인담기('대비|' + 정체(el) + '|' + cs.color + '|' + 배경글, 한건);
    }
  }

  // ── 2) 어두운 타입에 남은 밝은(흰) 배경 ────────────────────────────
  const 흰잔재 = [];
  if (어두운타입) {
    const 요소들 = document.body.querySelectorAll('*');
    for (const el of 요소들) {
      // 디자인 전환 드롭버튼은 일부러 밝다 — 토큰을 안 쓰는 안전망이라
      // 어두운 타입에서도 흰 알약으로 남아야 되돌리기 통로가 보인다.
      if (el.closest('#dmenu')) continue;
      const cs = getComputedStyle(el);
      const c = 색분해(cs.backgroundColor);
      if (!c || c.a < 0.5) continue;              // 배경을 실제로 칠한 것만
      const r = el.getBoundingClientRect();
      if (r.width < 40 || r.height < 20) continue; // 점 같은 것은 뺀다
      const 보임 = 보이는배경(el);
      const L = 밝기(보임.색);
      if (L > 0.5) {                               // 밝은 판 = 흰 카드 잔재
        const 배경글 = `rgb(${Math.round(보임.색.r)}, ${Math.round(보임.색.g)}, ${Math.round(보임.색.b)})`;
        const 한건 = {
          길: 길찾기(el), 배경색: 배경글,
          밝기: Math.round(L * 1000) / 1000,
          넓이: Math.round(r.width) + 'x' + Math.round(r.height),
        };
        흰잔재.push(한건);
        원인담기('흰잔재|' + 정체(el) + '|' + 배경글, 한건);
      }
    }
  }

  // ── 3) 가로 넘침 ───────────────────────────────────────────────────
  const 문서폭 = document.documentElement.scrollWidth;
  const 창폭 = document.documentElement.clientWidth;
  const 넘침 = [];
  if (문서폭 > 창폭 + 1) {
    // 어떤 요소가 창 밖으로 나갔는지 — 스크롤 상자 안에 든 것은 정상이므로 뺀다
    for (const el of document.body.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (r.right <= 창폭 + 1) continue;
      if (r.width < 2 || r.height < 2) continue;
      let 스크롤상자안 = false;
      for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
        const ov = getComputedStyle(n).overflowX;
        if (ov === 'auto' || ov === 'scroll' || ov === 'hidden') { 스크롤상자안 = true; break; }
      }
      if (스크롤상자안) continue;
      넘침.push({ 길: 길찾기(el), 오른쪽끝: Math.round(r.right), 폭: Math.round(r.width) });
      if (넘침.length >= 12) break;
    }
  }

  대비미달.sort((a, b) => a.대비 - b.대비);
  흰잔재.sort((a, b) => b.밝기 - a.밝기);

  const 원인들 = [...원인묶음.values()].sort((a, b) => b.수 - a.수);

  return {
    글자수, 그림문자건너뜀,
    대비미달_수: 대비미달.length, 대비미달: 대비미달.slice(0, 표본수),
    흰잔재_수: 흰잔재.length,   흰잔재: 흰잔재.slice(0, 표본수),
    작은글자_수: 작은글자.length, 작은글자: 작은글자.slice(0, 표본수),
    원인_수: 원인들.length, 원인들: 원인들.slice(0, 60),
    문서폭, 창폭, 가로넘침: 문서폭 > 창폭 + 1, 넘친요소: 넘침,
  };
}
"""


# ══════════════════════════════════════════════════════════════════════════
async def _모드바꾸기(page, 기준: str, 모드: str) -> bool:
    """서버에 저장되는 값이라 한 번만 바꾸면 이후 모든 화면에 적용된다."""
    결과 = await page.evaluate(
        """async ([기준, 모드]) => {
            const body = new URLSearchParams({mode: 모드, next: '/'});
            const r = await fetch(기준 + '/auth/design-mode', {
                method: 'POST', credentials: 'same-origin',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: body.toString(),
            });
            return {ok: r.ok, status: r.status};
        }""",
        [기준.rstrip('/'), 모드],
    )
    return bool(결과.get('ok'))


async def _한화면(page, 기준: str, 길: str, 옵션: dict) -> dict:
    주소 = 기준.rstrip('/') + 길
    try:
        r = await page.goto(주소, wait_until='domcontentloaded', timeout=45000)
        상태 = r.status if r else 0
    except Exception as e:
        return {'화면': 길, '상태': 'ERR', '오류': str(e)[:200]}
    if 상태 >= 400:
        return {'화면': 길, '상태': 상태}
    try:
        # 늦게 그려지는 표(자바스크립트로 채우는 화면)를 조금 기다린다
        await page.wait_for_timeout(1200)
        잰것 = await page.evaluate(_측정JS, 옵션)
    except Exception as e:
        return {'화면': 길, '상태': 상태, '오류': str(e)[:200]}
    잰것['화면'] = 길
    잰것['상태'] = 상태
    return 잰것


async def _한타입(브라우저, 기준: str, 모드: str, 화면들: list[str], 동시: int) -> dict:
    from webapp.design_mode import MODES
    이름, _설명, 어두운가 = MODES[모드]
    ctx = await 브라우저.new_context(viewport={'width': 1920, 'height': 1080})
    page0 = await ctx.new_page()
    await page0.goto(기준.rstrip('/') + '/', wait_until='domcontentloaded', timeout=45000)
    if not await _모드바꾸기(page0, 기준, 모드):
        print(f'  ⚠ {이름}: 타입 전환 실패 — 로그인 상태를 확인하세요')
    옵션 = {'대비기준': _대비기준, '대비기준_큰글자': _대비기준_큰글자,
            '최소글자': _최소글자, '표본수': _화면당_표본, '어두운타입': bool(어두운가)}

    결과 = []
    큐 = list(화면들)
    페이지들 = [page0] + [await ctx.new_page() for _ in range(max(0, 동시 - 1))]
    잠금 = asyncio.Lock()

    async def 일꾼(p):
        while True:
            async with 잠금:
                if not 큐:
                    return
                길 = 큐.pop(0)
                남음 = len(큐)
            r = await _한화면(p, 기준, 길, 옵션)
            결과.append(r)
            표시 = ''
            if r.get('대비미달_수'):
                표시 += f" 대비{r['대비미달_수']}"
            if r.get('흰잔재_수'):
                표시 += f" 흰잔재{r['흰잔재_수']}"
            if r.get('가로넘침'):
                표시 += ' 가로넘침'
            if r.get('작은글자_수'):
                표시 += f" 작은글자{r['작은글자_수']}"
            print(f'  [{이름}] {길:<46} {r.get("상태")}{표시}  (남음 {남음})', flush=True)

    await asyncio.gather(*[일꾼(p) for p in 페이지들])
    await ctx.close()
    결과.sort(key=lambda x: x['화면'])
    return {'모드': 모드, '이름': 이름, '어두운타입': bool(어두운가), '화면들': 결과}


async def _달리기(기준: str, 모드들: list[str], 화면들: list[str], 동시: int, 헤드리스: bool):
    from playwright.async_api import async_playwright
    _결과폴더.mkdir(parents=True, exist_ok=True)
    모음 = {}
    async with async_playwright() as pw:
        브라우저 = await pw.chromium.launch(headless=헤드리스)
        try:
            for 모드 in 모드들:
                print(f'\n── {모드} ── 화면 {len(화면들)}개', flush=True)
                r = await _한타입(브라우저, 기준, 모드, 화면들, 동시)
                모음[모드] = r
                (_결과폴더 / f'{모드}.json').write_text(
                    json.dumps(r, ensure_ascii=False, indent=1), encoding='utf-8')
        finally:
            # 다음 사람이 라이브를 안전망으로 보게 되돌려 둔다
            try:
                ctx = await 브라우저.new_context()
                p = await ctx.new_page()
                await p.goto(기준.rstrip('/') + '/', wait_until='domcontentloaded', timeout=30000)
                await _모드바꾸기(p, 기준, 'current')
                await ctx.close()
            except Exception:
                pass
            await 브라우저.close()
    return 모음


def _요약쓰기(모음: dict) -> str:
    줄 = []
    줄.append('디자인 전수 감사 요약')
    줄.append('=' * 78)
    for 모드, r in 모음.items():
        화면들 = r['화면들']
        대비 = sum(x.get('대비미달_수', 0) for x in 화면들)
        흰 = sum(x.get('흰잔재_수', 0) for x in 화면들)
        작 = sum(x.get('작은글자_수', 0) for x in 화면들)
        넘 = [x['화면'] for x in 화면들 if x.get('가로넘침')]
        오류 = [x['화면'] for x in 화면들 if x.get('오류') or x.get('상태') in ('ERR',)]
        줄.append('')
        줄.append(f"■ {r['이름']} ({모드}) — 화면 {len(화면들)}개")
        줄.append(f"   대비 미달 {대비:,}곳 · 흰 잔재 {흰:,}곳 · 작은 글자 {작:,}곳 · 가로 넘침 {len(넘)}화면")
        if 넘:
            줄.append('   가로 넘침 화면: ' + ', '.join(넘[:12]) + (' …' if len(넘) > 12 else ''))
        if 오류:
            줄.append('   ⚠ 못 잰 화면: ' + ', '.join(오류[:10]) + (' …' if len(오류) > 10 else ''))
        나쁜순 = sorted((x for x in 화면들 if x.get('대비미달_수')),
                        key=lambda x: -x['대비미달_수'])[:10]
        if 나쁜순:
            줄.append('   대비 미달이 많은 화면:')
            for x in 나쁜순:
                최악 = x['대비미달'][0] if x['대비미달'] else None
                꼬리 = f" (최악 {최악['대비']} · {최악['글']!r})" if 최악 else ''
                줄.append(f"     {x['대비미달_수']:>5,}곳  {x['화면']}{꼬리}")
        흰순 = sorted((x for x in 화면들 if x.get('흰잔재_수')),
                      key=lambda x: -x['흰잔재_수'])[:10]
        if 흰순:
            줄.append('   흰 배경이 남은 화면:')
            for x in 흰순:
                줄.append(f"     {x['흰잔재_수']:>5,}곳  {x['화면']}")

        # ★ 여기가 실제 작업 목록이다 — 같은 규칙 하나가 수천 곳으로 불어나므로
        #   「곳 수」가 아니라 「원인」을 고쳐야 한다.
        묶음 = {}
        for x in 화면들:
            for c in x.get('원인들', []):
                v = 묶음.setdefault(c['열쇠'], {'수': 0, '표본': c['표본'], '화면': set()})
                v['수'] += c['수']
                v['화면'].add(x['화면'])
                if c['표본'].get('대비', 99) < v['표본'].get('대비', 99):
                    v['표본'] = c['표본']
        상위 = sorted(묶음.items(), key=lambda kv: -kv[1]['수'])[:25]
        if 상위:
            줄.append(f"   ── 원인별 (총 {len(묶음)}가지) — 위에서부터 고치면 된다 ──")
            for 열쇠, v in 상위:
                종류, 정체, *색 = 열쇠.split('|')
                표 = v['표본']
                꼬리 = ''
                if 종류 == '대비':
                    꼬리 = f" 대비 {표.get('대비')} · 글자{색[0]} 위 {색[1]} · 예: {표.get('글','')!r}"
                else:
                    꼬리 = f" 배경{색[0]} · {표.get('넓이','')}"
                줄.append(f"     {v['수']:>6,}곳 [{종류}] {정체[:42]:<42}{꼬리}")
                줄.append(f"            화면 {len(v['화면'])}개: " +
                          ', '.join(sorted(v['화면'])[:4]) + (' …' if len(v['화면']) > 4 else ''))
    본문 = '\n'.join(줄)
    (_결과폴더 / '요약.txt').write_text(본문, encoding='utf-8')
    return 본문


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--기준', required=True, help='예: https://mou-m.com 또는 http://localhost:5099')
    ap.add_argument('--타입', default='current,mono,layer,light')
    ap.add_argument('--화면', default='', help='쉼표로 나눈 경로. 비우면 라우트 표 전체')
    ap.add_argument('--동시', type=int, default=4)
    ap.add_argument('--창보임', action='store_true', help='브라우저 창을 띄워서 본다')
    a = ap.parse_args()

    화면들 = [s.strip() for s in a.화면.split(',') if s.strip()] or 화면목록()
    모드들 = [s.strip() for s in a.타입.split(',') if s.strip()]
    print(f'기준 {a.기준} · 타입 {모드들} · 화면 {len(화면들)}개 · 동시 {a.동시}')

    모음 = asyncio.run(_달리기(a.기준, 모드들, 화면들, a.동시, not a.창보임))
    print('\n' + _요약쓰기(모음))
    print(f'\n원자료: {_결과폴더}')


if __name__ == '__main__':
    main()
