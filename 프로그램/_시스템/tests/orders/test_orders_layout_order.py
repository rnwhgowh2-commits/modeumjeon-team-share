# -*- coding: utf-8 -*-
"""주문 내역 화면의 **세로 순서** 고정 (2026-08-12 사장님 확정).

    ① 주문 불러오는 중 → ② 마켓·계정별 불러오기 현황 → ③ 주문현황 카드
    → ④ 가로탭(마켓 상태·주문 관리·돈 확인) → ⑤ 주문내역 표

🔴 왜 시험으로 잠그나 — 이 순서는 **화면 코드의 줄 순서**가 곧 결과라서, 나중에 누가
   한 블록만 옮겨도 조용히 되돌아간다. 옛 순서(탭 → 매입 엑셀 카드 → 숫자 카드 → 마켓줄)
   에서는 화면에 들어오자마자 오늘 몇 건·얼마인지를 알 수 없었다.

🔴 더망고 매입 엑셀 — 사장님: "드래그 앤 드랍으로 올리도록 딱 느꼈으면 좋겠어."
   표 전체가 드롭존이고, 올리는 길은 **한 벌**이어야 한다(두 벌이면 한쪽만 고쳐진다).
"""
import pathlib
import re

TPL = (pathlib.Path(__file__).resolve().parents[2]
       / 'webapp' / 'templates' / 'orders' / 'index.html')
SRC = TPL.read_text(encoding='utf-8')


def _resolve(tab: str) -> str:
    """Jinja 의 `{% if tab == 'ship' %}` / `{% else %}` 를 그 탭 기준으로 푼다."""
    out, i = [], 0
    pat = re.compile(r"\{%\s*if tab (==|!=) 'ship'\s*%\}")
    while True:
        m = pat.search(SRC, i)
        if not m:
            out.append(SRC[i:])
            break
        out.append(SRC[i:m.start()])
        end = SRC.index('{% endif %}', m.end())
        body = SRC[m.end():end]
        els = body.find('{% else %}')
        yes, no = (body[:els], body[els + len('{% else %}'):]) if els >= 0 else (body, '')
        want_ship = (m.group(1) == '==')
        take = yes if ((tab == 'ship') == want_ship) else no
        out.append(take)
        i = end + len('{% endif %}')
    return ''.join(out)


def _order(html: str, ids):
    """주어진 id 들이 화면에 나타나는 순서대로 돌려준다(없는 것은 뺀다)."""
    pos = []
    for x in ids:
        m = re.search(r'id="%s"' % re.escape(x), html)
        if m:
            pos.append((m.start(), x))
    return [x for _, x in sorted(pos)]


LIST = _resolve('list')
SHIP = _resolve('ship')

#: 화면 순서 — 이 배열이 사장님 확정 순서 그 자체다.
EXPECTED = ['loadbar', 'mkline', 'acctline', 'acovbar', 'warnbar',
            'kpis', 'ffTabs', 'ostTabs', 'mgTabs', 'ppCard', 'droprel']


def test_주문내역_세로_순서가_확정대로다():
    got = _order(LIST, EXPECTED)
    assert got == EXPECTED, f'화면 순서가 바뀌었습니다\n기대: {EXPECTED}\n실제: {got}'


def test_불러오는중이_맨_위다():
    """①번 — 지금 무엇을 하는 중인지가 가장 먼저 보여야 한다."""
    got = _order(LIST, EXPECTED)
    assert got[0] == 'loadbar'


def test_숫자카드가_거르기_탭보다_위다():
    """③이 ④보다 위 — 「무엇으로 거를지」보다 「오늘 상황」이 먼저다."""
    got = _order(LIST, EXPECTED)
    assert got.index('kpis') < got.index('ffTabs')
    assert got.index('kpis') < got.index('ostTabs')


def test_마켓_계정_현황이_숫자카드보다_위다():
    """②가 ③보다 위 — 어느 마켓이 얼마나 들어왔는지를 먼저 본다."""
    got = _order(LIST, EXPECTED)
    for x in ('mkline', 'acctline', 'acovbar', 'warnbar'):
        assert got.index(x) < got.index('kpis'), x


def test_매입_엑셀_카드는_표_바로_위다():
    """⑤ 표 바로 위 — 채울 일이 있는 자리에 도구를 둔다."""
    got = _order(LIST, EXPECTED)
    assert got.index('ppCard') == got.index('droprel') - 1


# ── 드래그 앤 드랍 ────────────────────────────────────────────────────────────

def test_주문내역_표_전체가_매입엑셀_드롭존이다():
    """사장님 요청 — 평소엔 아무것도 없다가 끌어오면 표가 놓을 자리로 바뀐다."""
    assert 'id="dropov-pp"' in LIST, '주문 내역에 매입 엑셀 안내막이 없습니다'
    assert '더망고 매입 엑셀을 여기에 놓으세요' in LIST
    # 안내막은 표를 덮는 자리(#droprel) **안**에 있어야 한다
    i_rel = LIST.index('id="droprel"')
    i_ov = LIST.index('id="dropov-pp"')
    i_end = LIST.index('id="pdxLegend"')
    assert i_rel < i_ov < i_end


def test_송장작업_드롭존은_그대로다():
    """새 장치가 기존 송장 엑셀 드롭을 밀어내면 안 된다."""
    assert 'id="dropov"' in SHIP and '운송장번호' in SHIP
    assert 'id="dropov-pp"' not in SHIP, '송장 작업엔 매입 엑셀 안내막이 뜨면 안 됩니다'


def test_두_탭이_같은_드롭_장치를_쓴다():
    """올리는 길이 두 벌이면 한쪽만 고쳐져 조용히 어긋난다."""
    assert SRC.count("rel.addEventListener('drop'") == 1, '표 드롭 배선이 두 벌입니다'
    assert "getElementById(SHIP?'dropov':'dropov-pp')" in SRC


def test_매입엑셀_업로드_경로가_한_벌이다():
    """드롭존과 「파일 고르기」가 같은 upload() 를 쓴다."""
    assert 'ppUploadFile=upload;' in SRC, 'upload() 를 드롭존이 못 부릅니다'
    assert 'if(ppUploadFile)ppUploadFile(f);' in SRC
