# -*- coding: utf-8 -*-
"""「대량등록」을 위쪽 메뉴 어디에 넣을지 — 시안 3개를 만든다.

왜 스크립트로 만드나
    위쪽 메뉴는 이미 화면에 있는 것이다. 손으로 옮겨 그리면 반드시 항목이 빠진다.
    실제로 뜬 화면에서 **머리 막대 통째**와 **꾸밈(css) 통째**를 떼어다 쓰고,
    새로 넣는 것은 「대량등록」 한 덩어리뿐이다.

증명 방법 (자기 보고 금지)
    각 시안에서 **새로 넣은 덩어리만 도로 빼면 원본과 글자 하나까지 같아야 한다.**
    같지 않으면 만들다 만 것이므로 멈춘다.

쓰는 법
    python scripts/gen_bulk_menu_mockup.py            # 확인 서버(5190)에서 떼어와 만든다
"""
from __future__ import annotations

import io
import os
import pathlib
import re
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

_시스템 = pathlib.Path(__file__).resolve().parents[1]
_정적 = _시스템 / 'webapp' / 'static'
_서버 = os.environ.get('MOCKUP_BASE', 'http://localhost:5190')
_나갈곳 = pathlib.Path(os.path.expanduser('~')) / 'Desktop' / '모음전 시안 v1 — 대량등록 메뉴 위치.html'

_꾸밈 = ['tokens.css', 'toss.css', 'airy.css', 'scope_fix.css',
         'badge_bg_fix.css', 'inline_color_fix.css', 'topnav.css']


def _받기(길: str) -> str:
    return urllib.request.urlopen(_서버 + 길, timeout=30).read().decode('utf-8', 'replace')


def 머리막대(html: str) -> str:
    """화면에 실제로 뜬 머리 막대를 통째로 떼어낸다."""
    m = re.search(r'<header class="tn"[^>]*>.*?</header>', html, re.S)
    if not m:
        raise SystemExit('머리 막대를 못 찾았다 — 확인 서버가 떠 있는지 보라')
    return m.group(0)


def 대량등록_탭들(html: str) -> list[tuple[str, str, str]]:
    """대량등록 화면 안쪽 탭 8개 — (주소, 그림, 이름). 화면에 뜬 그대로."""
    out = []
    for 주소, 글 in re.findall(r'href="(/bulk/\?tab=[a-z_]+)"[^>]*>\s*([^<]+?)\s*<', html):
        글 = ' '.join(글.split())
        그림, _, 이름 = 글.partition(' ')
        if (주소, 그림, 이름) not in out:
            out.append((주소, 그림, 이름 or 글))
    return out


def _펼침(탭들) -> str:
    """새로 넣는 덩어리 — 원본과 같은 부품 이름을 그대로 쓴다."""
    칸 = []
    for i in (0, 4):
        줄 = ''.join(
            '<a class="tn-ml" href="%s"><span class="tn-emo">%s</span>'
            '<span class="tn-ml-n">%s</span></a>' % (주소, 그림, 이름)
            for 주소, 그림, 이름 in 탭들[i:i + 4])
        제목 = '만들기·보내기' if i == 0 else '보기·챙기기'
        칸.append('<div class="tn-col"><div class="tn-col-t">%s</div>%s</div>' % (제목, 줄))
    return ''.join(칸)


def 시안_A(머리: str, 탭들) -> tuple[str, str]:
    """A안 — 위쪽 막대에 「대량등록」 자리를 하나 더 (모음전과 나란히)."""
    덩어리 = ('<div class="tn-tab" data-tab="bulk" tabindex="0">'
              '<span class="tn-tab-n">대량등록</span>'
              '<div class="tn-mega">%s</div></div>' % _펼침(탭들))
    자리 = '</nav>'
    return 머리.replace(자리, 덩어리 + 자리, 1), 덩어리


