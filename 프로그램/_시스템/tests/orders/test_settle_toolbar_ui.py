# -*- coding: utf-8 -*-
"""정산예정금액 탭 **줄단추 4개** — 자리·색·「누르면 뭐가 바뀌나」 (사장님 지적 2026-08-13).

> *"로켓그로스, 계산규칙, 11번가 미확정 가져오기, 롯데온 입금내역 가져오기 왜렇게 칸이
>  띄어져 있는지? 굳이 색상을 많이 넣어서 디자인 헷갈리게 하지말기. 앞에 이모티콘이나
>  파란,노란버튼 뺴기"*
> *"호버로 누르면 어떤게 반영되는지? (과정은 어떻게 되는지?)"*

🔴 벌어진 이유 — `.bar-row` 가 `justify-content:space-between` 인데 동작 단추들이
   **낱개로** 그 줄의 자식이었다. space-between 은 자식 수만큼 틈을 벌리므로,
   단추를 하나 더할 때마다 화면이 더 넓게 흩어진다. 묶어야 멈춘다.

🔴 호버는 `hover-info-card` 규칙을 따른다. 카드 안에 **누를 것이 없으므로** 규칙 1~6 중
   1·2·5·6 을 쓴다(카드 안에서 머물 이유가 없어도 3·4 는 넣는다 — 긴 글을 읽는 중에
   마우스가 카드에 얹히면 꺼진다).
"""
import pathlib
import re

import pytest

TPL = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "templates"
       / "orders" / "index.html")
BTNS = ["spn-rules-btn", "spn-rg-btn", "spn-el-btn", "spn-lo-btn"]


@pytest.fixture(scope="module")
def tpl():
    return TPL.read_text(encoding="utf-8")


def _tag(tpl: str, bid: str) -> str:
    """그 단추의 여는 태그부터 닫는 태그까지."""
    i = tpl.index('id="%s"' % bid)
    s = tpl.rindex("<button", 0, i)
    return tpl[s:tpl.index("</button>", s)]


# ── ① 색·이모티콘 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bid", BTNS)
def test_단추_이름에_이모티콘이_없다(tpl, bid):
    """🔵🟡🚀⚙️ 는 뜻이 없는 장식이었다 — 색이 많으면 무엇이 중요한지 안 보인다."""
    label = _tag(tpl, bid).split(">", 1)[1]
    bad = re.findall(r"[\U0001F300-\U0001FAFF☀-➿️]", label)
    assert not bad, "「%s」 이름에 장식이 남았다: %r" % (bid, bad)


def test_본문_안내글도_옛_이름을_안_부른다(tpl):
    """화면 설명이 「⚙️ 계산 규칙」이라 적으면 단추와 이름이 달라 못 찾는다."""
    assert "「⚙️ 계산 규칙」" not in tpl
    assert "「계산 규칙」" in tpl


# ── ② 자리 ───────────────────────────────────────────────────────────────────

def test_동작_단추가_한_묶음이다(tpl):
    """🔴 낱개로 두면 `space-between` 이 화면 폭만큼 벌린다 — 그게 사장님이 본 그 틈이다."""
    i = tpl.index('<div class="bar-row">')
    row = tpl[i:tpl.index('<div class="kpis"', i)]
    grp = row.index('class="acts"')
    for bid in BTNS:
        assert row.index('id="%s"' % bid) > grp, "「%s」 가 묶음 밖에 있다" % bid


def test_묶음이_오른쪽에_붙는다(tpl):
    """왼쪽 기간 토글과 오른쪽 동작 단추 — 틈은 **그 사이 하나**뿐이어야 한다."""
    i = tpl.index(".spn .acts{")
    css = tpl[i:tpl.index("}", i)]
    assert "margin-left:auto" in css
    assert "gap" in css


# ── ③ 「누르면 뭐가 바뀌나」 ──────────────────────────────────────────────────

@pytest.mark.parametrize("bid", BTNS)
def test_단추마다_과정_설명이_붙어_있다(tpl, bid):
    """마우스만 올리면 **어디서 · 어떻게 · 무엇이 바뀌는지**를 읽을 수 있어야 한다."""
    tag = _tag(tpl, bid)
    assert 'data-how="' in tag, "「%s」 에 설명이 없다" % bid
    key = re.search(r'data-how="([a-z0-9]+)"', tag).group(1)
    blk = tpl[tpl.index("var _HOW={"):tpl.index("</script>", tpl.index("var _HOW={"))]
    m = re.search(r"%s\s*:\s*\{(.{0,1400}?)\n\s*\}," % key, blk, re.S)
    assert m, "_HOW 에 「%s」 설명이 없다" % key
    body = m.group(1)
    assert "단계" in body or "step" in body, "과정이 단계로 안 적혀 있다"
    assert "바뀌" in body or "반영" in body, "무엇이 바뀌는지 안 적혀 있다"


def test_옛_title_툴팁을_안_남긴다(tpl):
    """`title` 과 호버 창이 같이 뜨면 두 겹으로 겹쳐 읽기 어렵다."""
    for bid in ("spn-rg-btn", "spn-el-btn", "spn-lo-btn"):
        assert "title=" not in _tag(tpl, bid), "「%s」 에 옛 title 이 남았다" % bid


# ── ④ 호버 창이 규칙을 지키나 ────────────────────────────────────────────────

def test_호버창은_body에_fixed로_붙는다(tpl):
    """규칙 1 — 줄·카드의 overflow 에 잘리지 않게."""
    assert "document.body.appendChild" in tpl[tpl.index("_howPop"):tpl.index("_howPop") + 400]
    i = tpl.index(".howpop{")
    assert "position:fixed" in tpl[i:tpl.index("}", i)]


def test_지연_숫자가_표준값이다(tpl):
    """규칙 2·6 — 닫기 250ms / 열기 140ms. 단추 4개가 붙어 있어 열기 지연이 꼭 필요하다."""
    i = tpl.index("var _HOW_CLOSE")
    blk = tpl[i:i + 200]
    assert "250" in blk and "140" in blk


def test_창에_들어가면_안_닫히고_나가면_다시_예약한다(tpl):
    """규칙 3·4 — 긴 글을 읽는 중 마우스가 카드에 얹히면 꺼지면 안 된다."""
    i = tpl.index("_howPop.addEventListener('mouseenter'")
    blk = tpl[i:i + 300]
    assert "clearTimeout" in blk
    assert "_howPop.addEventListener('mouseleave'" in tpl


def test_아래가_모자라면_위로_뒤집는다(tpl):
    """규칙 5 — 화면 끝에서 잘리면 정작 결론을 못 읽는다."""
    i = tpl.index("function _howShow")
    blk = tpl[i:i + 900]
    assert "innerHeight" in blk and "getBoundingClientRect" in blk


def test_스크롤하면_닫는다(tpl):
    """fixed 좌표가 낡아 엉뚱한 자리에 남는다."""
    blk = tpl[tpl.index("function _howShow"):tpl.index("function _howShow") + 2200]
    assert "scroll" in blk
