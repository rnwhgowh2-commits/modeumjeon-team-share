# -*- coding: utf-8 -*-
"""0건 진단이 **그 화면의 링크 모양**까지 알려 준다.

🔴 왜 필요한가 (2026-08-12 라이브 SSG)
   진단은 이렇게까지 나왔다.

       0건(나이키 신발 - 추천•인기 상품, SSG.COM · 링크 62 · 선택자 0)

   「링크는 62개 있는데 우리 선택자엔 0개」까지는 알았는데 **고칠 수가 없다.**
   그 62개가 어떤 모양인지를 모르기 때문이다.
   SSG 는 브라우저 도구로 열 수 없어(정책 차단) 내 눈으로 확인할 방법이 없다.
   → 확장이 대신 보고 **경로 모양만** 세어 보낸다.

★ 링크 주소를 통째로 보내지 않는다 — 숫자를 `#` 로 뭉갠 **모양**만 센다.
  어느 모양이 상품인지 고르기엔 그걸로 충분하고, 주소를 그대로 나르지 않아도 된다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

BG = (Path(__file__).resolve().parents[2]
      / 'extension' / 'moum-crawler' / 'background.js')


def _node():
    exe = shutil.which('node')
    if not exe:
        pytest.skip('node 가 없는 환경')
    return exe


def _probe_src() -> str:
    """0건일 때 화면을 들여다보는 함수 본문을 꺼낸다."""
    src = BG.read_text(encoding='utf-8')
    m = re.search(r'func: \(s, idRe\) => \{\n(.*?)\n          \},', src, re.S)
    assert m, ('0건 진단 함수를 못 찾았습니다. 구조가 바뀌었다면 이 시험도 '
               '같이 고쳐야 합니다 — 못 찾은 채 통과하면 아무것도 안 봅니다.')
    return m.group(1)


def test_진단_함수를_찾는다():
    body = _probe_src()
    assert '링크모양' in body, '링크 모양을 세는 부분이 없습니다.'


def test_링크_모양을_숫자_뭉개서_센다():
    """🔴 실제로 돌려 본다 — 글자만 세면 안 도는 코드도 통과한다."""
    body = _probe_src()
    script = '''
const { JSDOM } = (() => { try { return require('jsdom'); } catch (e) { return {}; } })();
''' + '''
// jsdom 없이도 되게 최소한의 document/location 을 흉내 낸다.
const HREFS = [
  '/item/itemView.ssg?itemId=1000552535854',
  '/item/itemView.ssg?itemId=1000552535999',
  '/item/itemView.ssg?itemId=1000552536111',
  '/service/help',
  '/service/notice',
];
globalThis.location = { href: 'https://www.ssg.com/search.ssg?query=x' };
globalThis.document = {
  title: '나이키 신발 - 추천 상품, SSG.COM',
  documentElement: { innerHTML: '' },
  querySelectorAll: (sel) => {
    if (sel === 'a[href]') return HREFS.map((h) => ({ getAttribute: () => h }));
    return [];
  },
};
const probe = (s, idRe) => {
''' + body + '''
};
console.log(JSON.stringify(probe('a[href*="itemView.ssg"]', 'itemView[.]ssg[?][^"<>]*?itemId=(\\\\d+)')));
'''
    r = subprocess.run([_node(), '-e', script], capture_output=True, timeout=30)
    out = r.stdout.decode('utf-8').strip()
    assert out, f'진단 함수가 돌다가 죽었습니다:\n{r.stderr.decode("utf-8")[-600:]}'
    d = json.loads(out)
    assert d['링크수'] == 5
    shape = d['링크모양']
    assert '/item/itemView.ssg×3' in shape, (
        f'가장 많은 링크 모양을 못 셌습니다: {shape}')
    assert '1000552535854' not in shape, (
        f'주소를 그대로 실어 보내고 있습니다 — 모양만 세야 합니다: {shape}')


def test_받은_글에도_있는지_같이_센다():
    """🔴 「화면에 없다」가 「안 왔다」는 뜻이 아니다 — H몰이 그랬다.

    이 숫자가 크면 답은 `html_scan` 이고, 이것도 0이면 그 화면엔 정말 상품이 없다.
    이 한 줄이 없어서 H몰 때 있지도 않은 「진짜 마우스 휠」 문제를 쫓았다.
    """
    body = _probe_src()
    script = '''
globalThis.location = { href: 'https://www.hmall.com/p/pda/itemPtc?x=1' };
globalThis.document = {
  title: '나이키 - 현대Hmall',
  documentElement: { innerHTML: '{"slitmCd":"2001112223","x":1},{"slitmCd":"2001112224"}' },
  querySelectorAll: () => [],
};
const probe = (s, idRe) => {
''' + body + '''
};
console.log(JSON.stringify(probe('[data-slitm-cd]', '"slitmCd"\\\\s*:\\\\s*"?(\\\\d{6,})')));
'''
    r = subprocess.run([_node(), '-e', script], capture_output=True, timeout=30)
    out = r.stdout.decode('utf-8').strip()
    assert out, f'진단 함수가 돌다가 죽었습니다:\n{r.stderr.decode("utf-8")[-600:]}'
    d = json.loads(out)
    assert d['선택자수'] == 0, '화면에서는 0개여야 하는 상황을 만든 것이다.'
    assert d['받은글'] == 2, (
        f'받은 글에 상품번호 2개가 있는데 {d["받은글"]}개로 셌습니다 — '
        '이 숫자가 없으면 「html_scan 이 답인가」를 알 수 없습니다.'
    )


def test_진단_문구에_받은글이_실린다():
    src = BG.read_text(encoding='utf-8')
    assert "' · 받은글 '" in src, (
        '진단 문구에 「받은글」이 안 실립니다 — 세어 놓고 안 보내면 소용없습니다.'
    )


def test_진단_문구에_링크모양이_실린다():
    src = BG.read_text(encoding='utf-8')
    assert re.search(r"'\s*·\s*많은 모양 '", src), (
        '진단 문구에 링크 모양이 안 실립니다 — 세어 놓고 안 보내면 소용없습니다.'
    )
