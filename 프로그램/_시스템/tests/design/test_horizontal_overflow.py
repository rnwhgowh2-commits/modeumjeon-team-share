# -*- coding: utf-8 -*-
"""넓은 표가 화면 틀을 통째로 밀어내지 않는지.

사장님 지적(2026-07-31): 「가로로 화면 초과하는 사이즈의 경우 가로스크롤이 있는데
화면 자체가 넘어가고 있음. 화면은 그대로 있고 내용물이 움직여야 함」 (예: 주문관리)

원인 — 가로로 늘어선 상자(`.app { display:flex }`)의 자식은 **기본 최소폭이
`auto` = 내용물 폭**이다. 그래서 넓은 표가 `.main` 을 통째로 늘리고, 그만큼
문서가 옆으로 길어진다. 실브라우저 실측(2026-07-31, 기존 타입, 3,000px 표 주입):

    고치기 전 : 문서폭 3,371 / 창폭 1,265 → 사이드바가 -2,106px 로 화면 밖
    고친 뒤   : 문서폭 1,280 / 창폭 1,280 → 사이드바 0 고정, 표 안쪽만 스크롤

상단탭 경로(topnav.css)에는 이미 `min-width:0` 이 있었다 — 그래서 타입마다
증상이 달라 원인을 찾기 어려웠다. 두 경로를 같게 맞춘 것이다.
"""
import io
import os

_정본 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'webapp', 'static')


def _읽기(파일):
    with io.open(os.path.join(_정본, 파일), encoding='utf-8') as f:
        return f.read()


def _규칙_본문(css, 선택자):
    """`선택자 {` 부터 다음 `}` 까지를 떼어 온다."""
    자리 = css.index(선택자 + ' {')
    끝 = css.index('}', 자리)
    return css[자리:끝 + 1]


def test_사이드바_경로의_main_이_창폭을_지킨다():
    """min-width 가 없으면 넓은 표가 화면 전체를 옆으로 민다."""
    규칙 = _규칙_본문(_읽기('toss.css'), '.main')
    assert 'min-width: 0' in 규칙 or 'min-width:0' in 규칙, (
        '.main 에 min-width:0 이 없다 — 넓은 표가 화면 틀을 통째로 밀어낸다'
    )


def test_상단탭_경로의_main_도_창폭을_지킨다():
    css = _읽기('topnav.css')
    규칙 = _규칙_본문(css, '.app.tn-on > .tn-body > .main')
    assert 'min-width: 0' in 규칙 or 'min-width:0' in 규칙


def test_모음전_상품_격자도_창폭을_지킨다():
    """격자(grid)의 `1fr` 칸도 기본 최소폭이 「내용물 폭」이다 — flex 와 같은 함정.

    라이브 실측(/bundles, 기존 타입): 문서폭 2,281 / 창폭 1,265.
    `.bl-table-wrap` 에 overflow 는 이미 있었지만, 칸이 같이 늘어나 무력화돼 있었다.
    """
    import io as _io
    import os as _os
    p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                      '..', '..', 'webapp', 'templates', 'bundles', 'list.html')
    글 = _io.open(p, encoding='utf-8').read()
    자리 = 글.index('.d1-layout { display: grid;')
    규칙 = 글[자리:글.index('}', 자리) + 1]
    assert 'minmax(0, 1fr)' in 규칙 or 'minmax(0,1fr)' in 규칙, (
        '.d1-layout 의 1fr 칸에 minmax(0,…) 이 없다 — 넓은 표가 화면 틀을 밀어낸다'
    )
    # 표를 감싼 상자가 스크롤을 가져야 위 고침이 뜻을 갖는다
    자리2 = 글.index('.bl-table-wrap {')
    assert 'overflow' in 글[자리2:글.index('}', 자리2)]


def test_main_에_overflow_를_주지_않는다():
    """한 축에 overflow 를 주면 다른 축도 스크롤 상자가 된다.

    그러면 세로 스크롤이 통째로 .main 안으로 들어가고, 표 머리 고정(sticky)이
    창이 아니라 .main 을 기준으로 붙는다 — 고치려던 것보다 큰 변화다.
    가로 스크롤은 표를 감싼 상자(예: 주문관리 #tablewrap)가 맡는다.
    """
    규칙 = _규칙_본문(_읽기('toss.css'), '.main')
    assert 'overflow' not in 규칙, (
        '.main 에 overflow 가 붙었다 — 세로 스크롤과 표 머리 고정이 함께 바뀐다'
    )
