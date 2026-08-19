# -*- coding: utf-8 -*-
"""[사장님 확정] 상품 상세 탭 **6개 → 4개** — 한눈에 / 사올 때 / 팔 때 / 판매·정산.

■ 확정본 (인수인계서 C2)
    한눈에 / 사올 때(소싱처+매트릭스+가격이력) / 팔 때(마켓·정책) / 판매·정산
    🔴 **표·그래프 하나도 안 뺀다** — 탭만 접는다.
    배치는 **S5** — 위에 소싱처·가격이력을 나란히, 아래에 옵션 매트릭스를 통째로.

■ 🔴 이 시험이 지키는 것
  1. 탭이 **정확히 4개**이고 이름이 확정본 그대로다.
  2. **판이 하나도 안 없어졌다** — 「사올 때」가 옛 t2·t3·t5 를 **셋 다** 그린다.
     탭을 줄이면서 판을 빠뜨리는 게 이 작업의 유일한 실패 방식이다.
  3. 옛 탭 이름이 화면에 **안 남았다**(「옵션 매트릭스 (최저가만)」 같은 탭 이름).
  4. 그리는 함수(`renderT2/T3/T5`)를 **안 고쳤다** — 고치면 화면과 값이 갈린다.
     넣을 자리만 바꿔 끼운다(`body()` 가 그때그때 다른 칸을 돌려준다).
"""
import io
import re

import pytest

TPL = 'webapp/templates/bundles/tower.html'


@pytest.fixture(scope='module')
def src():
    return io.open(TPL, encoding='utf-8').read()


@pytest.fixture(scope='module')
def tabs(src):
    m = re.search(r'var TABS = \[(.*?)\];', src, re.S)
    assert m, 'TABS 목록을 못 찾았습니다'
    return re.findall(r"\{id:'([^']+)', name:'([^']+)'\}", m.group(1))


# ── ① 탭이 4개, 이름은 확정본 그대로 ─────────────────────────

def test_탭이_정확히_네_개다(tabs):
    assert len(tabs) == 4, f'탭이 4개가 아닙니다: {[n for _i, n in tabs]}'


def test_탭_이름과_순서가_확정본_그대로다(tabs):
    assert [n for _i, n in tabs] == ['한눈에', '사올 때', '팔 때', '판매·정산']


def test_옛_탭_이름이_탭_목록에_안_남았다(tabs):
    옛이름 = ['판매 이력', '옵션 매트릭스 (최저가만)', '소싱처 수집 이력',
              '마켓 등록·정책', '가격/재고 변동 이력']
    남음 = [n for _i, n in tabs if n in 옛이름]
    assert not 남음, f'옛 탭 이름이 그대로 있습니다: {남음}'


# ── ② 🔴 판이 하나도 안 없어졌다 ─────────────────────────────

def test_사올_때가_옛_세_판을_다_그린다(src):
    """🔴 이 시험이 이 파일에서 제일 중요하다 — 탭을 줄이며 판을 빠뜨리는 게
    이 작업의 유일한 실패 방식이다. 셋 다 불려야 한다."""
    m = re.search(r'function showBuy\(\)\{(.*?)\n\}', src, re.S)
    assert m, '「사올 때」를 그리는 showBuy() 가 없습니다'
    body = m.group(1)
    for fn in ('renderT2', 'renderT3', 'renderT5'):
        assert fn in body, f'「사올 때」가 {fn} 을 안 부릅니다 — 판이 사라집니다'


def test_사올_때가_세_창구를_다_부른다(src):
    """매트릭스·소싱처·가격이력은 서로 다른 창구에서 온다 — 하나만 부르면 빈 판이 된다."""
    m = re.search(r'function showBuy\(\)\{(.*?)\n\}', src, re.S)
    body = m.group(1)
    for path in ("'matrix'", "'sources'", "'summary'"):
        assert path in body, f'「사올 때」가 {path} 를 안 부릅니다'