def 시안_B(머리: str, 탭들) -> tuple[str, str]:
    """B안 — 「옵션생성 & 상품생성」 펼침 안에 「대량등록」 칸을 하나 더."""
    덩어리 = ('<div class="tn-col"><div class="tn-col-t">대량등록</div>'
              '<a class="tn-ml" href="/bulk/"><span class="tn-emo">📚</span>'
              '<span class="tn-ml-n">대량등록 첫 화면</span></a>'
              + ''.join('<a class="tn-ml" href="%s"><span class="tn-emo">%s</span>'
                        '<span class="tn-ml-n">%s</span></a>' % (주소, 그림, 이름)
                        for 주소, 그림, 이름 in 탭들[:3])
              + '</div>')
    m = re.search(r'<div class="tn-tab[^"]*" data-tab="s_collect".*?</div>\s*</div>\s*</div>',
                  머리, re.S)
    if not m:
        raise SystemExit('「옵션생성 & 상품생성」 자리를 못 찾았다')
    끝 = m.end() - len('</div></div>')
    끝 = 머리.index('</div>', 머리.index('</div>', 끝 - 200))
    # 펼침 상자(tn-mega)가 닫히기 직전에 칸을 하나 더 넣는다
    앞 = 머리[:m.start()]
    몸 = m.group(0)
    자리 = 몸.rindex('</div>', 0, 몸.rindex('</div>'))
    새몸 = 몸[:자리] + 덩어리 + 몸[자리:]
    return 앞 + 새몸 + 머리[m.end():], 덩어리


def 시안_C(머리: str, 탭들) -> tuple[str, str]:
    """C안 — 오른쪽에 바로가기 한 줄 (「로드맵」이 있던 자리)."""
    덩어리 = '<a class="tn-loose" href="/bulk/">대량등록</a>'
    자리 = '<span class="tn-user">'
    return 머리.replace(자리, 덩어리 + 자리, 1), 덩어리


_안내 = {
    'a': ('A안. 위쪽 막대에 나란히',
          '「대량등록」이 다른 묶음들과 같은 줄에 늘 보입니다. 한 번에 눌러 들어갑니다.',
          '늘 보임 · 한 번에 · 「모음전과 다른 일」이 한눈에'),
    'b': ('B안. 「옵션생성 & 상품생성」 안에',
          '지금 메뉴를 늘리지 않습니다. 「옵션생성 & 상품생성」에 마우스를 올리면 오른쪽 끝에 나옵니다.',
          '메뉴 안 늘어남 · 두 번 거쳐야 함 · 이름 겹침 걱정'),
    'c': ('C안. 오른쪽에 바로가기',
          '「로드맵」이 있던 자리에 글자 하나로 놓습니다. 늘 보이되 조용합니다.',
          '늘 보임 · 한 번에 · 안쪽 8개는 안 보임'),
}


def build() -> str:
    집 = _받기('/')
    머리 = 머리막대(집)
    탭들 = 대량등록_탭들(_받기('/bulk/'))
    if len(탭들) < 8:
        raise SystemExit('대량등록 안쪽 탭을 %d 개밖에 못 찾았다' % len(탭들))

    판 = {}
    for 키, 만들기 in (('a', 시안_A), ('b', 시안_B), ('c', 시안_C)):
        새, 덩어리 = 만들기(머리, 탭들)
        # ★ 증명 — 넣은 덩어리만 도로 빼면 원본과 글자 하나까지 같아야 한다
        되돌림 = 새.replace(덩어리, '', 1)
        if 되돌림 != 머리:
            raise SystemExit('%s안: 원본이 바뀌었다 — 만들다 말았다' % 키.upper())
        판[키] = 새
    print('보존 증명 — 세 시안 모두 「넣은 것만 빼면 원본과 동일」 통과')

    꾸밈 = '\n'.join('/* ==== %s ==== */\n%s' % (n, io.open(_정적 / n, encoding='utf-8').read())
                     for n in _꾸밈 if (_정적 / n).exists())

    탭단추 = ''.join(
        '<button class="v-tab%s" data-target="%s"><div class="v-name">%s</div>'
        '<div class="v-desc">%s</div><div class="v-meta"><span class="v-key">%d</span>%s</div>'
        '</button>' % (' on' if k == 'a' else '', k, _안내[k][0], _안내[k][1], i + 1,
                       ' ← 추천' if k == 'a' else '')
        for i, k in enumerate(('a', 'b', 'c')))

    판들 = ''.join(
        '<div class="variant-pane%s" id="pane-%s">'
        '<div class="mock-win"><div class="mock-bar"><span>●●●</span>'
        '<span class="url">mou-m.com</span></div>'
        '<div class="ds ds-light mock-live">%s'
        '<div class="mock-body"><div class="mock-note">%s</div></div></div></div></div>'
        % (' on' if k == 'a' else '', k, 판[k], _안내[k][2])
        for k in ('a', 'b', 'c'))

    return _틀 % {'꾸밈': 꾸밈, '탭단추': 탭단추, '판들': 판들}


