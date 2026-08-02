# -*- coding: utf-8 -*-
"""어두운 모드에서 「화면이 자기 안에서 다시 정의한 공용 색 이름」을 되돌리는 CSS 를 만든다.

무슨 일이 있었나
  주문 화면 CSS 안에 `.o7 { --ink:#191F28 }` 처럼 밝은 모드 색이 못 박혀 있었다.
  위(.ds.ds-dark)에서 색을 뒤집어도 그 화면 안쪽은 못 박힌 값을 쓰므로
  검정 배경에 검정 글자가 된다.
  라이브 실측(2026-07-31 mou-m.com/orders, 검정 한 판): 기준 미달 507곳, 최악 1.11.

왜 지우지 않고 덮어쓰나
  「현재」 모드에는 .ds 가 안 붙어 tokens.css 의 색이 아예 없다. 화면이 못 박아 둔
  값이 그 모드의 유일한 색이라, 지우면 「현재」(안전망)가 깨진다.

밝은 모드도 같이 낸다 (파일 이름은 dark_ 로 시작하지만 세 모드를 다 다룬다)
  「밝은 카드」에서도 화면이 못 박은 --sub(#8B95A1)이 흰 바탕에서 3.04 로 미달이었다.
  `.ds.ds-dark …` / `.ds.ds-dark.ds-layer …` / `.ds.ds-light …` 세 벌을 낸다.
  「현재」에는 어느 것도 안 걸린다.

쓰는 법
  python scripts/gen_dark_scope_fix.py        # webapp/static/dark_scope_fix.css 를 다시 만든다
  python scripts/gen_dark_scope_fix.py --check # 최신인지만 확인 (테스트가 쓴다)
"""
from __future__ import annotations

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP = os.path.join(HERE, 'webapp')
TOKENS = os.path.join(WEBAPP, 'static', 'tokens.css')
OUT = os.path.join(WEBAPP, 'static', 'dark_scope_fix.css')

# 이 파일들은 보지 않는다 — tokens.css 는 원천 자체고, stripe.css 는 이미 죽은 테마다.
#
# 🔴 [2026-08-02] badge_bg_fix.css 를 뺀 이유 — 여기서는 **일부러** 색 이름을 다시 정한다.
#   사장님 확정으로 팝업(모달)은 흰 바탕을 그대로 둔다. 그런데 팝업 안 글자는 화면
#   전체의 글자색 이름을 물려받아, 어두운 타입에서 **흰 종이에 흰 글자**가 됐다
#   (「옵션 조합 생성 및 수정」 제목이 대비 1.09 로 통째로 안 보였다).
#   그래서 그 팝업 **안에서만** 이름을 밝은 값으로 되돌린다. 이 되돌림을 이 도구가
#   또 되돌리면(=어두운 값으로) 원래 사고로 되돌아간다. 의도된 재정의라 여기서 뺀다.
#   ★ 이 파일이 「기존 타입」에 안 새는지는 test_dark_scope 의 별도 검사가 지킨다.
SKIP = ('tokens.css', 'stripe.css', 'dark_scope_fix.css', 'badge_bg_fix.css')
# 크기·여백 토큰은 모드에 따라 안 바뀌므로 대상이 아니다.
NOT_COLOR = re.compile(r'--(fs|sp|r|fw|lh|ap)-')


def _strip_comments(s: str) -> str:
    return re.sub(r'/\*.*?\*/', ' ', s, flags=re.S)


def _css_blocks(path: str, text: str):
    if path.endswith('.css'):
        return [text]
    return re.findall(r'<style[^>]*>(.*?)</style>', text, re.S | re.I)


def _token_block(tokens_css: str, sel: str) -> dict:
    """같은 선택자 블록이 여러 개면 **뒤에 온 것이 이긴다** — CSS 규칙 그대로.

    ★ 여기서 첫 블록만 읽으면, 나중에 tokens.css 뒤에 값을 고쳐도 이 생성물이
      옛 값을 그대로 박아 넣어 **내가 방금 고친 값을 내가 도로 덮는다.**
      실제로 그렇게 됐다 — `--faint` 를 #8E8E93 으로 올렸는데 이 파일이
      `.ds.ds-dark .o7 { --faint: var(--ap-g45) }`(#6E6E73)로 되돌려 놨다.
    """
    out = {}
    for m in re.finditer(re.escape(sel) + r'\s*\{([^{}]*)\}', tokens_css):
        out.update({k: v.strip() for k, v in
                    re.findall(r'(--[0-9A-Za-z가-힣_-]+)\s*:\s*([^;]+);', m.group(1))})
    return out


