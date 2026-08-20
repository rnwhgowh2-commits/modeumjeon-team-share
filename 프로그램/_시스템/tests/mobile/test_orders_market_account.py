# -*- coding: utf-8 -*-
"""배치5-4차 — 폰 주문 화면의 마켓·계정 구분 (사장님 확정 A3+B1+C1+D1).

사장님 요청(2026-08-06): 「모바일 주문내역도 PC와 같이 마켓별·계정별 구분해서 보고,
누르면 그 주문내역과 매출 등이 나오고, 정산예정금도 포함되고, 못 불러온 계정은
다시 불러올 수 있어야 한다.」

무엇을 지키나
    ① 마켓·계정은 **새 조회를 만들지 않는다** — 이미 받은 행의 '판매처'·'쇼핑몰별칭'
       으로만 가른다. 서버에 새 집계 API 를 만들면 PC 와 다른 숫자가 나올 길이 열린다.
    ② 🔴 한 화면 한 범위 — 목록·매출·마진·송장·품절위험이 **모두 visRows() 한 함수**를
       탄다. 판마다 따로 거르면 「목록은 쿠팡인데 매출은 전체」인 거짓 화면이 된다.
    ③ 🔴 정산예정금의 정직성 — 모르는 행을 0 으로 합에 넣지 않는다(건수로만 센다).
       라벨에 「입금일 기준 아님」을 못 박는다: 주문일 기준 합을 입금-달로 읽는 오독이
       2026-08-06 정산예정금액 탭에서 라이브에 5.5억 거짓을 낸 바로 그 부류다.
    ④ 매출·정산예정금의 **모수가 같다** — 둘 다 SCOPE(취소·반품 제외). 한쪽만 빼면
       같은 격자에서 견줄 수 없다.
    ⑤ 「다시 시도」는 서버 90초 캐시를 무시(fresh=1)하는 PC 와 **같은 길**을 쓴다.
    ⑥ 🔴 못 불러옴(실패)과 중복 접힘(정상)을 **다른 상자**에 그린다 — 섞으면 멀쩡한
       계정이 고장난 것처럼 보인다(PC renderWarn 이 두 덩이를 나누는 것과 같은 규칙).
    ⑦ C1 정렬 — 숫자는 자릿수가 세로로 맞아야 마켓끼리 견줄 수 있다(tabular-nums).
    ⑧ 손끝 목표 44px — 이 화면이 이미 실측으로 못 박아 둔 규칙(칩 31→44).

★ '낱말이 어딘가 있나'로 검사하지 않는다 — JS 는 그 줄 본문을, CSS 는 규칙 본문을
  정규식으로 못 박는다(형제 시험들과 같은 방식).
"""
import re
from pathlib import Path

import pytest

_TPL = (Path(__file__).resolve().parents[2] / 'webapp' / 'templates'
        / 'mobile' / 'orders.html')


@pytest.fixture(scope='module')
def src() -> str:
    return _TPL.read_text(encoding='utf-8')


def _css_body(src: str, selector: str) -> str:
    """CSS 규칙 **본문**을 꺼낸다(낱말 검사 금지 — 주석에 있어도 통과하면 안 되므로)."""
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', src)
    assert m, f'CSS 규칙 {selector} 가 없어요'
    return m.group(1)


