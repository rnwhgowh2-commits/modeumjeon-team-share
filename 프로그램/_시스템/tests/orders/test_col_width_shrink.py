# -*- coding: utf-8 -*-
"""주문 내역 표의 **열 폭 줄이기** — 끝까지 줄어들게 (2026-08-13 사장님 신고).

사장님: "칼럼(열)의 폭을 줄이고자하는데 끝까지 안줄여줘. 글자가 있어서 그런거야?
        글자가 있더라도 줄이게 해줘. 넘치는 부분은 ... 이렇게 표시해줘."

🔴🔴 원인 — `table-layout:fixed` 는 **표 폭이 확정된 숫자일 때만** 작동한다.
   이 표는 CSS 가 `width:max-content`(= 내용만큼) 라 브라우저가 자동 배분으로
   되돌렸고, 그러면 지정한 폭이 **「최소값」으로만** 쓰인다. 칸이 전부
   `white-space:nowrap` 이라 긴 상품명이 곧 폭의 바닥이 됐다 —
   **넓히는 건 되고 줄이는 건 안 됐다.**

   라이브 실측(2026-08-13, 사장님 계정 337주문):
     · 옛 방식: 상품명 열에 30px 를 줘도 **693px 그대로** (1px 도 안 줄었다)
     · 새 방식: 120px 요청 → 머리·몸통 **정확히 120px**, 표 폭 4888→4229

🔴 말줄임(`text-overflow:ellipsis`)은 **이미 코드에 있었는데 한 번도 작동한 적이
   없었다** — 폭이 줄어든 적이 없으니 넘칠 일도 없었다. 게다가 `td` 에만 걸려 있어
   머리글자는 옆 칸으로 흘러넘쳤다(신고의 눈에 보이는 절반).

★ 이 시험은 **코드 계약**만 본다. 진짜 증거는 렌더된 폭이라, 위 라이브 실측이
  그 자리를 대신한다. 그래서 여기서는 「글자가 있나」가 아니라 **「fixed 를 켜면서
  확정 폭도 같이 주나」**라는, 깨지면 증상이 그대로 돌아오는 지점을 못박는다.
"""
import pathlib
import re

TPL = (pathlib.Path(__file__).resolve().parents[2]
       / 'webapp' / 'templates' / 'orders' / 'index.html')
SRC = TPL.read_text(encoding='utf-8')


def _fn(name: str) -> str:
    """`function name(){ … }` 의 몸통을 중괄호 짝을 세어 잘라 온다."""
    m = re.search(r'function\s+%s\s*\(' % re.escape(name), SRC)
    assert m, f'{name}() 을 찾지 못했습니다'
    i = SRC.index('{', m.end() - 1)
    depth, j = 0, i
    while j < len(SRC):
        if SRC[j] == '{':
            depth += 1
        elif SRC[j] == '}':
            depth -= 1
            if depth == 0:
                return SRC[i:j + 1]
        j += 1
    raise AssertionError(f'{name}() 의 끝을 찾지 못했습니다')


APPLY = _fn('applyColW')


def test_fixed_를_켜면_표_폭도_확정_숫자로_준다():
    """🔴 이 시험이 이번 고침의 심장이다.

    `table-layout:fixed` 만 켜고 표 폭을 `max-content` 로 두면 브라우저가 자동
    배분으로 되돌린다 — 그 순간 지정한 폭은 최소값이 되고, 글자가 있는 열은
    영영 안 줄어든다. 둘은 **반드시 같이** 가야 한다.
    """
    assert "tableLayout='fixed'" in APPLY, 'fixed 배치를 켜지 않습니다'
    assert 't.style.width=' in APPLY, (
        '표에 확정 폭을 주지 않습니다 — fixed 만 켜면 브라우저가 자동 배분으로 '
        '되돌려 「글자 때문에 안 줄어드는」 옛 증상이 그대로 돌아옵니다.'
    )
    # 폭은 열 폭의 **합**이어야 한다(아무 숫자나 주면 열이 비례로 늘어난다)
    assert 'total' in APPLY, '열 폭의 합을 세지 않습니다'


def test_손_안_댄_열도_폭을_못박는다():
    """🔴 fixed 는 폭이 없는 열에 남은 공간을 **똑같이 나눠 준다.**
    한 열만 지정하면 나머지 32열이 제멋대로 넓어졌다 좁아진다."""
    assert 'colWAuto' in APPLY, '손 안 댄 열의 원래 폭을 굳히지 않습니다'
    assert 'getBoundingClientRect' in APPLY, '원래 폭을 실제로 재지 않습니다'


def test_원래_폭_기억은_표를_다시_그릴_때_버린다():
    """지난 판에서 잰 폭을 새 표에 물리면 열이 어긋난 채 굳는다."""
    assert re.search(r'colWAuto=null;\s*\n\s*applyColW\(\); bindColResize\(\);', SRC), (
        '표를 다시 그릴 때 colWAuto 를 비우지 않습니다'
    )


def test_머리글도_같이_잘린다():
    """🔴 몸통만 자르면 **머리글자가 옆 칸으로 흘러넘쳐** 줄여도 줄어 보이지 않는다."""
    m = re.search(r'\.o7 table\[style\*="fixed"\] td,\s*\n\s*'
                  r'\.o7 table\[style\*="fixed"\] th\{([^}]*)\}', SRC)
    assert m, '머리글(th)이 말줄임 규칙에 빠져 있습니다'
    rule = m.group(1)
    assert 'overflow:hidden' in rule and 'text-overflow:ellipsis' in rule


def test_잘라도_끌_손잡이는_남는다():
    """머리 칸에 `overflow:hidden` 을 주면 밖으로 삐져나온 손잡이가 잘려
    **한 번 줄이면 다시 못 늘린다.** 손잡이만 안쪽으로 붙인다."""
    assert '.o7 table[style*="fixed"] th .colgrip{right:0;}' in SRC


def test_끌기_바닥이_24px_다():
    """사장님: "끝까지 안줄여줘." 옛 바닥은 40px.
    0 까지 열면 손잡이를 못 잡아 되돌리지 못하므로 24px 로 둔다."""
    assert 'Math.max(24,Math.round(w0+(ev.clientX-x0)))' in SRC, (
        '끌기 최소 폭이 24px 가 아닙니다'
    )
    assert 'Math.max(40,Math.round(w0+' not in SRC, '옛 40px 바닥이 남아 있습니다'


def test_폭을_하나도_안_정했으면_손대지_않는다():
    """🔴 아무도 안 건드린 화면까지 fixed 로 바꾸면, 지금 잘 보이던 표가
    통째로 다시 배치된다. 정한 폭이 없으면 예전 그대로여야 한다."""
    assert "t.style.tableLayout=''; t.style.width='';" in APPLY, (
        '정한 폭이 없을 때 원래 배치로 되돌리지 않습니다'
    )
