# -*- coding: utf-8 -*-
"""주문 내역 화면의 **세로 순서** 고정 (2026-08-13 사장님 확정 — 올려주신 이미지 4장).

    ① 주문 불러오는 중 → ② 주문현황 카드 → ③ 계정 경고
    → ④ 가로탭(마켓 상태·주문 관리·돈 확인) → ⑤ 마켓 칩·계정 칩 → ⑥ 주문내역 표

🔴 왜 시험으로 잠그나 — 이 순서는 **화면 코드의 줄 순서**가 곧 결과라서, 나중에 누가
   한 블록만 옮겨도 조용히 되돌아간다. 옛 순서(탭 → 매입 엑셀 카드 → 숫자 카드 → 마켓줄)
   에서는 화면에 들어오자마자 오늘 몇 건·얼마인지를 알 수 없었다.
🔴 2026-08-12 순서는 「마켓 칩 → 경고 → 카드 → 가로탭」이었다. 카드가 마켓 칩 아래라
   화면 맨 위가 「거르는 장치」로 채워져 있었다 → 카드를 맨 위로, 거르는 장치는 아래로.

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
EXPECTED = ['loadbar', 'kpis', 'acovbar', 'warnbar',
            'ffTabs', 'ostTabs', 'mgTabs', 'mkline', 'acctline',
            'ppCard', 'droprel']


def test_주문내역_세로_순서가_확정대로다():
    got = _order(LIST, EXPECTED)
    assert got == EXPECTED, f'화면 순서가 바뀌었습니다\n기대: {EXPECTED}\n실제: {got}'


def test_불러오는중이_맨_위다():
    """①번 — 지금 무엇을 하는 중인지가 가장 먼저 보여야 한다."""
    got = _order(LIST, EXPECTED)
    assert got[0] == 'loadbar'


def test_숫자카드가_거르는_장치보다_모두_위다():
    """②가 ④·⑤보다 위 — 「무엇으로 거를지」보다 「오늘 상황」이 먼저다.
    🔴 마켓 칩(mkline)도 거르는 장치다. 2026-08-12 순서에선 이것만 카드 위에 있어
       화면 맨 윗줄이 필터로 채워져 있었다."""
    got = _order(LIST, EXPECTED)
    for x in ('ffTabs', 'ostTabs', 'mgTabs', 'mkline', 'acctline'):
        assert got.index('kpis') < got.index(x), x


def test_계정_경고가_숫자카드_바로_아래다():
    """③ — 못 불러온 계정이 있으면 카드 숫자가 실제보다 적다. 숫자 바로 밑에서 말한다."""
    got = _order(LIST, EXPECTED)
    assert got.index('acovbar') == got.index('kpis') + 1
    assert got.index('warnbar') == got.index('acovbar') + 1
    # 경고가 거르기 탭보다 위 — 「덜 불러왔다」를 알고 나서 거른다
    assert got.index('warnbar') < got.index('ffTabs')


def test_마켓_계정_칩이_가로탭_바로_아래다():
    """⑤ — 거르는 장치끼리 모아 둔다(가로탭 → 마켓 칩 → 계정 칩)."""
    got = _order(LIST, EXPECTED)
    assert got.index('mkline') == got.index('mgTabs') + 1
    assert got.index('acctline') == got.index('mkline') + 1


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


# ══ [2026-08-12 사장님 확정] 표 열 순서 1~32 ══════════════════════════════════
#  사장님이 번호를 직접 매겨 주신 순서다. 한 칸만 밀려도 잡히게 배열로 못 박는다.

import re as _re

_PC = _re.search(r'var PANEL_COLS=\[(.*?)\n    \];', SRC, _re.S)
PANEL = [(c, t) for c, a, t in
         _re.findall(r"\{c:'([^']*)',a:'([^']+)'(?:,t:'([^']*)')?\}", _PC.group(1))] if _PC else []

EXPECTED_COLS = [
    '_ostatus', '_ffcol', '_pdx_margin', '_margin', '_pp_purchase', '_supply',
    '주문상태', '송장입력', '주문일', '판매처', '쇼핑몰별칭', '_gap1',
    '상품명', '옵션', '수량', '오픈마켓주문번호',
    '구매자', '구매자번호', '수령자', '수령자전화번호', '우편번호', '주소', '_gap2',
    '단가', '실결제금액', '배송비', '정산예정금액', '정산예정금(배송비포함)',
    '총주문금액', '옵션추가금', '마켓수수료', '수수료율', '_links',
]


def test_열_순서가_사장님_확정대로다():
    got = [c for c, _ in PANEL]
    assert got == EXPECTED_COLS, f'열 순서가 바뀌었습니다\n기대: {EXPECTED_COLS}\n실제: {got}'


def test_주문이행가능이_두번째다():
    """A-1 — 사장님이 2번으로 못 박으신 신설 열."""
    assert [c for c, _ in PANEL][1] == '_ffcol'


def test_마진_두_열의_이름이_주문전_주문후로_갈린다():
    """같은 「마진」이 두 개라 어느 쪽이 실제인지 알 수 없었다."""
    d = dict(PANEL)
    assert d['_pdx_margin'] == '주문전 예상 마진'
    assert d['_margin'] == '주문후 실마진'


def test_주문판매가는_단가와_통합돼_사라졌다():
    """라이브 373건 전부 「단가」와 같았다 — 같은 숫자를 두 벌로 두지 않는다."""
    got = [c for c, _ in PANEL]
    assert '_pdx_sale' not in got
    assert '단가' in got


def test_매입가_입력칸은_남아_있다():
    """🔴 사장님 목록엔 번호가 없지만 빼면 실매입가를 적을 곳이 사라진다
    (4번 「주문후 실마진」의 재료다)."""
    assert '_pp_purchase' in [c for c, _ in PANEL]


def test_묶음_사이_여백이_둘이다():
    """사장님이 비워 두신 11·22번 = 사람 정보 앞 / 돈 앞 여백."""
    got = [c for c, _ in PANEL]
    assert got.count('_gap1') == 1 and got.count('_gap2') == 1
    assert got.index('_gap1') < got.index('상품명')
    assert got.index('_gap2') < got.index('단가')


# ── 헤더 필터 정규화 ─────────────────────────────────────────────────────────

def test_주문상태_필터가_정규화된_값을_쓴다():
    """🔴 화면 배지는 12개 통일 상태인데 ▼ 필터만 마켓 원본값이라
    **같은 화면 안에서 기준이 어긋났다**(사장님 스크린샷)."""
    assert "if(col==='주문상태')return unifyStatus(" in SRC


def test_구매자는_수령자와_같으면_한줄로_줄인다():
    """대부분 같은 사람이라 같은 이름이 두 번 서서 표만 넓어졌다."""
    assert "if(col==='구매자')return sameAsRecv(r,'구매자','수령자');" in SRC
    assert "if(col==='구매자번호')return sameAsRecv(r,'구매자번호','수령자전화번호');" in SRC
    # 필터 목록도 화면과 같은 값을 봐야 한다(화면은 「-」인데 필터가 이름이면 어긋난다)
    assert "if(col==='구매자')return _txt(sameAsRecv(" in SRC


def test_주문_이행_가능_판단_단추가_표_위에_있다():
    """사장님: "「주문 이행 가능 판단」 이렇게 누르면 실시간으로 열에 넣어줘"."""
    assert 'id="ffJudge"' in LIST
    assert '주문 이행 가능 판단' in LIST
    # 표(#droprel) 보다 위에 있어야 누르고 바로 결과를 본다
    assert LIST.index('id="ffJudge"') < LIST.index('id="droprel"')
    # 송장 작업 탭엔 두지 않는다(그 탭은 3분류 축이 따로 있다)
    assert 'id="ffJudge"' not in SHIP


def test_판단_단추는_다시_긁지_않고_저장값으로_판정한다():
    """🔴 크롤은 사장님 PC 확장이 한다 — 서버가 소싱처를 새로 못 긁는다.
    그래서 결과에 「가장 오래된 소싱처 확인」을 같이 말해야 「방금 확인했다」는
    오해가 안 생긴다."""
    assert 'loadFulfillment(loadSeq,function()' in SRC
    assert '가장 오래된 소싱처 확인은' in SRC


# ══ [2026-08-12] 열 너비 조절 + 설정 서버 저장 ═══════════════════════════════
#  사장님: "열 조절할 수 있도록해줘 / 한번 수정하면 재배포나 탭 옮겼다 와도 저장하도록."

def test_열_경계에_끌_손잡이가_붙는다():
    assert 'colgrip' in SRC and "cursor:col-resize" in SRC
    assert 'function bindColResize()' in SRC
    # 표를 다시 그릴 때마다 다시 달아야 한다(표는 innerHTML 로 통째로 갈린다)
    assert 'applyColW(); bindColResize();' in SRC


def test_너비를_놓는_순간_서버에_저장한다():
    """브라우저에만 두면 브라우저를 바꾸는 순간 사라진다(이번 신고의 원인)."""
    assert 'vpSave({widths:colW});' in SRC


def test_설정_저장은_서버_창구를_쓴다():
    assert "fetch('/orders/api/view-prefs'" in SRC
    assert 'vpSave({quick:quick});' in SRC
    assert 'vpSave({presets:presets});' in SRC


def test_브라우저_저장본은_지우지_않는다():
    """🔴 서버가 잠깐 안 될 때 화면이 빈손이 되면 안 된다 — 두 곳에 같이 둔다."""
    assert 'localStorage.setItem(QLS,JSON.stringify(quick));' in SRC


def test_브라우저에만_있던_설정은_서버로_옮겨진다():
    """사장님이 예전에 만들어 둔 기간 버튼이 옮겨 가는 길(한 번만 일어난다)."""
    assert 'if(Object.keys(up).length)vpSave(up);' in SRC
