# -*- coding: utf-8 -*-
"""「···」 메뉴가 목록 상자 안에 갇혀 잘리지 않는지.

사장님 지적(2026-08-13): 「상품 목록 창이 너무 작아서 점세개 누르면 스크롤 생기고 있어」

## 원인 — 선언한 적 없는 세로 클리핑

`.og-tbwrap` 에는 `overflow-x:auto` **하나만** 걸려 있었다. 그런데 CSS 규격상
**한 축이 `visible` 이 아니면 다른 축의 `visible` 은 자동으로 `auto` 가 된다.**
그래서 세로도 스크롤 상자가 되어, `position:absolute` 로 뜨던 메뉴가 잘렸다.
`z-index:20` 은 소용없다 — 잘림은 쌓임 순서가 아니라 **스크롤포트 클리핑**이라
z-index 로 못 뚫는다.

라이브 실측(2026-08-13, https://mou-m.com/optgen?tab=product):

| 상태 | 상자 높이 | 열면 scrollHeight | 잘린 양 | 보이는 메뉴 |
|---|---|---|---|---|
| 필터 없음(80줄) | 3441 | 3441 → 3504 | 47.6px | — |
| 「상품 만듦」(2줄) | 165 | 165 → 205 | 40px | 37px |
| 「정책 적용」(1줄) | **78** | 78 → 141 | **63px** | **14px** |

🔴 범인이 **둘**이다 — 폰(`max-width:768px`)에는 `.og-tb{display:block;overflow-x:auto}`
   가 따로 있어 표 자체가 두 번째 클리핑 상자가 된다(375×812 실측: 메뉴 98px 중 56px 잘림).
   그래서 조상을 하나씩 손보는 처방으로는 부족하다 — **조상 밖(body)으로 꺼낸다.**

🔴 「카드가 짧다」는 `max-height` 탓이 **아니다.** 저장소 어디에도 `.og-tbwrap` 높이
   규칙이 없다(라이브 계산값 `max-height:none`). 필터를 켜면 줄이 `display:none` 이
   되고 `.og-wrap{align-items:start}` 라 카드가 내용만큼 쪼그라드는 것이다.
   그래서 높이를 고정하는 처방(`max-height:calc(...)`)은 **증상을 상시화**한다.
"""
import io
import os
import re

_템플릿 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     '..', '..', 'webapp', 'templates', 'optgen', 'index.html')


def _읽기():
    with io.open(_템플릿, encoding='utf-8') as f:
        return f.read()


def _규칙(css, 선택자):
    """`선택자{` 부터 다음 `}` 까지."""
    m = re.search(re.escape(선택자) + r'\s*\{([^}]*)\}', css)
    assert m, f'{선택자} 규칙을 못 찾았다'
    return m.group(1)


def _코드만(html):
    """주석을 걷어낸 본문.

    🔴 이게 없으면 시험이 **자기 설명에 걸린다.** 실제로 걸렸다 —
       「이 코드를 쓰면 안 된다」고 주석에 적어 뒀더니, 글자를 세는 검사가
       그 주석을 코드로 보고 실패시켰다. 글자만 세는 검사는 주석·코드를 못 가른다.
    """
    줄 = [l for l in html.splitlines() if not l.lstrip().startswith(('//', '/*', '*', '{#'))]
    return '\n'.join(줄)


def test_메뉴는_창_기준으로_뜬다():
    """`absolute` 면 조상 스크롤 상자에 갇힌다 — `fixed` 여야 조상을 벗어난다."""
    본문 = _규칙(_읽기(), '.og-menu')
    assert 'position:fixed' in 본문.replace(' ', ''), (
        f'.og-menu 가 창 기준이 아니다 — 목록 상자에 갇혀 잘린다: {본문!r}')


def test_메뉴를_body_로_옮긴다():
    """CSS 만 fixed 로 바꾸면 부족하다 — 조상에 transform·filter 가 생기면
    다시 그 조상 기준이 된다. body 로 옮겨야 확실하다(저장소 표준)."""
    html = _읽기()
    assert 'document.body.appendChild(menu)' in html, (
        '메뉴를 body 로 옮기지 않는다 — 조상 밖으로 꺼내야 안 잘린다')