_틀 = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>모음전 시안 — 「대량등록」 메뉴 위치</title>
<style>%(꾸밈)s</style>
<style>
 body { margin:0; background:#F2F4F6; font-family:-apple-system,BlinkMacSystemFont,'Malgun Gothic',sans-serif; color:#1D1D1F; }
 .wrap { max-width:1920px; margin:0 auto; padding:20px 24px 60px; }
 h1 { font-size:22px; font-weight:700; margin:0 0 4px; }
 .lead { font-size:14px; color:#6E6E73; line-height:1.6; margin:0 0 18px; }
 .reco { background:#fff; border:1px solid #E5E8EB; border-left:4px solid #0071E3; border-radius:10px;
         padding:14px 18px; font-size:14px; line-height:1.7; margin:0 0 18px; }
 .reco b { color:#0071E3; }
 .variant-tabs { position:sticky; top:0; z-index:50; display:flex; gap:10px; background:#F2F4F6;
                 padding:10px 0 14px; }
 .v-tab { flex:1; text-align:left; background:#fff; border:1px solid #E5E8EB; border-radius:10px;
          padding:12px 16px; cursor:pointer; font-family:inherit; }
 .v-tab.on { border-color:#0071E3; box-shadow:0 0 0 2px rgba(0,113,227,.15); }
 .v-name { font-size:15px; font-weight:700; margin-bottom:3px; }
 .v-desc { font-size:12.5px; color:#6E6E73; line-height:1.5; }
 .v-meta { font-size:12px; color:#0071E3; margin-top:6px; font-weight:600; }
 .v-key { display:inline-block; background:#F2F4F6; color:#6E6E73; border-radius:4px;
          padding:1px 6px; margin-right:6px; font-weight:700; }
 .variant-pane { display:none; } .variant-pane.on { display:block; }
 .mock-win { background:#fff; border:1px solid #d1d6db; border-radius:10px; overflow:hidden;
             box-shadow:0 4px 12px rgba(0,0,0,.08); }
 .mock-bar { background:#f2f4f6; padding:10px 16px; font-size:12px; color:#6b7684;
             border-bottom:1px solid #e5e8eb; display:flex; align-items:center; gap:8px; }
 .mock-bar .url { background:#fff; padding:4px 12px; border-radius:5px;
                  font-family:ui-monospace,monospace; font-size:11.5px; flex:1; }
 .mock-live { background:#fff; }
 .mock-body { min-height:620px; background:#F9FAFB; padding:28px; }
 .mock-note { display:inline-block; background:#fff; border:1px solid #E5E8EB; border-radius:8px;
              padding:10px 16px; font-size:13.5px; color:#6E6E73; }
 table.cmp { width:100%%; border-collapse:collapse; background:#fff; margin-top:22px;
             border:1px solid #E5E8EB; border-radius:10px; overflow:hidden; font-size:13.5px; }
 table.cmp th, table.cmp td { padding:11px 14px; border-bottom:1px solid #F2F4F6; }
 table.cmp th { background:#FAFAFA; font-weight:600; text-align:left; color:#6E6E73; }
 table.cmp td.mid { text-align:center; }
 .hint { font-size:12.5px; color:#6E6E73; margin-top:14px; line-height:1.7; }
</style></head><body><div class="wrap">
<h1>「대량등록」을 위쪽 메뉴 어디에 넣을까요</h1>
<p class="lead">막대 위에 <b>마우스를 올리면</b> 실제처럼 펼쳐집니다. 탭을 눌러 바꿔 보세요 (숫자 <b>1·2·3</b> 또는 <b>←/→</b>).</p>
<div class="reco"><b>A안을 추천합니다.</b> 「대량등록」 안에는 「상품관리·주문관리·통계」가 <b>따로 또 있습니다</b>.
 지금 메뉴 묶음과 이름이 겹치므로, 묶음 <b>안에</b> 넣으면 같은 이름이 두 곳에 생겨 매번 헷갈립니다.
 <b>나란히</b> 두면 「모음전 쪽 일」과 「대량등록 쪽 일」이 갈려 보입니다.</div>
<div class="variant-tabs">%(탭단추)s</div>
%(판들)s
<table class="cmp"><tr><th>견주는 점</th><th class="mid">A. 나란히</th><th class="mid">B. 묶음 안에</th><th class="mid">C. 오른쪽 바로가기</th></tr>
<tr><td>늘 보이나</td><td class="mid">보임</td><td class="mid">안 보임(올려야 나옴)</td><td class="mid">보임</td></tr>
<tr><td>몇 번 눌러 들어가나</td><td class="mid">1번</td><td class="mid">2번</td><td class="mid">1번</td></tr>
<tr><td>안쪽 8개가 미리 보이나</td><td class="mid">보임</td><td class="mid">일부만</td><td class="mid">안 보임</td></tr>
<tr><td>이름 겹침(상품관리·주문관리)</td><td class="mid">갈려 보임</td><td class="mid">헷갈림</td><td class="mid">갈려 보임</td></tr>
<tr><td>위쪽 막대가 길어지나</td><td class="mid">한 칸 늘어남</td><td class="mid">그대로</td><td class="mid">그대로</td></tr></table>
<p class="hint"><b>확인해 주실 것</b> — ① 막대에 올렸을 때 펼침이 제대로 뜨는지 ② 「대량등록」 글자 크기·간격이 옆 항목과 같은지 ③ 겹쳐 보이는 곳은 없는지<br>
<b>다음</b> — 「A로 갈게요」 한 마디면 그대로 화면에 넣습니다. 「A인데 이름은 □□로」처럼 섞거나 고쳐도 됩니다.</p>
</div><script>
const tabs=document.querySelectorAll('.v-tab'), panes=document.querySelectorAll('.variant-pane');
function activate(t){tabs.forEach(x=>x.classList.toggle('on',x.dataset.target===t));
 panes.forEach(p=>p.classList.toggle('on',p.id==='pane-'+t));}
tabs.forEach(t=>t.addEventListener('click',()=>activate(t.dataset.target)));
document.addEventListener('keydown',e=>{const o=[...tabs].map(t=>t.dataset.target);
 const c=document.querySelector('.v-tab.on').dataset.target,i=o.indexOf(c);
 if(/^[1-9]$/.test(e.key)&&o[+e.key-1])activate(o[+e.key-1]);
 else if(e.key==='ArrowRight'&&i<o.length-1)activate(o[i+1]);
 else if(e.key==='ArrowLeft'&&i>0)activate(o[i-1]);});
</script></body></html>"""


def main() -> int:
    html = build()
    _나갈곳.parent.mkdir(parents=True, exist_ok=True)
    io.open(_나갈곳, 'w', encoding='utf-8').write(html)
    print('SAVED:', _나갈곳, '·', len(html), '자')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