def test_여섯_그리기_함수가_다_살아_있다(src):
    """탭은 4개지만 **그리는 함수는 6개 그대로**다 — 지우면 그 표가 사라진다."""
    for n in range(1, 7):
        assert f'function renderT{n}(' in src, f'renderT{n} 이 사라졌습니다'


def test_팔_때와_판매정산이_옛_함수를_그대로_쓴다(src):
    """이름만 바뀐 탭 — 그리는 것은 t4·t6 그대로."""
    m = re.search(r'var render = \{([^}]*)\}', src)
    assert m, 'render 지도 를 못 찾았습니다'
    assert 't4:renderT4' in m.group(1).replace(' ', '')
    assert 't6:renderT6' in m.group(1).replace(' ', '')


# ── ③ S5 배치 — 위 두 칸, 아래 한 칸 ─────────────────────────

def test_S5_배치다_위는_두_칸_아래는_통째(src):
    """사장님 확정 S5. 소싱처·가격이력이 위에 나란히, 매트릭스가 아래 통째로."""
    m = re.search(r'function showBuy\(\)\{(.*?)\n\}', src, re.S)
    body = m.group(1)
    assert 'buy-two' in body, 'S5 의 「나란히 두 칸」 틀이 없습니다'
    assert 'buy-full' in body, 'S5 의 「아래 통째 한 칸」 틀이 없습니다'
    # 위 두 칸 = 소싱처·가격이력 / 아래 통째 = 매트릭스
    자리 = re.findall(r'data-buy="(t\d)"', body)
    assert 자리 == ['t3', 't5', 't2'], \
        f'S5 순서가 아닙니다(소싱처·가격이력 → 매트릭스): {자리}'


def test_배치_CSS가_있다(src):
    assert '.buy-two{' in src.replace(' ', '') or '.buy-two {' in src
    assert '.buy-full' in src


# ── ④ 🔴 그리는 함수는 안 고쳤다 ────────────────────────────

def test_그리는_함수를_안_고쳤다(src):
    """🔴 renderT2/T3/T5 를 고치면 화면과 값이 갈린다. **넣을 자리만** 바꿔 끼운다.

    그 장치가 `body()` 다 — 그때그때 다른 칸을 돌려주게만 한다.
    """
    assert 'function into(' in src, '자리를 바꿔 끼우는 into() 가 없습니다'
    m = re.search(r'function body\(\)\{(.*?)\}', src, re.S)
    assert m, 'body() 를 못 찾았습니다'
    assert 'slot' in m.group(1).lower(), \
        'body() 가 바뀐 자리를 안 봅니다 — 세 판이 같은 칸에 겹쳐 그려집니다'


def test_판이_겹쳐_그려지지_않게_자리를_되돌린다(src):
    """🔴 자리를 안 되돌리면 다음 탭이 엉뚱한 칸에 그려진다."""
    m = re.search(r'function into\((.*?)\n\}', src, re.S)
    assert m, 'into() 를 못 찾았습니다'
    assert 'finally' in m.group(1), \
        'into() 가 finally 로 자리를 안 되돌립니다 — 그리다 실패하면 자리가 남는다'


# ── ⑤ 화면 어디에도 옛 탭 이름이 안 남았다 ───────────────────

def test_안내글이_새_탭_이름으로_말한다(src):
    """「자세한 계산은 「마켓 등록·정책」 탭 →」 같은 안내가 옛 이름을 가리키면
    사장님이 없는 탭을 찾게 된다."""
    문제 = []
    for 옛 in ('「마켓 등록·정책」 탭', '「옵션 매트릭스 (최저가만)」 탭',
               '「소싱처 수집 이력」 탭', '「가격/재고 변동 이력」 탭',
               '「판매 이력」 탭'):
        if 옛 in src:
            문제.append(옛)
    assert not 문제, f'안내글이 없는 탭 이름을 가리킵니다: {문제}'
