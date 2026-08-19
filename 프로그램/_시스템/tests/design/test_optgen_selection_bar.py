# -*- coding: utf-8 -*-
"""옵션 생성(직접) 목록 — 「고른 것」 띠(①-A)와 전체 선택(③-A).

사장님 확정 2026-08-14. 정본 시안 = `_시안_임시/optgen_direct_부품_4항목.html`
의 ①-A · ③-A.

무엇을 지키나
  ① 띠는 표 **위**에 있고, 고른 것이 0개일 때도 **자리를 지킨다**(흐리게 + 단추 꺼짐).
     · 사라졌다 나타나면 표가 위아래로 튀어, 누르려던 줄이 손끝에서 도망간다.
     · 말은 「삭제」 하나뿐이다 — 같은 흐름이 화면마다 다른 이름으로 불리면 안 된다.
     · 삭제 단추는 **빨강 테두리 + 빨강 글자**다. 꽉 채운 빨강은 「이게 기본 동작」처럼
       보여, 되돌릴 수 없는 단추에 줄 옷이 아니다.
     · 🔴 확인창 문구는 **손대지 않는다.** 무엇을 몇 개 없애는지 이름까지 보여주는
       그 글이 진짜 방어선이다.
  ③ 「전체」는 **지금 화면에 보이는 줄**뿐이다. 숨은 줄까지 고르면 사장님이
     **안 보이는 것을 지우게 된다** — 되돌릴 수 없어 한 번의 어긋남이 곧 사고다.

🔴 왜 글자를 세나 — 이 화면의 고르기·삭제는 브라우저에서만 도는 코드라, 서버 시험이
   닿지 않는다. 그래서 「어떤 모양이어야 하는지」를 여기서 못 박는다. 실제로 눌러 본
   확인은 브라우저로 따로 한다(둘 다 있어야 한다).
"""
import io
import os
import re

_여기 = os.path.dirname(os.path.abspath(__file__))
_목록 = os.path.join(_여기, '..', '..', 'webapp', 'templates', 'optgen', 'index.html')
_조립대 = os.path.join(_여기, '..', '..', 'webapp', 'templates', 'matrix', 'detail.html')


def _읽기(경로):
    with io.open(경로, encoding='utf-8') as f:
        return f.read()


def _규칙(css, 선택자):
    """`선택자{` 부터 다음 `}` 까지 — 그 규칙 본문만."""
    m = re.search(re.escape(선택자) + r'\s*\{([^}]*)\}', css)
    assert m, f'{선택자} 규칙을 못 찾았다'
    return m.group(1).replace(' ', '').replace('\n', '')


def _함수(js, 이름):
    """`function 이름(` 부터 중괄호가 닫힐 때까지 — 그 함수 본문만."""
    i = js.find('function %s(' % 이름)
    assert i >= 0, f'{이름} 함수를 못 찾았다'
    깊이, j = 0, js.index('{', i)
    for k in range(j, len(js)):
        if js[k] == '{':
            깊이 += 1
        elif js[k] == '}':
            깊이 -= 1
            if 깊이 == 0:
                return js[j:k + 1]
    raise AssertionError(f'{이름} 함수의 끝을 못 찾았다')


# ── ① 삭제 단추 자리 ────────────────────────────────────────────────────────
def test_띠는_표_위에_있다():
    """예전엔 표 **아래**에 있었다 — 눈이 표를 다 지나야 단추를 만났다."""
    html = _읽기(_목록)
    띠 = html.find('id="og-delbar"')
    표 = html.find('<table class="og-tb og-c3 og-tb4"')
    상자 = html.find('<div class="og-tbwrap">')
    assert 띠 >= 0 and 표 >= 0 and 상자 >= 0, '띠·표·상자 중 하나를 못 찾았다'
    assert 상자 < 띠 < 표, (
        '띠가 표 바로 윗줄에 없다 — 아래에 두면 눈이 표를 다 지나야 단추를 만난다')


