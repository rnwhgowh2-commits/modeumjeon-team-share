# -*- coding: utf-8 -*-
"""안 보이는 글자 전수 감사 — 「진한 의미색 판 위의 글자」 대비를 실제 렌더에서 잰다.

토큰 설계(tokens.css): `--바탕-{색}` 은 **흰 글자를 얹는 진한 배경**이다.
그 판 위에 흰 글자가 아닌 것이 얹히면 글자가 묻힌다(포장 스캔에서 실제로 그랬다).

원문 대조로는 판정할 수 없다 — `[style*="color: white"]` 처럼 다른 규칙이
흰 글자를 이미 주는 자리가 많아 거짓 양성이 쏟아진다. 그래서 렌더 후 계산값으로 잰다.
"""
import sys, json, time
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5225"
MAX_PAGES = int(sys.argv[2]) if len(sys.argv) > 2 else 40

SEEDS = ["/", "/mobile", "/mobile/menu", "/mobile/scan", "/mobile/scan-batch?mode=in",
         "/mobile/scan-ship", "/mobile/inventory", "/mobile/orders", "/mobile/settle"]

PROBE = r"""
() => {
  const 배경용 = {                       // --바탕-{색} 실제값 (tokens.css)
    'rgb(29, 122, 61)':'초록', 'rgb(199, 51, 43)':'빨강',
    'rgb(154, 91, 0)':'주황',  'rgb(0, 102, 204)':'파랑',
  };
  const 상대휘도 = (r,g,b) => {
    const f = v => { v/=255; return v<=0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); };
    return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b);
  };
  const 뜯기 = s => (s.match(/[\d.]+/g)||[]).map(Number);
  const 대비 = (a,b) => {
    const L1=상대휘도(...a.slice(0,3)), L2=상대휘도(...b.slice(0,3));
    const hi=Math.max(L1,L2), lo=Math.min(L1,L2);
    return (hi+0.05)/(lo+0.05);
  };
  const 칠해진배경 = el => {                // 투명이면 조상으로 거슬러 올라간다
    let n = el;
    while (n && n !== document.documentElement) {
      const bg = getComputedStyle(n).backgroundColor;
      const v = 뜯기(bg);
      if (v.length >= 3 && (v.length < 4 || v[3] > 0.5)) return {색: bg, 요소: n};
      n = n.parentElement;
    }
    return null;
  };
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    const 글 = (el.textContent||'').trim();
    if (!글 || 글.length > 60) continue;
    // 글자를 직접 가진 요소만 (자식이 대신 그리는 껍데기는 제외)
    const 직접 = [...el.childNodes].some(n => n.nodeType===3 && n.textContent.trim());
    if (!직접) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity < 0.1) continue;
    const bg = 칠해진배경(el);
    if (!bg) continue;
    const 이름 = 배경용[bg.색];
    if (!이름) continue;                    // 진한 의미색 판 위만 본다
    const fg = 뜯기(cs.color);
    const c = 대비(fg, 뜯기(bg.색));
    if (c >= 4.5) continue;                 // 읽을 수 있으면 통과
    out.push({판: 이름, 대비: Math.round(c*100)/100, 글자색: cs.color, 판색: bg.색,
              글: 글.slice(0,28),
              자리: el.tagName.toLowerCase() + (el.className && typeof el.className==='string'
                    ? '.' + el.className.trim().split(/\s+/).slice(0,3).join('.') : ''),
              크기: cs.fontSize});
  }
  return out;
}
"""

LINKS = r"""
() => [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))
        .filter(h => h && h.startsWith('/') && !h.startsWith('//'))
        .filter(h => !/\/(static|api)\//.test(h) && !/\.(json|md|xlsx|csv|png|jpg)$/.test(h))
        .filter(h => !/\/(download|export|logout)/.test(h))
"""


def main():
    본 = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("pageerror", lambda e: None)
        큐, 본목록 = list(SEEDS), []
        while 큐 and len(본목록) < MAX_PAGES:
            길 = 큐.pop(0)
            if 길 in 본목록:
                continue
            본목록.append(길)
            try:
                page.goto(BASE + 길, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(900)
            except Exception as e:
                print(f"  (못 염) {길} — {type(e).__name__}", flush=True)
                continue
            try:
                for h in page.evaluate(LINKS):
                    h = h.split("#")[0]
                    if h and h not in 본목록 and h not in 큐 and len(큐) < 120:
                        큐.append(h)
            except Exception:
                pass
            try:
                for h in page.evaluate(PROBE):
                    h["화면"] = 길
                    본.append(h)
            except Exception as e:
                print(f"  (검사 실패) {길} — {type(e).__name__}", flush=True)
        print(f"\n훑은 화면 {len(본목록)}개", flush=True)
        ctx.close(); b.close()

    # 같은 자리 중복 제거
    키 = lambda h: (h["자리"], h["판"], h["글자색"])
    묶음 = {}
    for h in 본:
        묶음.setdefault(키(h), h)
    결과 = sorted(묶음.values(), key=lambda h: h["대비"])
    print(f"대비 4.5 미만 = {len(결과)}곳\n", flush=True)
    for h in 결과:
        print(f"  대비 {h['대비']:>5}  [{h['판']} 판] {h['자리']}  글자 {h['글자색']} · {h['크기']}", flush=True)
        print(f"           「{h['글']}」  ({h['화면']})", flush=True)
    return 결과


if __name__ == "__main__":
    r = main()
    with open("contrast_hits.json", "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