def _fn_body(src: str, name: str) -> str:
    """`function name(...){ ... }` 의 본문을 중괄호 균형으로 잘라낸다."""
    m = re.search(r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{', src)
    assert m, f'함수 {name} 이 없어요'
    i, depth = m.end(), 1
    while i < len(src) and depth:
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
        i += 1
    return src[m.end():i - 1]


# ── ① 새 조회를 만들지 않는다 — 행의 두 칸으로만 가른다 ──────────────────
def test_filter_uses_existing_row_fields_not_a_new_api(src):
    # [5차] visRows 는 rowsExcept('') 로 위임한다 — 거르는 실체는 그쪽 한 곳에만 있다.
    assert re.search(r"function visRows\(\)\{\s*return rowsExcept\(''\);", src), \
        'visRows 가 rowsExcept 한 곳으로 위임하지 않아요(거르는 규칙이 두 곳이면 갈라져요)'
    body = _fn_body(src, 'rowsExcept')
    assert "r['판매처']" in body, "마켓은 행의 '판매처' 칸으로 갈라야 해요"
    assert "r['쇼핑몰별칭']" in body, "계정은 행의 '쇼핑몰별칭' 칸으로 갈라야 해요"
    # 마켓·계정 전용 새 엔드포인트를 부르면 PC 와 다른 숫자가 나올 길이 열린다.
    for bad in ('/mobile/orders/api/', 'market-summary', 'account-summary'):
        assert bad not in src, f'마켓·계정용 새 조회({bad})를 만들면 안 돼요'


# ── ② 한 화면 한 범위 — 다섯 판이 모두 visRows() 를 탄다 ──────────────────
@pytest.mark.parametrize('fn', ['renderList', 'renderKpis', 'shipRowsOf',
                                'mgSubset', 'noInvN', 'todayRows', 'renderRisk'])
def test_every_pane_goes_through_visrows(src, fn):
    assert 'visRows()' in _fn_body(src, fn), (
        f'{fn} 이 visRows() 를 안 타면 판마다 범위가 갈라져요')


def test_chip_count_follows_the_filter(src):
    body = _fn_body(src, 'chipCounts')
    assert re.search(r"setCnt\('mo-cnt-list',\s*trusted\?visRows\(\)\.length:null\)", body), \
        '「목록」 칩 개수도 고른 마켓·계정 기준이어야 해요(못 불러왔으면 - )'


# ══════════ [5차] PC 와 같은 다중 선택 ══════════════════════════════════════
#   사장님 지적(2026-08-06): 「PC와 같이 마켓/계정 중복 선택 기능 안 되고 있어」.
#   폰만 한 번에 하나씩이었다. 규칙은 PC(orders/index.html toggleMarket·toggleAccount)를
#   그대로 옮긴다 — 한쪽만 다르면 **같은 조작에 두 화면이 다른 답**을 낸다.

def test_selection_state_is_a_set_not_a_single_value(src):
    assert re.search(r'var\s+selMk=new Set\(\),\s*selAcc=\{\}', src), \
        '마켓은 집합, 계정은 마켓별 집합이어야 여러 개를 고를 수 있어요'
    # 옛 한 개짜리 상태가 남아 있으면 두 규칙이 공존해 갈라진다.
    assert not re.search(r'var sel=\{mk:', src), '옛 한 개짜리 선택 상태가 남아 있어요'


def test_market_toggle_matches_pc(src):
    """PC toggleMarket — 다시 누르면 빼기 / 전무·전부면 필터 해제(= 전체)."""
    body = _fn_body(src, 'toggleMarket')
    assert re.search(r'if\(selMk\.has\(m\)\)selMk\.delete\(m\);\s*else selMk\.add\(m\);', body), \
        '마켓은 눌러서 더하고 다시 눌러서 빼야 해요'
    assert re.search(r'selMk\.size===0\|\|selMk\.size===allMarketLabels\(\)\.length', body), \
        '전무·전부면 필터를 풀어야 해요(PC 와 같은 규약)'


def test_account_toggle_matches_pc(src):
    """PC toggleAccount 세 갈래 — 「전체」에서 첫 클릭 = 그 계정만 / 이후 토글 / 전부면 해제."""
    body = _fn_body(src, 'toggleAccount')
    assert re.search(r'if\(pick\.size===A\.length\)\{\s*pick=new Set\(\[a\]\);\s*\}', body), \
        '「전체」 상태에서 처음 누르면 그 계정만 남아야 해요'
    assert re.search(r'else if\(pick\.has\(a\)\)\{\s*pick\.delete\(a\);\s*\}\s*else\s*\{\s*pick\.add\(a\);', body), \
        '그 뒤로는 눌러서 더하고 다시 눌러서 빼야 해요'
    assert re.search(r'pick\.size===0\|\|pick\.size===A\.length', body), \
        '전무·전부면 그 마켓 계정 필터를 풀어야 해요'


def test_accounts_are_independent_per_market(src):
    """계정 집합은 **마켓마다 따로** — 쿠팡에서 고른 게 롯데온에 영향 주면 안 된다."""
    assert re.search(r'selAcc\[m\]', _fn_body(src, 'toggleAccount')), \
        '계정 선택이 마켓별로 나뉘어 있지 않아요'
    assert 'allAccounts(m)' in _fn_body(src, 'toggleAccount')


def test_account_chip_rows_are_grouped_per_selected_market(src):
    """PC renderAcctChips — 고른 마켓마다 한 줄, 계정 2곳 이상인 마켓만."""
    body = _fn_body(src, 'renderAccChips')
    assert 'Array.from(selMk)' in body, '고른 마켓들마다 줄을 만들어야 해요'
    assert re.search(r'allAccounts\(m\)\.length>=2', body), \
        '계정이 1곳뿐인 마켓은 고를 게 없어 줄을 만들면 안 돼요'
    assert 'mv-accgrp' in body and 'mv-acclbl' in body, \
        '줄마다 어느 마켓 계정인지 이름표가 있어야 해요'


def test_chip_counts_exclude_their_own_axis(src):
    """쿠팡을 고른 순간 다른 마켓 칩이 0 이 되면 갈아탈 수 없다 — PC filteredExcept 와 같은 처방."""
    assert "rowsExcept('mk')" in _fn_body(src, 'renderMkChips'), \
        '마켓 칩 건수는 마켓 조건을 뺀 기준이어야 해요'
    assert "rowsExcept('acc')" in _fn_body(src, 'renderAccChips'), \
        '계정 칩 건수는 계정 조건을 뺀 기준이어야 해요'


def test_summary_rows_and_chips_share_one_rule(src):
    """요약 줄을 눌러도 칩과 **같은 함수**를 부른다 — 두 곳이 다르게 동작할 수 없다."""
    src_tail = src[src.index("mo-mv-list').addEventListener"):]
    assert 'toggleAccount(mk,acc)' in src_tail and 'toggleMarket(mk)' in src_tail, \
        '요약 줄이 자기만의 선택 규칙을 따로 쓰면 칩과 갈라져요'
    assert not re.search(r'function pickMarket', src), '옛 단일 선택 함수가 남아 있어요'


def test_summary_highlight_looks_up_accounts_by_market_label(src):
    """🔴 실측으로 잡은 버그 — 집계 객체를 넘기면 selAcc["[object Object]"] 를 뒤져
    목록·매출은 맞게 걸리는데 **요약 줄만 강조가 안 되는** 어긋난 화면이 된다."""
    body = _fn_body(src, 'renderSummary')
    assert 'selectedAcctsIn(m.label)' in body, \
        'selectedAcctsIn 에 마켓 라벨(m.label)을 넘겨야 해요 — 객체를 넘기면 강조가 안 돼요'
    assert not re.search(r'selectedAcctsIn\(m\)', body), '집계 객체를 그대로 넘기면 안 돼요'


def test_account_row_click_also_selects_its_market(src):
    """계정만 걸리고 마켓이 안 걸리면 계정 칩 줄이 안 나타나 되돌릴 손잡이가 없다."""
    src_tail = src[src.index("mo-mv-list').addEventListener"):]
    assert re.search(r'if\(!selMk\.has\(mk\)\)toggleMarket\(mk\);', src_tail), \
        '계정 줄을 누르면 그 마켓도 같이 골라져야 해요'


def test_all_chip_clears_both_filters(src):
    src_tail = src[src.index("mo-mk-chips').addEventListener"):]
    assert re.search(r'selMk\.clear\(\);\s*selAcc=\{\}', src_tail), \
        '「전체」는 마켓·계정 필터를 모두 풀어야 해요'


def test_account_name_drops_redundant_market_suffix(src):
    """「브랜드마켓(쿠팡)」 → 「브랜드마켓」 — PC acctName 과 같은 규칙(원본은 title 로 남긴다)."""
    body = _fn_body(src, 'acctName')
    assert '쿠팡|스마트스토어' in body and 'replace' in body
    assert 'title="\'+esc(a)+\'"' in _fn_body(src, 'renderAccChips'), \
        '줄인 이름만 남기고 원본을 잃으면 안 돼요'


def test_selection_label_stays_short_on_a_phone(src):
    """여러 개를 고르면 라벨이 길어져 375px 에서 줄바꿈된다 — 두 개까지만 적는다."""
    body = _fn_body(src, 'selLabel')
    assert re.search(r"head\.length<=2\?head\.join\('·'\):head\[0\]\+' 외 '", body), \
        '고른 게 많으면 「외 N곳」으로 줄여야 해요'


# ── 🔴 라이브 실측(2026-08-06)에서 잡은 거짓 0 — 여기서 굳힌다 ──────────────
#   자격증명이 없으면 서버는 실패가 아니라 **ok=true + 0건 + 경고**로 답한다.
#   그 0 을 진짜 0 으로 읽어, 전 마켓을 못 불러온 상태에서 매출·정산예정금이
#   「0 원」으로 떴다(= 「안 팔렸다」는 단정). 0 원은 모름이 아니다.
def test_empty_plus_failure_is_unknown_not_zero(src):
    body = _fn_body(src, 'mkTrusted')
    assert 'parts[m.key]==null' in body, '응답을 못 받은 마켓은 믿을 수 없어요'
    assert re.search(r'if\(\(parts\[m\.key\]\|\|\[\]\)\.length\)return true;', body), \
        '실제 행을 받았으면 믿어야 해요(부분 실패까지 통째로 - 로 만들면 과잉)'
    assert 'return !mkFailed(m.key);' in body, \
        '0건인데 실패 경고까지 있으면 「모름」이어야 해요(0 으로 단정 금지)'


@pytest.mark.parametrize('fn', ['renderKpis', 'renderRisk', 'renderMargin',
                                'renderShip', 'chipCounts', 'renderList'])
def test_zero_vs_unknown_uses_the_trusted_test(src, fn):
    # [5차] 「보는 범위」 기준이어야 한다 — 아래 시험이 그 이유를 설명한다.
    assert 'scopeTrusted()' in _fn_body(src, fn), (
        f'{fn} 이 「응답만 왔는지」로 0 을 그리면 못 불러온 걸 0 이라 말해요')


def test_trust_is_judged_on_the_scope_being_viewed(src):
    """🔴 [5차 실측] 다중 선택이 생기며 드러난 거짓 화면 —
    스마트스토어만 골랐는데 그게 실패하면, **쿠팡이 성공했다는 이유로**
    「스마트스토어 주문이 없어요 · 매출 0원」이라 말했다(못 불러온 걸 「없다」고 단정)."""
    body = _fn_body(src, 'scopeTrusted')
    assert re.search(r'if\(!selMk\.size\)return anyTrusted\(\);', body), \
        '마켓을 안 골랐으면 전체가 곧 보는 범위예요'
    assert re.search(r'selMk\.has\(m\.label\)\s*&&\s*mkTrusted\(m\)', body), \
        '고른 마켓 중 믿을 수 있는 게 있는지로 판정해야 해요'
    # 마켓 칩의 「전체」 건수만은 전체 기준이 맞다(무엇을 고르든 전체는 전체다).
    assert re.search(r'anyTrusted\(\)\?won\(base\.length\)', _fn_body(src, 'renderMkChips')), \
        '「전체」 칩 건수는 전체 기준이어야 해요'


def test_scope_trusted_does_not_call_itself(src):
    """자기 자신을 부르면 화면이 통째로 죽는다(실측에서 실제로 났다 — 무한 반복)."""
    body = _fn_body(src, 'scopeTrusted')
    assert 'scopeTrusted(' not in body, 'scopeTrusted 가 자기 자신을 부르고 있어요'


def test_settle_shows_dash_when_no_row_amount_is_known(src):
    """고른 계정의 행이 전부 「정산예정금 모름」이면 '-' — 0 원은 「받을 게 없다」는 단정."""
    # [6차] 아는 행 수는 공용 함수의 counted 를 그대로 받는다(여기서 다시 세지 않는다).
    assert 'known:s.counted' in _fn_body(src, 'settleOf'), \
        '금액을 아는 행 수(known)를 받아야 「전부 모름」을 가릴 수 있어요'
    assert re.search(r"\(!st\.known&&st\.unknown\)\?'-'", _fn_body(src, 'renderKpis')), \
        '아는 행이 0 인데 0 원이라 그리면 안 돼요'
    assert re.search(r"\(!s\.known&&s\.unk\)\?'-'", _fn_body(src, 'mvNums')), \
        '요약 줄도 같은 규칙이어야 해요(위 숫자칸과 갈라지면 안 됨)'


def test_empty_list_tells_failure_apart_from_real_zero(src):
    """못 불러온 것과 진짜 0건은 다른 사실이다 — 「주문이 없어요」로 뭉치면 거짓 화면."""
    body = _fn_body(src, 'renderList')
    # [5차] 판정이 「보는 범위」 기준으로 바뀌었다 — 고른 마켓만 실패해도 「없어요」라 말하면 안 된다.
    assert re.search(r'if\(!scopeTrusted\(\)\)\{', body), \
        '못 불러왔을 때와 주문 0건일 때의 안내가 같으면 안 돼요'
    assert '주문을 불러오지 못했어요' in body


# ── ③ 정산예정금 — 모르면 0 으로 더하지 않는다 + 「입금일 기준 아님」 ────────
def test_settle_never_counts_unknown_as_zero(src):
    """🔴 [6차] 사장님 지적 「PC와 모바일에서 정산예정금 차이가 있어」의 근본 수정.

    원인: 폰이 `정산예정금액`(=상품분, 배송비 뺀 값)을 직접 더했고, PC 는 공용 파일의
    `정산예정금(배송비포함)`(=정산예정금액+고객배송비)을 썼다 → 폰이 **배송비 정산분만큼
    늘 적게** 나왔다. order_claim_scope.js 머리말이 「왜 정산예정금액이 아닌가」를 이미
    못 박아 뒀는데, 매출만 공용 함수를 쓰고 정산예정금은 새로 만든 것이 잘못이다."""
    body = _fn_body(src, 'settleOf')
    assert 'SCOPE.settleSummary(sub)' in body, \
        '정산예정금은 PC 와 **같은 함수**(SCOPE.settleSummary)에서 나와야 해요'
    # 상품분 열을 직접 더하는 옛 산식이 남아 있으면 다시 갈라진다.
    assert "정산예정금액'" not in body, \
        "`정산예정금액`(상품분)을 직접 더하면 배송비 정산분이 빠져요"
    # 모르는 건수는 그 함수의 blank 를 그대로 쓴다(여기서 다시 세면 두 정의가 된다).
    assert re.search(r'unknown:s\.blank', body) and re.search(r'known:s\.counted', body), \
        '모르는 건수도 같은 함수의 답(blank·counted)을 써야 해요'


def test_settle_field_is_the_shared_one_everywhere(src):
    """줄 상세의 정산예정도 위 숫자칸과 **같은 열** — 줄을 다 더해도 합계가 맞아야 한다."""
    assert "num(r[SCOPE.SETTLE_FIELD])" in src, \
        '줄 상세가 공용 열(SCOPE.SETTLE_FIELD)을 안 쓰면 합계와 어긋나요'
    # 화면 어디에도 상품분 열을 직접 읽는 곳이 남으면 안 된다(주석은 허용).
    code = '\n'.join(l for l in src.split('\n')
                     if "정산예정금액" in l and not l.strip().startswith('//')
                     and not l.strip().startswith('{#'))
    assert not re.search(r"r\['정산예정금액'\]", code), \
        f'상품분 열을 직접 읽는 곳이 남아 있어요:\n{code}'


def test_settle_label_says_it_is_not_a_payout_date(src):
    """주문일 기준 합을 「입금일」로 읽는 오독을 라벨이 막는다(5.5억 거짓의 부류)."""
    assert '입금일 기준 아님' in src
    body = _fn_body(src, 'renderKpis')
    assert 'mo-kpi-settle-c' in body, '잔글씨를 배선이 채워야 해요(정적 문구 고정 금지)'
    assert '입금일 기준 아님' in body


def test_settle_reports_unknown_count_on_screen(src):
    body = _fn_body(src, 'renderKpis')
    assert re.search(r'st\.unknown\s*\?', body), \
        '정산예정금을 모르는 건수를 화면에 밝혀야 해요(조용히 빼면 합계가 작아 보여요)'


# ── ④ 매출과 정산예정금의 모수가 같다 ────────────────────────────────────
def test_sales_and_settle_share_the_same_scope(src):
    """둘 다 취소·반품 제외(order_claim_scope.js 단일 원천). 한쪽만 빼면 견줄 수 없다."""
    # [6차] 이제 둘 다 공용 파일(order_claim_scope.js)의 함수를 그대로 부른다 —
    #   제외 규칙이 그 안에 한 번만 있으므로 모수가 갈라질 수 없다.
    assert 'SCOPE.settleSummary' in _fn_body(src, 'settleOf'), \
        '정산예정금도 매출과 같은 모수(취소·반품 제외)를 써야 해요'
    assert 'SCOPE.salesOf' in _fn_body(src, 'salesOf')


def test_summary_rows_reuse_the_same_two_functions(src):
    """마켓·계정 줄의 매출·정산예정금이 KPI 와 **같은 함수**에서 나온다."""
    body = _fn_body(src, 'mvStats')
    assert 'salesOf(' in body and 'settleOf(' in body, \
        '요약 줄이 산식을 새로 만들면 위 숫자칸과 갈라져요'


# ── ⑤ 「다시 시도」 = fresh=1 (PC 와 같은 길) ─────────────────────────────
def test_retry_forces_a_fresh_fetch(src):
    body = _fn_body(src, 'retryMarket')
    assert 'fresh=1' in body, '「다시 시도」가 90초 캐시를 무시(fresh=1)해야 실조회가 돼요'
    assert '/orders/preview.json' in body, 'PC 와 같은 엔드포인트를 써야 해요(새 경로 금지)'
    assert 'retryBusy' in body, '연타 방지가 있어야 해요'


def test_retry_button_exists_for_each_failed_account_and_for_all(src):
    body = _fn_body(src, 'renderFail')
    assert 'data-remk=' in body, '못 불러온 계정마다 「다시 시도」가 있어야 해요'
    assert 'mo-retry-all' in body, '「모두 다시 시도」가 있어야 해요'
    # 눌린 척 금지 — 진행 중엔 단추를 잠그고 그렇게 말한다.
    assert 'disabled' in body and '불러오는 중' in body


# ── ⑥ 실패와 중복은 다른 상자 ────────────────────────────────────────────
def test_failures_and_duplicates_are_never_mixed(src):
    body = _fn_body(src, 'renderFail')
    assert "getElementById('mo-fail')" in body
    assert "getElementById('mo-dup')" in body, \
        '중복 접힘은 실패와 다른 상자에 그려야 해요(멀쩡한 계정이 고장난 것처럼 보임)'
    split = _fn_body(src, 'warnSplit')
    assert 'isDupKind' in split, '중복인지 실패인지 가르는 판정이 있어야 해요'


def test_top_warning_bar_does_not_repeat_the_failure_list(src):
    """같은 사실이 한 화면에 두 번 나오지 않는다(위 띠 + 아래 띠 중복 금지)."""
    body = _fn_body(src, 'renderWarns')
    assert 'sp.other' in body, '위 띠에는 마켓을 못 짚는 일반 알림만 남겨야 해요'


# ── ⑦ C1 정렬 — 숫자 자릿수가 세로로 맞는다 ──────────────────────────────
def test_summary_numbers_are_digit_aligned(src):
    body = _css_body(src, '.mv-v')
    assert 'tabular-nums' in body, '숫자가 세로로 가지런해야 마켓끼리 견줄 수 있어요'
    assert 'font-weight:700' in body.replace(' ', '')


def test_summary_row_is_name_left_numbers_right(src):
    """C1 = 왼쪽 이름 / 오른쪽 숫자. 한 격자라 전 행이 열 폭을 공유한다."""
    body = _css_body(src, '.mv-c1').replace(' ', '')
    assert 'display:grid' in body
    assert 'grid-template-columns:1frmax-content' in body, \
        '이름 칸은 남는 폭을, 숫자 칸은 내용 폭을 가져야 해요(과대 고정폭 금지)'
    nums = _css_body(src, '.mv-nums').replace(' ', '')
    assert 'justify-items:end' in nums, '숫자는 오른쪽에 맞아야 해요'


def test_label_and_value_stay_together(src):
    """라벨을 값에서 먼 우측으로 밀지 않는다(칸 안 빈 공간 방지)."""
    assert 'justify-self:start' in _css_body(src, '.mv-k').replace(' ', '')


# ── ⑧ 손끝 목표 44px ────────────────────────────────────────────────────
@pytest.mark.parametrize('sel', ['.mv-row', '.mv-retry', '.mv-allbtn'])
def test_touch_targets_are_at_least_44px(src, sel):
    body = _css_body(src, sel).replace(' ', '')
    m = re.search(r'min-height:(\d+)px', body)
    assert m and int(m.group(1)) >= 44, f'{sel} 은 손끝 목표 44px 이상이어야 해요'


# ── 화면 뼈대 — 자리는 서버가 아니라 배선이 채운다(지어낸 숫자 금지) ─────────
@pytest.mark.parametrize('el_id', ['mo-mk-chips', 'mo-acc-chips', 'mo-mv-list',
                                   'mo-fail', 'mo-dup', 'mo-kpi-settle'])
def test_screen_has_the_new_slots(src, el_id):
    assert f'id="{el_id}"' in src, f'{el_id} 자리가 화면에 있어야 해요'


def test_market_and_account_lists_are_not_hardcoded(src):
    """마켓·계정을 JS 에 적으면 새 마켓·새 계정이 조용히 빠진다."""
    for fn, 원천 in (('renderMkChips', 'mvStats()'), ('renderAccChips', 'allAccounts(')):
        body = _fn_body(src, fn)
        assert 원천 in body, f'{fn} 은 불러온 행에서 만들어야 해요'
        for hard in ('쿠팡', '스마트스토어', '롯데온', '11번가'):
            assert hard not in body, f'{fn} 에 마켓 이름을 적으면 안 돼요({hard})'
    # allAccounts 도 행에서 만든다(마켓 목록을 JS 에 적으면 새 계정이 조용히 빠진다).
    assert "r['쇼핑몰별칭']" in _fn_body(src, 'allAccounts')


def test_empty_list_message_names_the_selected_scope(src):
    """「30일 · 쿠팡」을 보는데 그냥 「주문이 없어요」라 말하면 거짓 화면이 된다."""
    body = _fn_body(src, 'renderList')
    assert 'selLabel()' in body, '빈 안내가 지금 고른 마켓·계정을 말해야 해요'


def test_stale_account_chip_survives_zero_rows(src):
    """기간을 바꿔 고른 계정 주문이 0건이 되어도 칩을 남긴다 — 왜 비었는지 보이게."""
    body = _fn_body(src, 'renderAccChips')
    assert re.search(r'!allOn\s*&&\s*!seen', body), \
        '고른 계정이 0건이 되면 칩이 사라져 목록이 왜 비었는지 알 수 없어요'


def test_cs_admits_it_cannot_narrow_to_account(src):
    """CS 원천엔 계정이 없다 — 없는 걸 있는 척 좁히지 않고 그 사실을 화면에 밝힌다."""
    body = _fn_body(src, 'renderCs')
    assert 'selAcc' in body and '계정 정보가 없어요' in body
    assert 'selMk' in _fn_body(src, 'csItems'), 'CS 목록도 고른 마켓을 따라야 해요'


def test_failed_market_row_is_not_selectable(src):
    """못 불러온 마켓을 고르면 빈 목록이 「주문 0건」으로 오해된다."""
    assert re.search(r"classList\.contains\('bad'\)\s*\)\s*return", src), \
        '못 불러온 마켓 줄은 눌러도 걸리지 않아야 해요'


# ── 실화면 — 열리고, 새 자리가 그려진다 ──────────────────────────────────
def test_orders_page_renders_with_new_sections(flask_app):
    c = flask_app.test_client()
    r = c.get('/mobile/orders')
    assert r.status_code == 200
    html = r.data.decode('utf-8')
    for el_id in ('mo-mk-chips', 'mo-acc-chips', 'mo-mv-list', 'mo-fail',
                  'mo-dup', 'mo-kpi-settle'):
        assert f'id="{el_id}"' in html
    # 초기값은 '-' — 서버 답 전에 그럴듯한 수를 그려 두지 않는다.
    assert re.search(r'id="mo-kpi-settle"[^>]*>-<', html)
    assert '입금일 기준 아님' in html
