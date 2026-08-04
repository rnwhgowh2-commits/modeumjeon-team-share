# -*- coding: utf-8 -*-
"""표 정렬 전수 실측 — 실브라우저가 그린 픽셀로 화면마다 표를 잰다.

왜 실브라우저인가
    표 상당수가 자바스크립트로 그려진다(마진계산기 aggTable 등).
    코드만 훑는 검사(check_typography.py)로는 그런 표의 머리글이 어디 붙었는지
    영영 알 수 없다 — 실제로 정적 검사는 5곳만 찾아냈다.

무엇을 재나
    표마다, 칸(열)마다
      · 머리글이 그려진 위치와 값이 그려진 위치가 **같은 축**에 있는가
        (값이 가운데면 가운데끼리, 오른쪽이면 오른쪽 끝끼리)
      · 2px 를 넘게 어긋나면 「어긋남」으로 센다
    덧붙여 화면의 글꼴도 같이 잰다(Inter 잔재 확인).

쓰는 법
    python 프로그램/_시스템/scripts/audit_table_align_live.py --기준 http://localhost:5077
    python 프로그램/_시스템/scripts/audit_table_align_live.py --기준 https://mou-m.com
    ... --화면 /orders/,/bundles/       # 일부만
"""
from __future__ import annotations
import asyncio, sys, os, json, argparse, collections

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, '프로그램', '_시스템'))

허용어긋남 = 2   # px — 소수점 반올림 정도는 어긋난 게 아니다

JS = r"""
() => {
  // 🔴 [2026-08-03] 칸 통째로 재면 「글자가 아닌 것」까지 같이 잡힌다.
  //   판매처 계정 표의 머리글에는 **칸 너비 조절 손잡이**가 들어 있어(칸 오른쪽 끝에
  //   붙어 있는 6px 짜리), 통째로 재니 글자가 47px 밀린 것처럼 나왔다 — 실제로는
  //   글자는 가운데에 잘 있었다. **글자만** 잰다(자리를 따로 잡은 장식은 뺀다).
  //   ★ 글자만 재도 안 된다 — 아이콘·배지가 글자 옆에 붙은 칸은 「보이는 덩어리」가
  //     가운데인데 글자만 보면 치우친 것으로 나온다(가짜 결함 28곳).
  //     보이는 것은 다 재되, **자리를 따로 잡은 장식**(position:absolute/fixed)만 뺀다.
  const 잰다 = (el) => {
    let L = Infinity, R = -Infinity;
    const 넣기 = (r) => {
      if (!r || (!r.width && !r.height)) return;
      L = Math.min(L, r.left); R = Math.max(R, r.right);
    };
    const 훑기 = (부모) => {
      for (const n of 부모.childNodes) {
        if (n.nodeType === 3) {                       // 글자
          if (!n.nodeValue.trim()) continue;
          const rg = document.createRange(); rg.selectNodeContents(n);
          넣기(rg.getBoundingClientRect());
        } else if (n.nodeType === 1) {                // 요소
          const cs = getComputedStyle(n);
          if (cs.position === 'absolute' || cs.position === 'fixed' ||
              cs.display === 'none' || cs.visibility === 'hidden') continue;
          넣기(n.getBoundingClientRect());
        }
      }
    };
    훑기(el);
    if (L === Infinity) return null;
    return { l: L, r: R, c: (L + R) / 2 };
  };
  const 결과 = [];
  const tables = document.querySelectorAll('table');
  for (const t of tables) {
    if (t.hasAttribute('data-align-keep')) continue;
    const head = t.tHead && t.tHead.rows.length ? t.tHead.rows[t.tHead.rows.length - 1] : null;
    const body = t.tBodies && t.tBodies[0];
    if (!head || !body || !body.rows.length) continue;
    // colspan 없는 첫 줄을 값 표본으로
    let 표본 = null;
    for (const r of body.rows) {
      let ok = true;
      for (const c of r.cells) if (c.colSpan > 1) { ok = false; break; }
      if (ok && r.offsetParent !== null) { 표본 = r; break; }
    }
    if (!표본) continue;
    const n = Math.min(head.cells.length, 표본.cells.length);
    const 칸 = [];
    for (let i = 0; i < n; i++) {
      const th = head.cells[i], td = 표본.cells[i];
      if (th.colSpan > 1 || td.colSpan > 1) continue;
      const ta = getComputedStyle(td).textAlign;
      const 쪽 = ta === 'right' || ta === 'end' ? 'r' : ta === 'center' ? 'c' : 'l';
      const a = 잰다(th), b = 잰다(td);
      if (!a || !b) continue;
      칸.push({ 이름: (th.textContent || '').trim().slice(0, 12), 값정렬: ta,
                차: Math.round(a[쪽] - b[쪽]) });
    }
    if (칸.length) 결과.push({ 클래스: (t.className || '').slice(0, 40),
                              동기화: t.classList.contains('정렬동기화'), 칸 });
  }
  const 표본글꼴 = getComputedStyle(document.body).fontFamily.split(',')[0].replace(/["']/g, '');
  return { 표: 결과, 글꼴: 표본글꼴 };
}
"""


def 화면목록():
    os.environ.setdefault('ENVIRONMENT', 'team-share-dev')
    from app import create_app
    길 = set()
    for r in create_app().url_map.iter_rules():
        if 'GET' not in (r.methods or set()) or r.arguments:
            continue
        p = str(r.rule)
        if p.startswith('/static') or p.startswith('/api') or '/api/' in p:
            continue
        if p.endswith('.json') or p.endswith('.md') or '/download' in p or '/export' in p:
            continue
        길.add(p)
    길.update(['/orders/?tab=list', '/orders/?tab=margin', '/orders/?tab=cs', '/orders/?tab=ship'])
    return sorted(길)