def test_고른_것이_0개여도_줄은_그대로_있다():
    """🔴 `hidden` 으로 감추면 띠가 나타났다 사라지며 표가 위아래로 튄다."""
    html = _읽기(_목록)
    띠 = html[html.find('id="og-delbar"'):]
    띠 = 띠[:띠.find('</div>')]
    assert 'hidden' not in 띠, f'띠 마크업에 hidden 이 있다 — 0개일 때 사라진다: {띠!r}'
    # 감추는 대신 흐리게 — 그 옷(.off)이 실제로 있어야 한다.
    assert '.og-selbar.off' in html, '0개일 때 흐리게 할 규칙(.og-selbar.off)이 없다'
    assert 'class="og-selbar off"' in html, (
        '처음 그려질 때부터 흐린 상태가 아니다 — 0개인데 파랗게 떠 있다')
    assert "og띠.classList.toggle('off'" in html, (
        '띠를 흐리게 하는 코드가 없다 — 0개 상태가 화면에 안 보인다')
    assert 'delbar.hidden' not in html and 'og띠.hidden' not in html, (
        '띠를 여전히 감추고 있다 — 표가 위아래로 튄다')


def test_0개면_단추가_꺼져_있다():
    """자리는 지키되 **누를 수는 없어야** 한다 — 아니면 빈 확인창이 뜬다."""
    html = _읽기(_목록)
    for 단추 in ('id="og-delgo"', 'id="og-delclr"'):
        i = html.find(단추)
        assert i >= 0, f'{단추} 를 못 찾았다'
        태그 = html[html.rfind('<', 0, i):html.find('>', i) + 1]
        assert 'disabled' in 태그, (
            f'{단추} 가 처음부터 켜져 있다 — 0개인데 눌린다: {태그!r}')
    assert "document.getElementById('og-delgo').disabled = 없음" in html, (
        '고른 수에 따라 삭제 단추를 켜고 끄는 코드가 없다')
    assert "document.getElementById('og-delclr').disabled = 없음" in html, (
        '고른 수에 따라 선택 해제 단추를 켜고 끄는 코드가 없다')


def test_단추_이름은_삭제다():
    html = _읽기(_목록)
    assert '<button class="og-del-go" type="button" id="og-delgo" disabled>삭제</button>' in html
    assert '>선택 해제</button>' in html, '「선택 해제」 단추가 없다'


def test_삭제_단추는_테두리만_빨갛다():
    """🔴 꽉 채운 빨강은 「이게 기본 동작」처럼 보여 손이 먼저 간다."""
    본문 = _규칙(_읽기(_목록), '.og-del-go')
    assert 'border:1pxsolidvar(--color-danger' in 본문, (
        f'빨강 테두리가 없다: {본문!r}')
    assert 'color:var(--글자-빨강' in 본문, (
        f'빨강 글자가 아니다 — --color-danger 는 배경용이라 흰 바탕에서 대비가 모자란다: {본문!r}')
    assert 'background:var(--color-danger' not in 본문, (
        f'꽉 채운 빨강이다 — 되돌릴 수 없는 단추에 줄 옷이 아니다: {본문!r}')


def test_확인창_문구는_그대로다():
    """🔴 단추 이름을 바꿨다고 같이 손대면 진짜 방어선이 흐려진다."""
    html = _읽기(_목록)
    for 글 in ("'묶음 ' + 고른함.size + '개를 지웁니다.'",
               "'안에 있는 옵션 ' + 옵션합 + '개와 그 재고 기록도 같이 사라지고,'",
               "'되돌릴 수 없습니다.'",
               "줄.push('', '지울까요?')"):
        assert 글 in html, f'확인창 문구가 바뀌었다 — 그대로 두기로 했다: {글}'
    assert "'「' + nm + '」 (' + code + ') 를 지웁니다.\\n'" in html, (
        '한 줄 삭제 확인창의 문구가 바뀌었다 — 이름까지 보여주는 그게 방어선이다')


def test_한_흐름은_한_이름으로만_불린다():
    """🔴 목록과 조립대는 **같은 코드**를 쓴다(조립대 주석에 그렇게 적혀 있다).

    한쪽만 「지우기」로 남으면 사장님이 같은 일을 두 이름으로 배우게 된다.
    주석도 본다 — 다음 사람이 옛 이름을 보고 그대로 되살리는 것을 막는다.
    """
    for 경로 in (_목록, _조립대):
        html = _읽기(경로)
        assert '지우기' not in html, (
            f'{os.path.basename(경로)} 에 「지우기」가 남아 있다 — 이 흐름의 이름은 「삭제」다')
    assert '>🗑 이 묶음 삭제</button>' in _읽기(_조립대)
    assert '>삭제</button>' in _읽기(_목록)


