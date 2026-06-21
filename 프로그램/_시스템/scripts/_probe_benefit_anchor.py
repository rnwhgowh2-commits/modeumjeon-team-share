# -*- coding: utf-8 -*-
"""SSG·롯데아이몰 PDP 에서 혜택영역 bottom_anchor 후보 셀렉터 조사.

가격(anchor)부터 혜택 끝까지 동적 확장하려면, 혜택 마지막 줄을 포함하는
'클래스 있는 컨테이너'를 찾아야 한다. 핵심 텍스트(카드혜택가/구매혜택/구매적립/
최대할인가/적립)를 가진 요소의 조상 체인 + bounding box bottom 을 출력.
"""
from __future__ import annotations
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import config  # noqa
from playwright.sync_api import sync_playwright
from lemouton.sourcing import auth as sauth
from lemouton.sourcing.screenshot import profile_for, latest_account

_JS = r"""(keywords) => {
  const out = [];
  const all = document.querySelectorAll('*');
  for (const kw of keywords) {
    let best = null;
    for (const el of all) {
      // 텍스트가 el 에 직접 포함되고 자식이 적은(잎에 가까운) 요소
      if ((el.textContent||'').includes(kw) && el.children.length <= 3) {
        const r = el.getBoundingClientRect();
        if (r.height>0 && r.width>0) { best = el; }
      }
    }
    if (!best) { out.push(`[${kw}] 없음`); continue; }
    // 조상 체인 (class 있는 것 위주) + bbox
    let node = best, chain = [];
    for (let i=0;i<6 && node;i++){
      const r = node.getBoundingClientRect();
      chain.push(`${node.tagName.toLowerCase()}.${(node.className||'').toString().trim().replace(/\s+/g,'.')||'(noclass)'} [y=${Math.round(r.y)} h=${Math.round(r.height)} bottom=${Math.round(r.y+r.height)}]`);
      node = node.parentElement;
    }
    out.push(`[${kw}]\n   ` + chain.join('\n   '));
  }
  return out.join('\n');
}"""

TARGETS = [
    ("SSG", "https://www.ssg.com/item/itemView.ssg?itemId=1000799167650&siteNo=6009&salestrNo=1010",
     ["카드혜택가", "상품쿠폰", "구매혜택", "충전결제", "배송"]),
    ("롯데아이몰", "https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559329941",
     ["최대할인가", "청구할인", "무이자", "적립", "할인 혜택"]),
]


def run_one(name, url, keywords):
    prof = profile_for(name)
    print("\n" + "=" * 70)
    print(f"# {name}  prof_anchor={prof.get('anchors')} box={prof.get('box')} login={prof.get('login')}")
    print("=" * 70)
    with sync_playwright() as p:
        logged = False
        if prof.get("login"):
            ls, la = prof["login"]
            la = la or latest_account(ls)
            if la and sauth.has_state(ls, la):
                browser, ctx = sauth.new_context_with_state(p, ls, la); logged = True
        if not logged:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36")
        try:
            page = ctx.new_page()
            page.set_viewport_size({"width": prof.get("viewport") or 1280, "height": 1600})
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            res = page.evaluate(_JS, keywords)
            print(res)
        finally:
            browser.close()


def main():
    for name, url, kws in TARGETS:
        try:
            run_one(name, url, kws)
        except Exception as e:
            print(f"[{name}] FAIL {repr(e)[:160]}")


if __name__ == "__main__":
    main()