async def 달리기(기준, 화면들, 동시):
    from playwright.async_api import async_playwright
    합 = {'화면': 0, '표': 0, '칸': 0, '어긋남': 0, '동기화표': 0, '화면아님': 0}
    나쁜곳, 글꼴들 = [], collections.Counter()

    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(viewport={'width': 1920, 'height': 1080})
        sem = asyncio.Semaphore(동시)

        async def 한화면(길):
            async with sem:
                pg = await ctx.new_page()
                try:
                    resp = await pg.goto(기준.rstrip('/') + 길, timeout=25000,
                                         wait_until='domcontentloaded')
                    # 🔴 [2026-08-03] 화면이 아닌 것을 세고 있었다.
                    #   자료 응답(JSON·text)과 404 안내가 「글꼴이 규칙 밖」으로 잡혀
                    #   Times New Roman 16곳·sans-serif 13곳이 결함처럼 보였다.
                    #   실제로는 /health 같은 자료 주소와, 로컬에서 꺼 둔 로그인 화면이었다.
                    if resp is not None:
                        ct = (resp.headers or {}).get('content-type', '')
                        if 'text/html' not in ct or resp.status >= 400:
                            합['화면아님'] += 1
                            return
                    # 표를 그리는 자바스크립트를 기다린다.
                    # 🔴 1.4초로는 라이브에서 모자랐다 — 표가 아직 안 그려진 채로 재서
                    #   「공통 규칙이 안 걸린 표」로 잘못 나왔다(자동화 설정 화면).
                    await pg.wait_for_timeout(3000)
                    데이터 = [await pg.evaluate(JS)]
                    for fr in pg.frames:              # 창 안의 창(마진계산기)도 본다
                        if fr == pg.main_frame:
                            continue
                        try:
                            데이터.append(await fr.evaluate(JS))
                        except Exception:
                            pass
                    합['화면'] += 1
                    for d in 데이터:
                        # 글꼴은 「어느 화면이 그랬는지」까지 남긴다 —
                        # 숫자만 세면 Times New Roman 16곳이 진짜 화면인지 빈 창인지 모른다.
                        글꼴들[(d.get('글꼴') or '?', 길)] += 1
                        for t in d.get('표', []):
                            합['표'] += 1
                            if t['동기화']:
                                합['동기화표'] += 1
                            for c in t['칸']:
                                합['칸'] += 1
                                if abs(c['차']) > 허용어긋남:
                                    합['어긋남'] += 1
                                    나쁜곳.append((길, t['클래스'], c['이름'], c['값정렬'], c['차']))
                except Exception as e:
                    print('   (건너뜀) %s — %s' % (길, str(e)[:60]))
                finally:
                    await pg.close()

        await asyncio.gather(*[한화면(g) for g in 화면들])
        await b.close()
    return 합, 나쁜곳, 글꼴들


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--기준', required=True)
    ap.add_argument('--화면', default='')
    ap.add_argument('--동시', type=int, default=4)
    a = ap.parse_args()

    화면들 = 화면목록()
    if a.화면:
        고른 = [s.strip() for s in a.화면.split(',') if s.strip()]
        화면들 = [g for g in 화면들 if any(g.startswith(s) for s in 고른)]

    print('=' * 62)
    print(' 표 정렬 전수 실측 — %s' % a.기준)
    print(' 화면 %d개' % len(화면들))
    print('=' * 62)

    합, 나쁜곳, 글꼴들 = asyncio.run(달리기(a.기준, 화면들, a.동시))

    print('-' * 62)
    print(' 훑은 화면 %d개 (화면 아닌 주소 %d개 제외) · 표 %d개 · 칸 %d개'
          % (합['화면'], 합['화면아님'], 합['표'], 합['칸']))
    print(' 공통 규칙이 걸린 표 : %d / %d 개' % (합['동기화표'], 합['표']))
    print(' 머리글↔값 어긋난 칸 : %d 곳' % 합['어긋남'])
    글꼴합 = collections.Counter()
    for (f, 길), v in 글꼴들.items():
        글꼴합[f] += v
    print(' 화면 글꼴 : %s' % ', '.join('%s×%d' % (k, v) for k, v in 글꼴합.most_common(6)))
    for f, _ in 글꼴합.most_common():
        if 'pretendard' in f.lower():
            continue
        곳 = sorted(set(길 for (ff, 길) in 글꼴들 if ff == f))
        print('   └ %-18s %s' % (f, ', '.join(곳[:6]) + (' 외 %d' % (len(곳) - 6) if len(곳) > 6 else '')))
    if 나쁜곳:
        print('-' * 62)
        print(' 어긋난 곳 (많은 순 20개)')
        묶음 = collections.Counter((x[0], x[1]) for x in 나쁜곳)
        for (길, 클래스), c in 묶음.most_common(20):
            보기 = [x for x in 나쁜곳 if x[0] == 길 and x[1] == 클래스][:3]
            print('   %-28s %-22s %2d곳  예: %s'
                  % (길[:28], 클래스[:22], c,
                     ', '.join('%s %+dpx' % (v[2], v[4]) for v in 보기)))
    print('-' * 62)
    out = os.path.join(ROOT, '_align_audit.json')
    json.dump({'합': 합, '나쁜곳': 나쁜곳[:500]}, open(out, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(' 원자료: %s' % out)


if __name__ == '__main__':
    main()