def test_상품_생성_탭이_같이_쓰는_옷은_안_지운다():
    """🔴 옵션 생성 탭 띠를 위로 옮겼다고 공용 규칙을 지우면
    상품 생성 탭의 「고른 묶음으로 상품 만들기」 띠가 통째로 맨몸이 된다."""
    html = _읽기(_목록)
    for 선택자 in ('.og-pickbar{', '.og-pickbar-n{', '.og-pickbar-s{', '.og-pclr{'):
        assert 선택자 in html, f'{선택자} 가 사라졌다 — 상품 생성 탭이 같이 쓴다'
    assert 'id="og-pickbar"' in html, '상품 생성 탭 띠 자체가 사라졌다'


# ── ③ 전체 선택 ─────────────────────────────────────────────────────────────
def test_머리줄에_전체_체크가_있다():
    html = _읽기(_목록)
    머리 = html[html.find('<thead>'):html.find('</thead>')]
    assert 'id="og-ckall"' in 머리, '머리줄 첫 칸에 전체 체크가 없다'
    assert '<th class="og-pick"><label><input type="checkbox" id="og-ckall"' in 머리, (
        '전체 체크가 머리줄 **첫 칸**이 아니거나 라벨로 안 감쌌다')


def test_전체는_보이는_줄만이다():
    """🔴 숨긴 줄까지 고르면 **안 보이는 것을 지우게 된다.**"""
    html = _읽기(_목록)
    본문 = _함수(html, 'og보이는체크')
    assert "display !== 'none'" in 본문, (
        f'보이는 줄을 가리는 조건이 없다 — 숨은 줄까지 골라진다: {본문!r}')
    쓰는곳 = html[html.find('og전체체크.addEventListener'):]
    쓰는곳 = 쓰는곳[:쓰는곳.find('});')]
    assert 'og보이는체크()' in 쓰는곳, (
        f'전체 체크가 보이는 줄만 고르지 않는다: {쓰는곳!r}')


def test_일부만_골랐으면_중간_상태다():
    """재고관리(`inventory/home.html` 의 `_hmRefreshBulkBar`)가 쓰는 그 방식."""
    본문 = _함수(_읽기(_목록), 'og고름갱신')
    assert 'indeterminate' in 본문, (
        f'중간 상태가 없다 — 일부만 골랐는데 「전부 골랐다」로 보인다: {본문!r}')
    assert '골랐다 === 보임.length' in 본문, (
        '「전부」 판정이 보이는 줄 수 기준이 아니다')


def test_상태를_세는_함수는_하나뿐이다():
    """🔴 입구가 다섯인데 각자 세면 확인창 개수와 화면이 갈린다."""
    html = _읽기(_목록)
    assert html.count('function og고름갱신(') == 1, '갱신 함수가 두 벌이다'
    assert 'function drawDel(' not in html, (
        '옛 갱신 함수(drawDel)가 남아 있다 — 두 곳이 각자 센다')
    # 고름을 바꾸는 입구는 전부 이 함수만 부른다.
    assert html.count('og고름갱신()') >= 5, (
        '갱신 함수를 부르는 곳이 너무 적다 — 어느 입구가 갱신을 빠뜨리고 있다')


def test_거르기가_끝나면_다시_센다():
    """🔴 브랜드를 바꾼 순간 「전체 선택됨」인데 실제로는 숨은 줄이 골라져 있으면,
    삭제 확인창의 개수와 화면이 어긋난다."""
    본문 = _함수(_읽기(_목록), 'apply')
    assert 'og숨은줄_체크풀기()' in 본문, (
        f'거르기 뒤 숨은 줄의 체크를 안 푼다: {본문!r}')
    assert 'og고름갱신()' in 본문, '거르기 뒤 다시 안 센다'
    assert 본문.index('og숨은줄_체크풀기()') < 본문.index('og고름갱신()'), (
        '체크를 풀기 **전에** 세고 있다 — 방금 숨긴 줄이 개수에 남는다')


def test_숨은_줄의_체크는_풀린다():
    본문 = _함수(_읽기(_목록), 'og숨은줄_체크풀기')
    assert "display === 'none'" in 본문 and 'ck.checked = false' in 본문, (
        f'숨은 줄의 체크를 실제로 풀지 않는다: {본문!r}')
    assert 'og체크담기(ck)' in 본문, (
        '체크만 풀고 고른 목록에서는 안 뺀다 — 화면과 개수가 갈린다')
