# -*- coding: utf-8 -*-
"""지어낸 색 이름을 잡는다 — 어두운 타입에서 흰 판이 되는 조용한 사고.

2026-08-02 실제 사고
    새 메뉴가 `background:var(--면,#fff)` 처럼 색 이름을 **지어서** 썼다.
    `--면`·`--선`·`--글자`·`--면-보조` 는 어디에도 정의된 적 없는 이름이라,
    브라우저는 예비값(흰 바탕·검정 글자)을 그대로 쓴다. 그래서 검정 화면
    한가운데 흰 카드 4장이 떠 있었다(라이브 실측: 흰 판 4곳 · 설명 글자 2.87).

    ★ 예비값이 있어서 **에러도 안 나고 검사도 다 통과한다.** 밝은 화면에서
      개발하면 멀쩡해 보이므로, 검정 타입을 안 켜 보면 영영 안 드러난다.
      실제로 이 사고는 라이브 전수 대비 측정에서야 발견됐다.

무엇을 보나
    templates/·static/ 의 `var(--이름)` 이 어딘가에 **정의된 이름**인지 본다.
    정의는 tokens.css 뿐 아니라 어느 CSS·템플릿의 <style> 이든 인정한다
    (화면이 자기 이름을 만들어 쓰는 것 자체는 정상이다 — 안 만들고 쓰는 게 문제).

기준선 방식
    이미 있던 것(자바스크립트가 값을 넣어 주는 이름 등)까지 지금 다 고치면
    범위가 커진다. **지금 있는 것은 그대로 두고, 새로 늘어나면 실패**하게 한다.
    새 이름이 필요하면 tokens.css 에 정의를 추가하고 이 목록에서 지우면 된다.
"""
import io
import os
import re
import sys

_시스템 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
_웹앱 = os.path.join(_시스템, 'webapp')

_정의_줄머리 = re.compile(r'(?m)^\s*(--[A-Za-z0-9_가-힣-]+)\s*:')
# 화면이 style="--이름:값" 으로 그 자리에서 만들어 쓰는 것도 정의로 인정한다
# (예: track/index.html 이 소싱처마다 색을 넣어 주는 --src-color).
_정의_중괄호 = re.compile(r'''[{;"']\s*(--[A-Za-z0-9_가-힣-]+)\s*:''')
_사용 = re.compile(r'var\(\s*(--[A-Za-z0-9_가-힣-]+)')

# 2026-08-02 기준 이미 있던 것 — 대부분 자바스크립트가 `style.setProperty` 로
# 값을 넣어 주거나(--mcl-scale·--bcm-pct·--pct·--tn-shift), 설명글 안의 예시다(--토큰).
# 여기 있는 이름은 「봐준다」는 뜻이지 「옳다」는 뜻이 아니다 — 줄이면 좋다.
알려진_미정의 = {
    '--warning', '--n50', '--p', '--brand', '--mcl-scale', '--토큰', '--r-lg',
    '--bcm-pct', '--primary-dim', '--dim', '--tn-shift',
    '--fw-보통', '--r-md', '--shadow-md', '--pct', '--primary-d', '--ok-strong',
    '--ln', '--delb', '--accent-soft',
    # 마진계산기는 원본을 무수정 이식하는 화면이라 여기서 못 고친다
    # (tools/build_margin_embed.py). 1곳뿐이라 봐준다 — 「상위 200건만 표시」 안내글.
    '--mut',
}


def _파일들():
    for 루트, _d, fs in os.walk(_웹앱):
        for f in fs:
            if f.endswith(('.css', '.html', '.js')):
                yield os.path.join(루트, f)


def _읽기(p):
    return io.open(p, encoding='utf-8', errors='replace').read()


def test_지어낸_색_이름이_없다():
    파일 = list(_파일들())
    정의 = set()
    for p in 파일:
        s = _읽기(p)
        정의 |= set(_정의_줄머리.findall(s)) | set(_정의_중괄호.findall(s))

    새로운 = {}
    for p in 파일:
        for 이름 in set(_사용.findall(_읽기(p))):
            if 이름 in 정의 or 이름 in 알려진_미정의:
                continue
            새로운.setdefault(이름, set()).add(
                os.path.relpath(p, _웹앱).replace(os.sep, '/'))

    assert not 새로운, (
        '어디에도 정의되지 않은 색 이름 %d종 — 어두운 타입에서 예비값(대개 흰색)이\n'
        '그대로 나와 검정 화면에 흰 판이 뜬다. tokens.css 에 이름을 정의하거나\n'
        '실재하는 이름(--surface·--surface2·--line·--ink·--글자-보조 …)으로 바꿔라.\n%s'
        % (len(새로운), '\n'.join('  %s — %s' % (k, ', '.join(sorted(v))[:80])
                                  for k, v in sorted(새로운.items())))
    )


def test_한_단_옅은_판_이름이_반드시_있다():
    """--surface2 가 비면 그 이름을 쓴 배경 선언이 통째로 무효가 된다(배경이 사라진다).

    [2026-08-02] 타입이 화이트 하나뿐이라 「모든 타입에」가 「기본과 화이트에」로 줄었다.
    """
    s = _읽기(os.path.join(_웹앱, 'static', 'tokens.css'))
    assert re.search(r'(?m)^\s*--surface2\s*:', s),         '--surface2 기본값이 없다 — 그 이름을 쓴 배경이 통째로 사라진다'
    블록 = re.search(r'\.ds\.ds-light\s*\{(.*?)\}', s, re.S)
    assert 블록, '.ds.ds-light 블록을 못 찾았다'
    assert '--surface2' in 블록.group(1), '화이트 타입에 --surface2 가 없다'
