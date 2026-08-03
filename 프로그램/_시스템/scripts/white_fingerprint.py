# -*- coding: utf-8 -*-
"""화이트 타입 화면 지문 — 「지우기 전/후가 똑같다」를 말이 아니라 측정으로 증명한다.

왜 만들었나
    사장님 확정(2026-08-02): 화이트 타입만 남기고 기존·검정A·검정B 를 **코드까지**
    지운다. 이때 가장 무서운 것은 **지우다가 화이트 화면이 조용히 망가지는 것**이다.
    화이트 타입의 보정(배지 색·팝업·정렬·달력…)은 전부 `.ds` 아래에 있어서,
    지우는 과정에서 그 표시를 잘못 건드리면 **화면이 통째로 옛 색으로 돌아간다.**
    그런데 그건 에러가 아니라 「그냥 색이 다름」이라 테스트로도 안 걸린다.

무엇을 재나
    화면마다 눈에 보이는 요소의 **글자색·바탕색·테두리색·글자크기·굵기·정렬·
    보임여부**를 전부 적어 지문을 만든다. 지우기 전에 한 번, 지운 뒤에 한 번 떠서
    **한 글자라도 달라지면 그 자리를 짚어 준다.**

쓰는 법
    python scripts/white_fingerprint.py --기준 http://localhost:5185 --저장 before
    (코드 삭제 작업)
    python scripts/white_fingerprint.py --기준 http://localhost:5185 --저장 after --대조 before
"""
from __future__ import annotations

import argparse
import asyncio
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

_보관 = _시스템.parents[1] / '_white_fingerprint'

# 화이트 타입이 화면에 걸릴 때 붙는 표시. 지우기 전에는 이 표시를 손으로 붙여 재고,
# 지운 뒤에는 서버가 늘 붙여 주므로 그대로 잰다 — 양쪽 다 같은 조건이 된다.
_화이트클래스 = 'ds ds-light'

_지문JS = r"""
(클래스) => {
  document.body.className = 클래스;
  document.documentElement.className = 클래스;
  // 커서가 어디 있느냐에 따라 테두리 색이 달라진다 — 재기 전에 커서를 뗀다.
  try { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); } catch (e) {}
  const 볼것 = ['color', 'backgroundColor', 'borderTopColor', 'borderLeftColor',
                'fontSize', 'fontWeight', 'textAlign', 'display', 'visibility',
                'opacity', 'fontVariantNumeric'];
  const 줄 = [];
  const 모두 = document.body.querySelectorAll('*');
  let i = 0;
  for (const el of 모두) {
    i++;
    if (i > 4000) break;                       // 아주 긴 화면은 앞쪽만 (충분히 대표한다)
    const cs = getComputedStyle(el);
    if (cs.display === 'none') continue;
    // ★ id 는 쓰지 않는다 — 화면이 그릴 때마다 새로 짓는 번호(:r4l: 같은)가 섞여
    //   **같은 코드끼리도 수백 곳이 다르게** 나온다(2026-08-02 실측).
    const 이름 = el.tagName.toLowerCase() +
      ((el.getAttribute('class') || '').trim()
        ? '.' + (el.getAttribute('class') || '').trim().split(/\s+/).slice(0, 3).join('.') : '');
    줄.push(이름 + '|' + 볼것.map(k => cs[k]).join('|'));
  }
  // ★ 순서는 무의미하다 — 비동기로 채워지는 화면은 순서가 매번 다르다.
  //   같은 생김새가 몇 개인지(가짓수와 개수)만 본다.
  줄.sort();
  return 줄;
}
"""


def 화면목록() -> list[str]:
    """감사기와 같은 화면 목록을 쓴다(따로 적으면 어긋난다)."""
    sys.path.insert(0, str(_시스템 / 'scripts'))
    from design_audit_live import 화면목록 as _목록
    return _목록()