def 색이름들(tokens_css: str) -> set:
    names = set(re.findall(r'(--[0-9A-Za-z가-힣_-]+)\s*:', tokens_css))
    return {n for n in names if not NOT_COLOR.match(n)}


def 덮어쓴_곳(색이름: set):
    """{선택자: (파일, {이름…})} — 화면 CSS 가 공용 색 이름을 다시 정의한 자리."""
    found = {}
    for root, _dirs, files in os.walk(WEBAPP):
        for f in sorted(files):
            if not f.endswith(('.html', '.css')) or f in SKIP:
                continue
            p = os.path.join(root, f)
            try:
                text = io.open(p, encoding='utf-8').read()
            except OSError:
                continue
            for blk in _css_blocks(p, text):
                blk = _strip_comments(blk)
                for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', blk):
                    sel = ' '.join(m.group(1).split())
                    names = [n for n in re.findall(r'(--[0-9A-Za-z가-힣_-]+)\s*:', m.group(2))
                             if n in 색이름]
                    if not names or not sel or sel.startswith('@') or 'ds-dark' in sel:
                        continue
                    if sel in (':root', 'html', 'body', ':root,html', ':root, html'):
                        continue
                    파일, 기존 = found.get(sel, (os.path.relpath(p, WEBAPP), set()))
                    found[sel] = (파일, 기존 | set(names))
    return dict(sorted(found.items()))


def build() -> str:
    tokens_css = _strip_comments(io.open(TOKENS, encoding='utf-8').read())
    색이름 = 색이름들(tokens_css)
    dark = _token_block(tokens_css, '.ds.ds-dark')
    base = _token_block(tokens_css, '.ds')

    머리 = io.open(__file__, encoding='utf-8').read().split('"""')[1].strip()
    out = ['/* 이 파일은 손으로 고치지 말 것 — scripts/gen_dark_scope_fix.py 가 만든다.',
           '   화면 CSS 에 공용 색 이름을 새로 못 박으면 tests/design/test_dark_scope.py 가 잡는다.',
           '',
           '   ' + 머리.replace('\n', '\n   '),
           '',
           '   왜 이기나 — `.ds.ds-dark .o7` 은 클래스 3개(0,3,0), 원래 `.o7` 은 1개(0,1,0).',
           '   같은 요소에 걸린 규칙이라 더 구체적인 쪽이 이긴다. */', '']

    # 「검정 3단」은 바탕이 한 단 밝아 같은 색이 문턱 아래로 떨어진다 → 그 모드 전용 값.
    # ★ 이것도 같이 내보내야 한다. 안 그러면 `.ds.ds-dark .o7`(0,3,0) 이 화면 안쪽에서
    #   `.ds.ds-dark.ds-layer`(0,3,0, 바깥 요소) 를 이겨 3단 값이 안 먹는다.
    layer = _token_block(tokens_css, '.ds.ds-dark.ds-layer')
    # 「밝은 카드」도 같은 문제를 겪는다 — 화면이 못 박은 `--sub:#8B95A1`(흰 바탕 3.04)이
    # tokens.css 의 값을 가린다. 어두운 쪽만 고치면 밝은 쪽은 그대로 안 읽힌다.
    light = dict(base)
    light.update(_token_block(tokens_css, '.ds.ds-light'))

    for sel, (파일, names) in 덮어쓴_곳(색이름).items():
        vals, layer_vals, light_vals = [], [], []
        for n in sorted(names):
            v = dark.get(n) or base.get(n)
            if v:
                vals.append('%s: %s;' % (n, v))
            if n in layer:
                layer_vals.append('%s: %s;' % (n, layer[n]))
            if n in light:
                light_vals.append('%s: %s;' % (n, light[n]))
        if not vals:
            continue
        out.append('/* %s */' % 파일.replace('\\', '/'))
        out.append('.ds.ds-dark %s { %s }' % (sel, ' '.join(vals)))
        if layer_vals:
            out.append('.ds.ds-dark.ds-layer %s { %s }' % (sel, ' '.join(layer_vals)))
        if light_vals:
            out.append('.ds.ds-light %s { %s }' % (sel, ' '.join(light_vals)))
    return '\n'.join(out) + '\n'


def main() -> int:
    css = build()
    if '--check' in sys.argv:
        old = io.open(OUT, encoding='utf-8').read() if os.path.exists(OUT) else ''
        if old != css:
            print('dark_scope_fix.css 가 최신이 아니다 — python scripts/gen_dark_scope_fix.py 를 다시 돌려라')
            return 1
        print('최신')
        return 0
    io.open(OUT, 'w', encoding='utf-8').write(css)
    print('SAVED:', OUT, '·', len(css), '자 ·', css.count('.ds.ds-dark '), '개 규칙')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
