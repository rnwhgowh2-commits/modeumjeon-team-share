# -*- coding: utf-8 -*-
"""디자인 전수 감사 — 실브라우저로 화면마다 「눈에 보이는 것」을 직접 잰다.

왜 만들었나
    화면이 113개, 타입이 4개다. 눈으로는 452번을 못 본다. 지난 대비 보정이
    `/orders` 한 화면 실측만으로 이뤄져서, 나머지 화면에 결함이 그대로 남았다
    (사장님이 마진계산기의 흰 카드 잔재·검정 배경의 검정 글씨를 발견).

무엇을 재나 — 사장님 지적 4가지를 한 번에 잡는다
    b. 문서 폭이 창 폭을 넘어 화면 틀이 통째로 밀림  → 「가로 넘침」
    c. 글자색과 배경색 대비가 모자라 안 읽힘         → 「대비 미달」(4.5 기준)
    d. 규칙에 없는 글자 크기(11px 미만 등)           → 「너무 작은 글자」

★ 정확도의 핵심 — 배경은 「역산」해야 한다.
    요소의 background-color 만 읽으면 안 된다. 반투명이면 그 밑에 깔린 색이
    비쳐 보이므로, 조상 쪽으로 올라가며 알파를 합성해 **눈에 실제로 보이는 색**을
    구해야 한다. 이걸 안 하면 실제 대비 16.9 인 자리가 1.09 로 잘못 나온다
    (2026-07-31 실측에서 확인).

[2026-08-02 사장님 확정] 타입은 화이트 하나뿐이다.
    예전에는 네 타입을 오가며 쟀고, 그 과정에서 **사장님 화면의 타입까지 바뀌는**
    함정이 있었다(감사기와 사람이 같은 계정을 쓰기 때문). 타입을 지우면서 그
    함정 자체가 없어졌다 — 이제 감사기는 화면을 열어 보기만 한다.

쓰는 법
    # 라이브 (실제 데이터가 있어야 표 안의 결함이 보인다)
    python scripts/design_audit_live.py --기준 https://mou-m.com

    # 로컬
    python scripts/design_audit_live.py --기준 http://localhost:5099

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
def _볼만한길(p: str) -> bool:
    """사람이 눈으로 보는 화면인가 (자료 내려받기·API 는 화면이 아니다)."""
    if p.startswith('/static') or p.startswith('/api'):
        return False
    if '/api/' in p or p.endswith('.json') or p.endswith('.md'):
        return False
    if '.xlsx' in p or '/download' in p or '/export' in p:
        return False
    return True


_주소표_보관 = None


def _주소표():
    """Flask 라우트 표를 한 번만 만든다(인자 있는 길을 되짚을 때도 쓴다)."""
    global _주소표_보관
    if _주소표_보관 is None:
        os.environ.setdefault('ENVIRONMENT', 'team-share-dev')
        from app import create_app
        _주소표_보관 = create_app().url_map
    return _주소표_보관


def 화면목록() -> list[str]:
    길 = set()
    for r in _주소표().iter_rules():
        if 'GET' not in (r.methods or set()):
            continue
        if r.arguments:                     # <id> 같은 길은 여기서 못 만든다
            continue                        #   → 링크주워오기() 가 실제 링크로 채운다
        p = str(r.rule)
        if _볼만한길(p):
            길.add(p)
    # 주문관리는 탭마다 화면이 다르다 — 탭도 따로 본다
    길.update(['/orders/?tab=list', '/orders/?tab=cs',
               '/orders/?tab=margin', '/orders/?tab=ship'])
    return sorted(길)


# ══════════════════════════════════════════════════════════════════════════
# 🔴 [2026-08-02] 감사기가 눈이 반쯤 감겨 있었다 — 맹점 두 곳을 뚫는다.
#
#   ① 주소에 번호가 붙는 화면 29개를 **통째로 안 봤다**(`if r.arguments: 건너뜀`).
#      상품 상세(/bundles/<code>) 가 여기 있었다 — 사장님이 흰 판을 발견한 그 화면이다.
#      번호를 지어낼 수는 없으므로, **이미 잰 화면에서 실제 링크를 주워** 규칙마다
#      한 개씩 골라 다시 잰다. 사람이 손으로 적으면 반드시 빠지므로 링크로 찾는다.
#
#   ② 마진계산기는 **화면 안의 창(iframe)** 이라 바깥만 재고 안은 못 봤다.
#      창 안쪽도 같은 잣대로 잰다.
# ══════════════════════════════════════════════════════════════════════════
def 인자화면_뽑기(주운링크: set[str], 화면당: int = 1) -> list[str]:
    """주워온 링크 중 「번호 붙은 규칙」에 해당하는 것을 규칙마다 화면당개씩 고른다."""
    from werkzeug.exceptions import HTTPException
    맞추개 = _주소표().bind('localhost')
    규칙별: dict[str, list[str]] = {}
    for 길 in sorted(주운링크):
        민길 = 길.split('#')[0]
        if not 민길.startswith('/') or not _볼만한길(민길):
            continue
        try:
            끝점, _인자 = 맞추개.match(민길.split('?')[0], method='GET')
        except HTTPException:
            continue
        except Exception:
            continue
        규칙 = next((r for r in _주소표().iter_rules() if r.endpoint == 끝점), None)
        if 규칙 is None or not 규칙.arguments:
            continue                        # 인자 없는 길은 이미 다 쟀다
        칸 = 규칙별.setdefault(str(규칙.rule), [])
        if len(칸) < 화면당:
            칸.append(민길)
    뽑음 = [x for v in 규칙별.values() for x in v]
    return sorted(set(뽑음))


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
  let 글자수 = 0, 그림문자건너뜀 = 0, 그림배경건너뜀 = 0, 로고건너뜀 = 0;
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
    // 🔴 [2026-08-02] 그림·그라데이션 배경은 **색으로 판정할 수 없다.**
    //   소싱처 로고 동그라미는 `linear-gradient` 로 칠해져 있어 배경색이 「투명」이다.
    //   그러면 위로 거슬러 올라가 **부모 카드의 옅은 파랑**을 배경으로 잡아,
    //   실제로는 잘 보이는 흰 글자를 대비 1.15 라고 잘못 말한다(라이브 실측).
    //   판정 불가는 「결함 없음」이 아니라 **판정 불가**로 따로 센다.
    if (배경.그림있음) { 그림배경건너뜀++; continue; }

    // 🔴 [2026-08-02 사장님 확정] **마켓 로고 배지는 기준에서 뺀다.**
    //   쿠팡 빨강·스마트스토어 초록 위의 흰 글자는 2.2~4.2 로 문턱 아래다. 그런데
    //   그 색은 **그 마켓을 가리키는 표시**다 — 바꾸면 다른 마켓처럼 보여서 더 위험하다
    //   (이 저장소의 색 바꾸기 도구도 같은 이유로 마켓색을 일부러 건너뛴다).
    //   접근성 표준도 로고·브랜드 마크는 대비 기준에서 제외한다.
    //   ★ 「고칠 수 없는 것」을 계속 세면 진짜 결함이 그 숫자에 묻힌다 → 따로 센다.
    if (el.closest('.brand-app-logo,.brand-pill-v2,.site-logo,.brand-favi,'
                   + '.lp-logo,.mk-logo,.app-icon,.logo')) { 로고건너뜀++; continue; }
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
      // 🔴 [2026-08-02 사장님 확정] **팝업(모달·안내창)은 흰 바탕을 허락한다.**
      //   데이터 코드 지도 같은 읽는 창은 흰 종이가 오히려 편하다는 판단.
      //   그래서 팝업 안쪽은 「흰 판 잔재」로 세지 않는다(글자 대비는 그대로 본다).
      if (el.closest('dialog,[role="dialog"],[class*="modal"],[class*="Modal"],'
                     + '[class*="popup"],[class*="Popup"],[class*="팝업"]')) continue;
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

  // ── 4) 숨은 판(팝업·펼침판) ────────────────────────────────────────
  // ★ 라이브에서 단추를 누르면 실제로 전송·삭제가 일어날 수 있다 — 절대 안 누른다.
  //   대신 숨어 있는 판을 **잠깐 보이게만** 했다가 원래대로 돌려놓고 잰다.
  //   보이기/숨기기는 그 화면의 로직을 건드리지 않으므로 안전하다.
  //   (사장님이 보신 「브랜드 정리」 팝업이 바로 이런 판이었다.)
  const 숨은판 = [];
  {
    const 후보 = [];
    for (const el of document.body.querySelectorAll('div,section,aside,dialog')) {
      const cs = getComputedStyle(el);
      if (cs.display !== 'none') continue;
      if (el.children.length < 2) continue;          // 판이라 할 만한 것만
      if ((el.textContent || '').trim().length < 10) continue;
      후보.push(el);
      if (후보.length >= 12) break;
    }
    const 되돌리기 = [];
    for (const el of 후보) {
      되돌리기.push([el, el.style.display, el.style.visibility]);
      el.style.display = 'block';
      el.style.visibility = 'hidden';   // 눈에는 안 보이게 — 색 계산엔 지장 없다
    }
    try {
      for (const el of 후보) {
        const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        let t2, 본것 = new Set();
        while ((t2 = w.nextNode())) {
          const 글2 = (t2.nodeValue || '').trim();
          if (!글2 || 그림문자만(글2)) continue;
          const e2 = t2.parentElement;
          if (!e2 || 본것.has(e2)) continue;
          본것.add(e2);
          const cs2 = getComputedStyle(e2);
          const 글자색2 = 색분해(cs2.color);
          if (!글자색2) continue;
          const 배경2 = 보이는배경(e2);
          const 실제2 = 글자색2.a < 0.999 ? 겹치기(글자색2, 배경2.색) : 글자색2;
          const 값2 = 대비(실제2, 배경2.색);
          if (값2 < 대비기준) {
            숨은판.push({
              길: 길찾기(e2), 글: 글2.slice(0, 40),
              대비: Math.round(값2 * 100) / 100,
              글자색: cs2.color,
              배경색: `rgb(${Math.round(배경2.색.r)}, ${Math.round(배경2.색.g)}, ${Math.round(배경2.색.b)})`,
            });
          }
          if (숨은판.length >= 표본수) break;
        }
        if (숨은판.length >= 표본수) break;
      }
    } finally {
      for (const [el, d, v] of 되돌리기) { el.style.display = d; el.style.visibility = v; }
    }
  }
  숨은판.sort((a, b) => a.대비 - b.대비);

  // ── 5) 글자 잘림 — 칸보다 글이 길어 잘려 나가는 자리 ────────────────
  //   사장님 지적: 「등록 상품수 입력」이 「등록 ㅅ」에서 끊겼다.
  //   ★ 줄임표(…)로 **일부러** 줄이는 건 정상이므로 뺀다. 잘못된 잘림은
  //     줄임표 없이 그냥 사라지는 것 — 사용자는 글이 있는 줄도 모른다.
  const 잘림 = [];
  {
    const 자 = document.createElement('canvas').getContext('2d');
    for (const el of document.body.querySelectorAll('input, button, label, th, td, span, div, a')) {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      if (cs.textOverflow === 'ellipsis') continue;      // 일부러 줄인 것
      const r = el.getBoundingClientRect();
      if (r.width < 8 || r.height < 4) continue;
      const 안쪽 = el.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
      if (안쪽 <= 0) continue;
      const 글꼴 = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;

      if (el.tagName === 'INPUT') {
        // ★ 글자를 보여 주는 칸만 본다. 체크상자·라디오는 `.value` 가 'on' 이지만
        //   그 글자를 화면에 그리지 않는다 — 이걸 안 빼면 체크상자 하나가
        //   「잘림」 269곳으로 불어나 진짜 4곳을 덮는다(2026-08-02 실측).
        const 종류속성 = (el.getAttribute('type') || 'text').toLowerCase();
        if (['checkbox', 'radio', 'hidden', 'file', 'color', 'range',
             'submit', 'button', 'reset', 'image'].includes(종류속성)) continue;
        // 입력칸은 안내글(placeholder)·값 둘 다 본다. 스크롤로 못 보는 건 잘림이다.
        for (const [종류, 글] of [['안내글', el.getAttribute('placeholder')], ['값', el.value]]) {
          if (!글 || !String(글).trim()) continue;
          자.font = 글꼴;
          const 글폭 = 자.measureText(String(글)).width;
          if (글폭 > 안쪽 + 1) {
            const 한건 = { 길: 길찾기(el), 글: String(글).slice(0, 40), 종류,
                           글자폭: Math.round(글폭), 칸폭: Math.round(안쪽) };
            잘림.push(한건);
            원인담기('잘림|' + 정체(el) + '|' + 종류 + '|' + Math.round(안쪽), 한건);
            break;
          }
        }
        continue;
      }
      // 글자만 든 칸이 넘치는지 — 자식이 있으면 그 자식이 따로 잡힌다(중복 방지)
      if (el.children.length) continue;
      if (cs.overflowX !== 'hidden' && cs.overflow !== 'hidden' && cs.whiteSpace !== 'nowrap') continue;
      const 속글 = (el.textContent || '').trim();
      if (!속글) continue;                    // 글이 없으면 잘릴 것도 없다(막대·아이콘)
      if (el.scrollWidth > el.clientWidth + 1) {
        const 한건 = { 길: 길찾기(el), 글: 속글.slice(0, 40), 종류: '글자',
                       글자폭: el.scrollWidth, 칸폭: el.clientWidth };
        잘림.push(한건);
        원인담기('잘림|' + 정체(el) + '|글자|' + el.clientWidth, 한건);
      }
    }
  }

  // ── 6) 숫자가 왼쪽에 붙어 자릿수가 안 맞는 표 칸 ────────────────────
  //   사장님 지적: 25,310,700 과 278,200 의 자릿수가 세로로 안 맞는다.
  //   규율(디자인 규칙 원칙 4) — 숫자·금액·수량은 **오른쪽 + 자릿수 고정**.
  //   ★ 한 칸만 보고 판단하지 않는다. **같은 칼럼에 숫자가 2개 이상**일 때만
  //     「표의 숫자열」로 보고 센다(머리글 하나짜리 숫자는 표가 아니다).
  //   🔴 **「숫자처럼 생긴 것」과 「크기를 재는 숫자」는 다르다.**
  //     주문번호 2009064984989 · 전화번호 01037780229 · 상품번호 6478210710 ·
  //     사이즈 225 는 자릿수를 맞출 이유가 없다(오히려 오른쪽으로 밀면 읽기 나빠진다).
  //     처음엔 이걸 안 갈라서 3,036곳 중 대부분이 오탐이었다(2026-08-02 실측).
  //     그래서 **칼럼 머리글 이름**으로 가린다 — 사람이 그 칸을 뭐라 불렀는지가 근거다.
  const 숫자왼쪽 = [];
  {
    const 숫자만 = /^[-+]?[0-9][0-9,]*(\.[0-9]+)?\s*(%|원|개|건|명|회)?$/;
    const 세는칸 = /수량|금액|가격|매출|매입|마진|건수|재고|개수|합계|평균|단가|정산|비용|잔고|잔액|점수|비율|율$|원$|개수/;
    const 이름표칸 = /번호|코드|전화|연락처|바코드|SKU|아이디|주소|일자|날짜|기간|사이즈|치수|우편|색상|컬러|색$|옵션|대상|순번|이름|명$|^#$|구분|상태|분류/;
    for (const 표 of document.body.querySelectorAll('table')) {
      const 칸별 = new Map();          // 칼럼번호 → [칸…]
      const 머리 = new Map();          // 칼럼번호 → 머리글 글자
      for (const 행 of 표.querySelectorAll('tr')) {
        [...행.children].forEach((c, i) => {
          if (c.tagName === 'TH' && !머리.has(i)) 머리.set(i, (c.textContent || '').trim());
          if (!칸별.has(i)) 칸별.set(i, []);
          칸별.get(i).push(c);
        });
      }
      for (const [번호, 칸들] of 칸별) {
        const 머리글 = 머리.get(번호) || '';
        // ★ **「세는 숫자」라는 증거가 있을 때만 센다**(2026-08-02 3차 조정).
        //   느슨하게 「8자리 이하 맨숫자」를 다 세었더니 6가지 중 5가지가 오탐이었다 —
        //   「컬러」칸의 색상 코드 2·4, 「대상」칸의 기록 번호 8·11,
        //   「옵션」칸의 사이즈 160·235, 「#」칸의 순번 1·2·3.
        //   이런 것들을 오른쪽으로 밀면 **오히려 잘못된 화면**이 된다.
        //   증거는 둘 중 하나 — ① 머리글이 세는 말(매출·건수·수량…) ② 값에 자리표(,)나
        //   단위(원·개·건·%)가 붙어 있음. 둘 다 없으면 「그냥 숫자처럼 생긴 것」으로 본다.
        if (이름표칸.test(머리글)) continue;          // 번호·코드·사이즈·색상 = 이름표다
        const 확실히세는칸 = 세는칸.test(머리글);
        const 숫자칸 = 칸들.filter(c => {
          const t = (c.textContent || '').trim();
          if (!t || t.length > 18 || !숫자만.test(t)) return false;
          if (/^0\d/.test(t)) return false;           // 앞자리 0 = 전화·우편 같은 번호
          if (확실히세는칸) return true;              // ① 머리글이 세는 말
          return /[,%원개건명회]/.test(t);            // ② 값에 자리표·단위
        });
        if (숫자칸.length < 2) continue;             // 표의 숫자열이 아니다
        for (const c of 숫자칸) {
          const cs = getComputedStyle(c);
          const 정렬 = cs.textAlign;
          if (정렬 === 'right' || 정렬 === 'end' || 정렬 === 'center') continue;
          const r = c.getBoundingClientRect();
          if (r.width < 8 || r.height < 4) continue;
          const 한건 = { 길: 길찾기(c), 글: (c.textContent || '').trim().slice(0, 20),
                         칼럼: 번호, 정렬 };
          숫자왼쪽.push(한건);
          원인담기('숫자정렬|' + 정체(표) + ' 칼럼' + 번호 + '|' + 정렬, 한건);
        }
      }
    }
  }

  // ── 7) 떠 있는 판이 반투명 — 뒤 내용이 비쳐 글자와 겹친다 ──────────
  //   사장님 지적: 마진계산기 그래프 위 설명 판에 **차트 선이 그대로 비쳐** 숫자가
  //   안 읽혔다. 원인은 그 판이 카드용 바탕 이름을 쓴 것 — 그 이름은 어두운 타입에서
  //   **반투명**(rgba(255,255,255,.04))이다. 페이지 위에 얹힌 카드에는 맞지만,
  //   **다른 내용 위에 뜨는 판**에는 치명적이다.
  //   ★ 규칙: 떠 있는 판(뜬 자리 + 겹침 순서가 있는 것)의 바탕은 **불투명**이어야 한다.
  //   ★ 떠 있는 판은 **마우스를 올려야 나타난다** — 화면에 그려진 것만 훑으면 못 잡는다.
  //     그래서 **스타일 규칙 자체**를 훑는다. 「뜬 자리(absolute/fixed) + 바탕색」을 한
  //     규칙에서 같이 정한 것이 곧 떠 있는 판이다. 그 바탕이 반투명이면 결함이다.
  const 비치는판 = [];
  {
    const 재보기 = document.createElement('div');
    재보기.style.cssText = 'position:absolute;left:-9999px;width:10px;height:10px';
    document.body.appendChild(재보기);
    const 본규칙 = new Set();
    for (const 시트 of document.styleSheets) {
      let 규칙들;
      try { 규칙들 = 시트.cssRules; } catch (e) { continue; }
      for (const r of 규칙들) {
        if (!r.style || !r.selectorText) continue;
        const 자리 = (r.style.position || '').toLowerCase();
        if (자리 !== 'absolute' && 자리 !== 'fixed') continue;
        const 바탕값 = r.style.background || r.style.backgroundColor;
        if (!바탕값) continue;
        // ★ 반투명이 **의도인 것**은 뺀다 — 모달 뒷배경(scrim)·토글 스위치·손잡이는
        //   비쳐 보이는 게 제 역할이다. 문제는 **글을 읽으라고 띄운 판**이 비칠 때다.
        if (/::(before|after)/.test(r.selectorText)) continue;
        if (/overlay|backdrop|mask|dim|scrim|shade|slider|switch|track|thumb|handle|-bg\b|bg$/i
            .test(r.selectorText)) continue;
        if (본규칙.has(r.selectorText)) continue;
        본규칙.add(r.selectorText);
        // 글이 실제로 들어가는 판인가 — 아니면 장식이다.
        let 글있음 = false;
        try {
          for (const el2 of document.querySelectorAll(r.selectorText)) {
            if ((el2.textContent || '').trim().length >= 10) { 글있음 = true; break; }
          }
        } catch (e) { continue; }
        if (!글있음) continue;
        재보기.style.background = '';
        재보기.style.background = 바탕값;
        const 잰색 = 색분해(getComputedStyle(재보기).backgroundColor);
        if (!잰색 || 잰색.a === 0 || 잰색.a >= 0.92) continue;
        const 한건 = { 길: r.selectorText.slice(0, 70), 투명도: Math.round(잰색.a * 100) / 100,
                       바탕: getComputedStyle(재보기).backgroundColor, 종류: '규칙' };
        비치는판.push(한건);
        원인담기('비치는판|' + r.selectorText.split(',')[0].trim().slice(0, 40) + '|규칙', 한건);
      }
    }
    재보기.remove();
    for (const el of document.body.querySelectorAll('*')) {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      const 뜸 = cs.position === 'absolute' || cs.position === 'fixed' || cs.position === 'sticky';
      if (!뜸) continue;
      if (cs.zIndex === 'auto' || Number(cs.zIndex) < 1) continue;   // 겹침 순서가 없으면 판이 아니다
      const r = el.getBoundingClientRect();
      if (r.width < 80 || r.height < 40) continue;                   // 작은 배지·점은 뺀다
      const 자기 = 색분해(cs.backgroundColor);
      if (!자기 || 자기.a === 0) continue;                            // 바탕을 아예 안 칠했으면 판이 아니다
      if (자기.a >= 0.92) continue;                                   // 충분히 불투명하면 정상
      if ((el.textContent || '').trim().length < 4) continue;         // 글이 없으면 읽힘 문제 아님
      const 한건 = { 길: 길찾기(el), 투명도: Math.round(자기.a * 100) / 100,
                     바탕: cs.backgroundColor, 넓이: Math.round(r.width) + 'x' + Math.round(r.height),
                     글: (el.textContent || '').trim().slice(0, 30) };
      비치는판.push(한건);
      원인담기('비치는판|' + 정체(el) + '|' + cs.backgroundColor, 한건);
    }
  }

  // ── 8) 글자끼리 겹침 — 서로 위에 그려져 둘 다 안 읽힌다 ─────────────
  //   사장님 지적: 대량등록 화면에서 「전체 고르기」와 옆 설명이 **겹쳐** 찍혔다.
  //   ★ 같은 자리에 두 글자가 그려지면 둘 다 못 읽는다 — 색·대비와 별개의 결함이다.
  //   ★ 일부러 겹치는 것(뜬 판·툴팁·뱃지)은 뺀다 — 겹침 순서가 있는 것은 의도된 것이다.
  const 겹침 = [];
  {
    const 조각 = [];
    const 걷기2 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let t3;
    while ((t3 = 걷기2.nextNode())) {
      const 글3 = (t3.nodeValue || '').trim();
      if (글3.length < 2 || 그림문자만(글3)) continue;
      const e3 = t3.parentElement;
      if (!e3) continue;
      const cs3 = getComputedStyle(e3);
      if (cs3.display === 'none' || cs3.visibility === 'hidden' || parseFloat(cs3.opacity) < 0.1) continue;
      if (e3.closest('[style*="z-index"],dialog,[role="dialog"]')) continue;
      let 뜬조상 = false;
      for (let n = e3; n && n !== document.body; n = n.parentElement) {
        const p = getComputedStyle(n).position;
        if ((p === 'absolute' || p === 'fixed') && getComputedStyle(n).zIndex !== 'auto') { 뜬조상 = true; break; }
      }
      if (뜬조상) continue;
      const r3 = e3.getBoundingClientRect();
      if (r3.width < 12 || r3.height < 8 || r3.width > 900) continue;
      조각.push({ el: e3, r: r3, 글: 글3.slice(0, 24) });
      if (조각.length >= 700) break;
    }
    const 본쌍 = new Set();
    for (let i = 0; i < 조각.length; i++) {
      for (let j = i + 1; j < 조각.length; j++) {
        const a = 조각[i], b = 조각[j];
        if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
        const 가로 = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
        const 세로 = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
        if (가로 <= 2 || 세로 <= 2) continue;                        // 살짝 스치는 건 뺀다
        const 겹친넓이 = 가로 * 세로;
        const 작은쪽 = Math.min(a.r.width * a.r.height, b.r.width * b.r.height);
        if (작은쪽 <= 0 || 겹친넓이 / 작은쪽 < 0.35) continue;        // 3분의 1 넘게 겹칠 때만
        const 열쇠 = 정체(a.el) + '|' + 정체(b.el);
        if (본쌍.has(열쇠)) continue;
        본쌍.add(열쇠);
        const 한건 = { 길: 길찾기(a.el), 글: a.글, 겹친글: b.글,
                       겹친비율: Math.round(겹친넓이 / 작은쪽 * 100) + '%' };
        겹침.push(한건);
        원인담기('겹침|' + 열쇠, 한건);
        if (겹침.length >= 60) break;
      }
      if (겹침.length >= 60) break;
    }
  }

  const 원인들 = [...원인묶음.values()].sort((a, b) => b.수 - a.수);

  // ── 5) 이 화면에 걸린 링크 — 「번호 붙은 화면」을 되짚는 유일한 실마리 ──
  //   /bundles/<code> 같은 길은 번호를 지어낼 수 없다. 실제 목록 화면에 걸린
  //   링크를 주워야 그 상세 화면을 잴 수 있다(사람이 손으로 적으면 반드시 빠진다).
  const 링크 = [];
  {
    const 본것 = new Set();
    for (const a of document.querySelectorAll('a[href]')) {
      const h = a.getAttribute('href') || '';
      if (!h.startsWith('/') || h.startsWith('//')) continue;   // 같은 집 안쪽만
      if (본것.has(h)) continue;
      본것.add(h);
      링크.push(h);
      if (링크.length >= 400) break;
    }
  }

  return {
    링크,
    숨은판_수: 숨은판.length, 숨은판: 숨은판.slice(0, 표본수),
    글자수, 그림문자건너뜀, 그림배경건너뜀, 로고건너뜀,
    대비미달_수: 대비미달.length, 대비미달: 대비미달.slice(0, 표본수),
    흰잔재_수: 흰잔재.length,   흰잔재: 흰잔재.slice(0, 표본수),
    잘림_수: 잘림.length,       잘림: 잘림.slice(0, 표본수),
    비치는판_수: 비치는판.length, 비치는판: 비치는판.slice(0, 표본수),
    겹침_수: 겹침.length,       겹침: 겹침.slice(0, 표본수),
    숫자왼쪽_수: 숫자왼쪽.length, 숫자왼쪽: 숫자왼쪽.slice(0, 표본수),
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
    # 중간 캐시(CDN)가 **이전 타입으로 그려진 화면**을 돌려주면 측정이 통째로 거짓이 된다.
    # 주소 뒤에 매번 다른 표식을 붙여 늘 새로 받게 한다(화면 로직에는 영향 없음).
    주소 = 기준.rstrip('/') + 길
    주소 += ('&' if '?' in 주소 else '?') + '_감사=' + str(abs(hash((길, 옵션.get('기대클래스')))) % 10**8)
    try:
        r = await page.goto(주소, wait_until='domcontentloaded', timeout=45000)
        상태 = r.status if r else 0
    except Exception as e:
        return {'화면': 길, '상태': 'ERR', '오류': str(e)[:200]}
    if 상태 >= 400:
        return {'화면': 길, '상태': 상태}
    try:
        # 늦게 그려지는 표(자바스크립트로 채우는 화면)를 기다린다.
        # ★ 예전엔 1.2초만 기다렸다 — 그래서 데이터가 실린 화면을 못 보고 지나쳤다.
        #   사장님이 보내주신 결함이 전부 「분석 결과가 뜬 뒤」의 화면이었다.
        try:
            await page.wait_for_load_state('networkidle', timeout=12000)
        except Exception:
            pass                      # 계속 통신하는 화면(폴링)은 그냥 넘어간다
        await page.wait_for_timeout(1200)
        잰것 = await page.evaluate(_측정JS, 옵션)
    except Exception as e:
        return {'화면': 길, '상태': 상태, '오류': str(e)[:200]}
    잰것['화면'] = 길
    잰것['상태'] = 상태

    # 🔴 [2026-08-02] **화면마다** 타입이 실제로 걸렸는지 확인한다.
    #   시작할 때 한 번만 보면 부족했다 — 중간 캐시(CDN)가 **이전 타입으로 그려진
    #   화면을 그대로 돌려주는** 일이 있어서, 검정A 를 재는 중에 화이트 타입 화면이
    #   40개 섞여 들어왔다. 그러면 있지도 않은 「흰 판 잔재」가 무더기로 잡히고,
    #   나는 멀쩡한 화면을 고치려 들게 된다(2026-08-02 실제로 여기까지 갔다).
    잰것['걸린타입'] = 기대타입 = 옵션.get('기대클래스') or ''
    if 기대타입:
        try:
            실제 = await page.evaluate("() => document.body.className || ''")
        except Exception:
            실제 = ''
        if 기대타입 not in 실제:
            잰것['타입어긋남'] = 실제
            # 이 화면 결과는 못 믿는다 — 숫자에서 빼고 표시만 남긴다.
            for k in ('대비미달_수', '흰잔재_수', '작은글자_수', '잘림_수',
                      '숫자왼쪽_수', '숨은판_수'):
                잰것[k] = 0
            잰것['원인들'] = []

    # 🔴 화면 안의 창(iframe) 도 같은 잣대로 잰다.
    #   마진계산기는 통째로 창 안에 들어 있어 바깥만 재면 **한 곳도 안 잡힌다**
    #   (사장님이 켜진 탭 글자·펼침 표 흰 판을 보신 그 화면이 바로 창 안쪽이다).
    잰것['창안'] = []
    for 창 in page.frames:
        if 창 is page.main_frame:
            continue
        try:
            안 = await 창.evaluate(_측정JS, 옵션)
        except Exception:
            continue                     # 남의 집 창은 못 들여다본다(정상)
        안.pop('링크', None)
        안['화면'] = 길 + ' ▸창안 ' + (창.url or '').split('?')[0][-48:]
        안['상태'] = 상태
        잰것['창안'].append(안)
    return 잰것


async def _한타입(브라우저, 기준: str, 모드: str, 화면들: list[str], 동시: int) -> dict:
    from webapp.design_mode import MODES
    이름, _설명, 어두운가 = MODES[모드]
    ctx = await 브라우저.new_context(viewport={'width': 1920, 'height': 1080})
    page0 = await ctx.new_page()
    await page0.goto(기준.rstrip('/') + '/', wait_until='domcontentloaded', timeout=45000)
    if not await _모드바꾸기(page0, 기준, 모드):
        print(f'  ⚠ {이름}: 타입 전환 실패 — 로그인 상태를 확인하세요')

    # 🔴 [2026-08-02] **바뀌었다는 말을 믿지 말고 화면에서 확인한다.**
    #   로그인이 걸린 곳에서는 타입 바꾸기 요청이 로그인 화면으로 넘어가는데,
    #   그 응답도 200 이라 「성공」으로 읽힌다. 그 상태로 재면 화면은 밝은 채인데
    #   감사기는 어두운 타입이라 믿어, **있지도 않은 흰 판 수십 곳**을 만들어 낸다
    #   (로컬 실측 2026-08-02: /policies/apply 흰 잔재 24곳이 전부 가짜였다).
    await page0.goto(기준.rstrip('/') + '/', wait_until='domcontentloaded', timeout=45000)
    붙은클래스 = await page0.evaluate("() => document.body.className || ''")
    from webapp.design_mode import DEFAULT_MODE as _안전망
    기대 = 'ds-' + 모드 if 모드 != _안전망 else ''
    if 기대 and 기대 not in 붙은클래스:
        raise SystemExit(
            f'\n🔴 {이름}: 화면에 타입이 안 걸렸다 (기대 "{기대}", 실제 "{붙은클래스}").\n'
            f'   이대로 재면 결과가 통째로 거짓이 된다 — 로그인이 필요한 곳이면\n'
            f'   로그인 상태로 돌리거나, 인증이 열린 기준(라이브)으로 재세요.')
    옵션 = {'대비기준': _대비기준, '대비기준_큰글자': _대비기준_큰글자,
            '최소글자': _최소글자, '표본수': _화면당_표본, '어두운타입': bool(어두운가),
            # 화면마다 「이 타입이 실제로 걸렸나」를 확인할 때 쓰는 표식
            '기대클래스': ('ds-' + 모드) if 모드 != _안전망 else ''}

    결과 = []
    페이지들 = [page0] + [await ctx.new_page() for _ in range(max(0, 동시 - 1))]
    잠금 = asyncio.Lock()
    큐: list[str] = []

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
            for 잰것 in [r] + list(r.get('창안') or []):
                꼬리 = ' (창안)' if 잰것 is not r else ''
                if 잰것.get('대비미달_수'):
                    표시 += f" 대비{잰것['대비미달_수']}{꼬리}"
                if 잰것.get('흰잔재_수'):
                    표시 += f" 흰잔재{잰것['흰잔재_수']}{꼬리}"
                if 잰것.get('가로넘침'):
                    표시 += f' 가로넘침{꼬리}'
                if 잰것.get('작은글자_수'):
                    표시 += f" 작은글자{잰것['작은글자_수']}{꼬리}"
                if 잰것.get('잘림_수'):
                    표시 += f" 잘림{잰것['잘림_수']}{꼬리}"
                if 잰것.get('숫자왼쪽_수'):
                    표시 += f" 숫자왼쪽{잰것['숫자왼쪽_수']}{꼬리}"
            print(f'  [{이름}] {길:<46} {r.get("상태")}{표시}  (남음 {남음})', flush=True)

    큐[:] = list(화면들)
    await asyncio.gather(*[일꾼(p) for p in 페이지들])

    # 🔴 2차 — 「번호 붙은 화면」. 1차에서 주워 온 실제 링크로만 찾는다.
    #   여기를 안 돌면 상품 상세·재고 상세 등 29가지 화면이 통째로 안 재진다.
    주운링크: set[str] = set()
    for r in 결과:
        주운링크.update(r.get('링크') or [])
    이미 = {x['화면'] for x in 결과}
    추가 = [p for p in 인자화면_뽑기(주운링크) if p not in 이미]
    if 추가:
        print(f'  [{이름}] ── 번호 붙은 화면 {len(추가)}개 추가로 잰다 ──', flush=True)
        큐[:] = 추가
        await asyncio.gather(*[일꾼(p) for p in 페이지들])
    else:
        print(f'  [{이름}] ⚠ 번호 붙은 화면을 하나도 못 찾았다 — 링크 주워오기 확인 필요', flush=True)

    await ctx.close()
    # 창 안쪽도 화면 하나로 세운다 — 안 그러면 요약에서 통째로 빠진다.
    펼침 = []
    for r in 결과:
        창안 = r.pop('창안', None) or []
        r.pop('링크', None)
        펼침.append(r)
        펼침.extend(창안)
    펼침.sort(key=lambda x: x['화면'])
    return {'모드': 모드, '이름': 이름, '어두운타입': bool(어두운가), '화면들': 펼침}


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
            # [2026-08-02] 끝나고 타입을 되돌리던 일이 사라졌다 — 타입이 화이트 하나뿐이라
            #   감사기가 사장님 화면의 타입을 바꿀 일이 아예 없다(그 함정 자체가 없어졌다).
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
        잘 = sum(x.get('잘림_수', 0) for x in 화면들)
        숫 = sum(x.get('숫자왼쪽_수', 0) for x in 화면들)
        넘 = [x['화면'] for x in 화면들 if x.get('가로넘침')]
        오류 = [x['화면'] for x in 화면들 if x.get('오류') or x.get('상태') in ('ERR',)]
        어긋 = [x['화면'] for x in 화면들 if x.get('타입어긋남') is not None]
        줄.append('')
        줄.append(f"■ {r['이름']} ({모드}) — 화면 {len(화면들)}개")
        숨 = sum(x.get('숨은판_수', 0) for x in 화면들)
        줄.append(f"   대비 미달 {대비:,}곳 · 흰 잔재 {흰:,}곳 · 작은 글자 {작:,}곳 · 가로 넘침 {len(넘)}화면")
        줄.append(f"   글자 잘림 {잘:,}곳 · 숫자가 왼쪽에 붙은 표 칸 {숫:,}곳")
        비 = sum(x.get('비치는판_수', 0) for x in 화면들)
        겹 = sum(x.get('겹침_수', 0) for x in 화면들)
        줄.append(f"   뒤가 비치는 떠 있는 판 {비:,}곳 · 글자끼리 겹침 {겹:,}곳")
        로 = sum(x.get('로고건너뜀', 0) for x in 화면들)
        그 = sum(x.get('그림배경건너뜀', 0) for x in 화면들)
        줄.append(f"   기준에서 뺀 것 — 마켓 로고 {로:,}곳(브랜드 표시) · 그림 배경 {그:,}곳(색으로 판정 불가)")
        if 어긋:
            줄.append(f"   ⚠ 타입이 안 걸린 채 온 화면 {len(어긋)}개 — 숫자에서 뺐다(캐시 의심): "
                      + ', '.join(sorted(어긋)[:6]) + (' …' if len(어긋) > 6 else ''))
        줄.append(f"   숨은 판(팝업·펼침판) 안의 대비 미달 {숨:,}곳")
        숨순 = sorted((x for x in 화면들 if x.get('숨은판_수')), key=lambda x: -x['숨은판_수'])[:6]
        for x in 숨순:
            최 = x['숨은판'][0] if x['숨은판'] else None
            줄.append(f"     {x['숨은판_수']:>4}곳  {x['화면']}" +
                      (f"  (최악 {최['대비']} · {최['글']!r})" if 최 else ''))
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


def 대조(이전폴더: str) -> str:
    """작업 전/후를 화면별로 맞대 본다.

    ★ 「기존 타입」이 한 픽셀도 안 바뀌었다는 것을 **주장이 아니라 측정으로** 보이는
      장치다. 그 타입의 숫자가 하나라도 움직이면 안전망을 건드린 것이다.
    """
    이전 = pathlib.Path(이전폴더)
    줄 = ['작업 전/후 대조', '=' * 78]
    for f in sorted(_결과폴더.glob('*.json')):
        옛 = 이전 / f.name
        if not 옛.exists():
            줄.append(f'\n■ {f.stem}: 이전 결과 없음 — 건너뜀')
            continue
        A = json.loads(옛.read_text(encoding='utf-8'))
        B = json.loads(f.read_text(encoding='utf-8'))
        이름 = B.get('이름', f.stem)
        a = {x['화면']: x for x in A['화면들']}
        b = {x['화면']: x for x in B['화면들']}
        총 = {}
        for 키, 표시 in (('대비미달_수', '대비 미달'), ('흰잔재_수', '흰 잔재'),
                         ('작은글자_수', '작은 글자'), ('잘림_수', '글자 잘림'),
                         ('숫자왼쪽_수', '숫자 왼쪽붙음'), ('비치는판_수', '비치는 판'),
                         ('겹침_수', '글자 겹침')):
            총[표시] = (sum(v.get(키, 0) for v in a.values()),
                        sum(v.get(키, 0) for v in b.values()))
        넘A = sum(1 for v in a.values() if v.get('가로넘침'))
        넘B = sum(1 for v in b.values() if v.get('가로넘침'))
        총['가로 넘침(화면)'] = (넘A, 넘B)
        줄.append(f'\n■ {이름} ({f.stem})')
        for 표시, (x, y) in 총.items():
            차 = y - x
            표식 = '변화 없음' if 차 == 0 else (f'▼ {abs(차):,} 줄었다' if 차 < 0 else f'▲ {차:,} 늘었다')
            줄.append(f'   {표시:<16} {x:>7,} → {y:>7,}   {표식}')
        # 화면 단위로 나빠진 곳(늘어난 곳)만 짚는다 — 좋아진 건 굳이 안 나열한다
        나빠짐 = []
        for 길 in sorted(set(a) & set(b)):
            d = b[길].get('대비미달_수', 0) - a[길].get('대비미달_수', 0)
            w = b[길].get('흰잔재_수', 0) - a[길].get('흰잔재_수', 0)
            if d > 0 or w > 0:
                나빠짐.append((길, d, w))
        if 나빠짐:
            줄.append('   ⚠ 나빠진 화면:')
            for 길, d, w in sorted(나빠짐, key=lambda t: -(t[1] + t[2]))[:15]:
                줄.append(f'      {길}  대비 +{d}  흰잔재 +{w}')
    본문 = '\n'.join(줄)
    (_결과폴더 / '대조.txt').write_text(본문, encoding='utf-8')
    return 본문


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--기준', required=True, help='예: https://mou-m.com 또는 http://localhost:5099')
    # [2026-08-02 사장님 확정] 타입이 화이트 하나뿐 — 고를 것이 없다.
    ap.add_argument('--타입', default='light')
    ap.add_argument('--화면', default='', help='쉼표로 나눈 경로. 비우면 라우트 표 전체')
    ap.add_argument('--동시', type=int, default=4)
    ap.add_argument('--창보임', action='store_true', help='브라우저 창을 띄워서 본다')
    ap.add_argument('--대조', default='', help='작업 전 결과 폴더와 맞대 본다(무손실 증명)')
    a = ap.parse_args()

    화면들 = [s.strip() for s in a.화면.split(',') if s.strip()] or 화면목록()
    모드들 = [s.strip() for s in a.타입.split(',') if s.strip()]
    print(f'기준 {a.기준} · 타입 {모드들} · 화면 {len(화면들)}개 · 동시 {a.동시}')

    모음 = asyncio.run(_달리기(a.기준, 모드들, 화면들, a.동시, not a.창보임))
    print('\n' + _요약쓰기(모음))
    if a.대조:
        print('\n' + 대조(a.대조))
    print(f'\n원자료: {_결과폴더}')


if __name__ == '__main__':
    main()