async def _재기(기준: str, 화면들: list[str], 동시: int) -> dict:
    from playwright.async_api import async_playwright
    결과: dict[str, list[str]] = {}
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(viewport={'width': 1920, 'height': 1080})
        페이지들 = [await ctx.new_page() for _ in range(max(1, 동시))]
        큐 = list(화면들)
        잠금 = asyncio.Lock()

        async def 일꾼(p):
            while True:
                async with 잠금:
                    if not 큐:
                        return
                    길 = 큐.pop(0)
                    남음 = len(큐)
                try:
                    await p.goto(기준.rstrip('/') + 길, wait_until='domcontentloaded', timeout=45000)
                    try:
                        await p.wait_for_load_state('networkidle', timeout=8000)
                    except Exception:
                        pass
                    await p.wait_for_timeout(900)
                    결과[길] = await p.evaluate(_지문JS, _화이트클래스)
                except Exception as e:
                    결과[길] = ['ERR ' + str(e)[:120]]
                print(f'  {길:<48} {len(결과[길]):>5}줄  (남음 {남음})', flush=True)

        await asyncio.gather(*[일꾼(p) for p in 페이지들])
        await b.close()
    return 결과


def 대조하기(옛이름: str, 새것: dict) -> int:
    """생김새별 **개수**로 맞대 본다.

    ★ 줄 하나씩 맞대면 안 된다 — 비동기로 채워지는 화면은 순서·개수가 매번 달라
      **같은 코드끼리도 수백 곳이 다르다고** 나온다(2026-08-02 실측). 그래서
      「어떤 생김새가 몇 개 있나」만 보고, 그 개수가 달라진 것만 짚는다.
    """
    from collections import Counter
    옛길 = _보관 / (옛이름 + '.json')
    if not 옛길.exists():
        print(f'⚠ 이전 지문이 없다: {옛길}')
        return 0
    옛 = json.loads(옛길.read_text(encoding='utf-8'))
    화면다름 = []
    총다름 = 0
    for 길, 새줄 in sorted(새것.items()):
        옛줄 = 옛.get(길)
        if 옛줄 is None:
            continue
        a, b = Counter(옛줄), Counter(새줄)
        빠짐 = a - b        # 있었는데 없어진 생김새
        생김 = b - a        # 없었는데 생긴 생김새
        if not 빠짐 and not 생김:
            continue
        n = sum(빠짐.values()) + sum(생김.values())
        총다름 += n
        화면다름.append((길, n, list(빠짐.items())[:2], list(생김.items())[:2]))
    print('\n' + '=' * 78)
    if not 화면다름:
        print('✅ 화이트 화면 지문 **완전 동일** — 지우기 전과 한 곳도 안 달라졌다.')
    else:
        print(f'🔴 달라진 화면 {len(화면다름)}개 · 달라진 생김새 {총다름}곳')
        for 길, n, 빠짐, 생김 in sorted(화면다름, key=lambda t: -t[1])[:12]:
            print(f'  {길}  ({n}곳)')
            for k, c in 빠짐:
                print(f'     없어짐 x{c}: {k[:104]}')
            for k, c in 생김:
                print(f'     새로생김 x{c}: {k[:104]}')
    return 총다름


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--기준', required=True)
    ap.add_argument('--저장', required=True, help='before / after')
    ap.add_argument('--대조', default='', help='맞대 볼 이전 지문 이름')
    ap.add_argument('--화면', default='')
    ap.add_argument('--동시', type=int, default=4)
    a = ap.parse_args()

    화면들 = [s.strip() for s in a.화면.split(',') if s.strip()] or 화면목록()
    print(f'지문 뜨기 — 화면 {len(화면들)}개 · {a.기준}')
    결과 = asyncio.run(_재기(a.기준, 화면들, a.동시))
    _보관.mkdir(parents=True, exist_ok=True)
    (_보관 / (a.저장 + '.json')).write_text(
        json.dumps(결과, ensure_ascii=False), encoding='utf-8')
    print(f'\n저장: {_보관 / (a.저장 + ".json")}')
    if a.대조:
        다름 = 대조하기(a.대조, 결과)
        raise SystemExit(1 if 다름 else 0)


if __name__ == '__main__':
    main()
