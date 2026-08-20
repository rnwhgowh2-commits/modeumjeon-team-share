# -*- coding: utf-8 -*-
"""확장이 **다음 쪽 주소를 실제로 풀 수 있는지** — node 로 그 식을 돌려 본다.

🔴🔴 왜 이 시험이 있나 (2026-08-12 라이브)
   무신사 검증 필터를 1~60쪽으로 시켰는데 **47개**(첫 쪽 분량)만 걷고
   「끝남 · 더 없음 · 오류 없음」이라 답했다. 확장 판은 0.7.94 가 맞았다.

   원인은 다음 쪽 주소를 푸는 식이 **정규식이 아니었던 것**이다.

       m0[1].replace(/\\u0026/g, '&').replace(/\\\\//g, '/')
                                              ^^^^^^^^
   JS 는 세 번째 `/` 에서 정규식을 닫아 버린다. 남은 `/g` 는 **정의 안 된 변수 `g`
   로 나누기**가 되어 `ReferenceError: g is not defined` 를 던졌고, 바깥
   `catch (e) {}` 가 그걸 삼켰다. 그래서 `url` 은 늘 `null` 이었고 쪽 넘김이
   **한 번도 시작되지 않았다.**

   🔴 문법 검사(`node --check`)로는 절대 안 잡힌다 — **문법은 맞다.**
     그래서 「글자가 있나」가 아니라 **그 식을 실제로 돌려** 결과를 본다.

★ 앞 세션은 이 47 을 「확장이 옛 판이라서」로 진단했는데 **틀렸다.**
  판을 새로 맞춘 뒤에도 47 그대로였다.
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

#: 무신사가 실제로 내려주는 모양 — JSON 안이라 `/` 가 `\/`, `&` 가 `&` 다.
SAMPLE = r'https:\/\/www.musinsa.com\/api\/search?page=2&hmacId=abc'
WANT = 'https://www.musinsa.com/api/search?page=2&hmacId=abc'


def _node():
    exe = shutil.which('node')
    if not exe:
        pytest.skip('node 가 없는 환경')
    return exe


def _helper_src() -> str:
    """`_listingCollectIds` 안에 심어 둔 주소 푸는 함수를 통째로 꺼낸다."""
    src = BG.read_text(encoding='utf-8')
    m = re.search(r'function _unescapeJsonUrl\(s\) \{.*?\n  \}', src, re.S)
    assert m, ('background.js 에서 `_unescapeJsonUrl` 을 못 찾았습니다. '
               '이름이 바뀌었다면 이 시험도 같이 고쳐야 합니다 — '
               '못 찾은 채 통과하면 아무것도 안 보는 시험이 됩니다.')
    return m.group(0)


def test_주소_푸는_함수가_있다():
    assert _helper_src().strip().startswith('function _unescapeJsonUrl')


def test_다음쪽_주소를_진짜로_푼다():
    """🔴 이게 이 파일의 핵심 — 식을 **실제로 돌려** 결과를 본다."""
    script = _helper_src() + f'''
try {{
  const got = _unescapeJsonUrl({json.dumps(SAMPLE)});
  console.log(JSON.stringify({{ ok: true, got: got }}));
}} catch (e) {{
  console.log(JSON.stringify({{ ok: false, err: e.constructor.name + ': ' + e.message }}));
}}
'''
    r = subprocess.run([_node(), '-e', script], capture_output=True, timeout=30)
    out = json.loads(r.stdout.decode('utf-8').strip() or '{}')
    assert out.get('ok'), (
        '주소를 푸는 식이 **돌다가 죽습니다** — 다음 쪽 주소가 늘 없는 것이 되고, '
        f'그런데도 「끝남」이라 답하게 됩니다.\n{out.get("err")}'
    )
    assert out['got'] == WANT, (
        f'푼 결과가 다릅니다.\n  나온 것: {out["got"]}\n  나와야 할 것: {WANT}'
    )


def test_안_푼_주소가_그대로_남지_않는다():
    """역슬래시가 남으면 그 주소로 부를 수 없다 — 조용히 실패한다."""
    script = _helper_src() + f'''
console.log(JSON.stringify({{got: _unescapeJsonUrl({json.dumps(SAMPLE)})}}));
'''
    r = subprocess.run([_node(), '-e', script], capture_output=True, timeout=30)
    got = json.loads(r.stdout.decode('utf-8').strip())['got']
    assert '\\' not in got, f'역슬래시가 남았습니다: {got}'
    assert '\\u0026' not in got and 'u0026' not in got


def test_여러쪽을_시켰는데_다음쪽을_못_찾으면_더있음으로_답한다():
    """🔴 「못 봤다」와 「없다」를 가른다.

    이 줄이 없으면 첫 쪽만 걷고도 「끝남 · 더 없음」이 되어, 사장님이
    「이 검색엔 47개뿐」이라고 믿게 된다.
    """
    src = BG.read_text(encoding='utf-8')
    assert re.search(r'if \(want > 1 && !url\) capped = true;', src), (
        '여러 쪽을 시켰는데 다음 쪽 주소를 못 찾은 경우를 「더 있음」으로 '
        '표시하는 줄이 없습니다 — 조용한 「끝남」이 됩니다.'
    )