def test_버튼이_메뉴_참조를_붙들고_있다():
    """🔴 body 로 옮기면 `btn.parentElement.querySelector('.og-menu')` 는 null 이다.
    그대로 두면 「···」가 **에러도 없이 아무 일도 안 한다** — 가장 조용한 실패."""
    코드 = _코드만(_읽기())
    assert "btn.parentElement.querySelector('.og-menu')" not in 코드, (
        '메뉴를 부모에서 다시 찾고 있다 — body 로 옮긴 뒤엔 null 이라 단추가 죽는다')
    # 붙들어 둔 참조를 실제로 쓰는지 — 「안 쓴다」만 확인하면 아무것도 안 쓸 수도 있다.
    assert 'var menu = cell && cell.querySelector' in 코드, (
        '여는 시점에 메뉴를 붙들어 두지 않는다')


def test_화면_아래에서는_위로_뒤집는다():
    """맨 아랫줄에서 열면 아래로는 자리가 없다 — 위로 뒤집어야 다 보인다."""
    html = _읽기()
    assert 'window.innerHeight' in html and 'r.top - ch' in html, (
        '위로 뒤집기가 없다 — 맨 아랫줄 메뉴가 화면 밖으로 나간다')


def test_창_오른쪽_밖으로_안_나간다():
    """🔴 라이브 실측이 잡은 것 — 메뉴가 **창 밖 103px** 로 날아갔다.

    이 표는 가로로 넘친다(실측 clientWidth 704 / scrollWidth 859). 그래서
    「···」 단추가 상자 오른쪽 **밖**에 있을 수 있고, 그 좌표를 그대로 쓰면
    메뉴가 화면을 벗어난다. 정본 `_pmShowFloat` 는 왼쪽만 붙잡는다 — 한 줄이 더 필요.
    """
    코드 = _코드만(_읽기())
    assert 'window.innerWidth' in 코드, (
        '오른쪽 가장자리를 안 붙잡는다 — 가로로 넘친 줄에서 메뉴가 창 밖으로 나간다')


def test_스크롤하면_닫는다():
    """🔴 fixed 는 페이지를 안 따라간다 — 안 닫으면 엉뚱한 자리에 남는다.

    캡처(`true`)여야 한다. **목록 상자 안쪽 스크롤은 window 로 안 올라온다.**
    (같은 처방이 `orders/index.html` 의 `.dcpop` 에도 있다)
    """
    html = _읽기()
    assert "addEventListener('scroll', ogCloseMenus, true)" in html, (
        '안쪽 스크롤을 캡처로 안 잡는다 — 메뉴가 엉뚱한 자리에 남는다')


def test_떠_있는_메뉴에는_그림자가_있다():
    """표 밖에 떠 있으면 테두리만으로는 바탕에 묻힌다."""
    본문 = _규칙(_읽기(), '.og-menu')
    assert 'box-shadow' in 본문, '떠 있는 메뉴에 그림자가 없다 — 바탕에 묻힌다'


def test_목록_상자에_높이를_고정하지_않는다():
    """🔴 반대 방향 처방 금지.

    「카드가 짧다」의 원인은 CSS 상한이 아니라 필터로 줄이 줄어드는 것이다.
    여기에 `max-height` 를 주면 **필터를 풀어도 늘 짧은 스크롤 상자**가 된다 —
    사장님 불만과 정반대다.
    """
    본문 = _규칙(_읽기(), '.og-tbwrap')
    assert 'max-height' not in 본문 and 'height:' not in 본문.replace(' ', ''), (
        f'.og-tbwrap 에 높이를 고정했다 — 짧은 카드가 상시화된다: {본문!r}')


def test_가로_스크롤은_그대로_둔다():
    """PC 에서 실측 27px 넘친다(clientWidth 960 / scrollWidth 987) —
    `overflow-x` 를 없애면 그만큼 영영 못 본다."""
    본문 = _규칙(_읽기(), '.og-tbwrap')
    assert 'overflow-x:auto' in 본문.replace(' ', ''), (
        '가로 스크롤이 사라졌다 — 넘치는 27px 을 못 보게 된다')


def test_두_탭_모두_같은_메뉴를_쓴다():
    """🔴 `tab=product` 와 `tab=direct·market` 은 **다른 마크업**이다
    (Jinja `{% if %}`/`{% else %}` 로 갈리고 메뉴 항목 수도 2개 vs 1개).
    처방이 클래스 기반이라 둘 다 덮는지 확인한다 — 한쪽만 고치면 나머지가 남는다.
    """
    html = _읽기()
    assert html.count('class="og-menu"') >= 2, (
        '메뉴 마크업이 한 벌뿐이다 — 탭이 갈리는 구조가 바뀌었는지 확인 필요')
    # 처방은 클래스로 걸므로 두 벌 모두 같은 클래스여야 한다.
    assert html.count("querySelectorAll('.og-more')") == 1, (
        '메뉴 여는 코드가 두 벌이다 — 한쪽만 고쳐질 수 있다')
