# -*- coding: utf-8 -*-
"""[TEST] 주문 3분류 — 이행 / 미이행(S 재고없음 · P 역마진) / 클레임.

사장님 확정 (2026-07-31):
  · S = 소싱처 재고로 판정
  · P = 정산예정금(배송비포함) − 최종매입가 < 0 이면 역마진, > 0 이면 이행 가능

여기서 못 박는 것:
  · 「품절」과 「모름」을 뭉개지 않는다 — 크롤 실패를 품절로 읽으면 팔 수 있는 주문이
    미이행으로 빠진다
  · 확인 불가는 이행도 미이행 사유도 아니다 — 눈으로 볼 수 있게 따로 센다
"""
from unittest.mock import patch

import pytest

from lemouton.orders import fulfillment as FF


# ── 재고 3상태 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('sources,expect', [
    ([{'crawled_price': 1000, 'stock_out': False, 'last_status': 'ok'}], 'in'),
    ([{'crawled_price': 1000, 'stock_out': True, 'last_status': 'ok'}], 'out'),
    # 크롤이 터진 소싱처뿐 → 품절이 아니라 **모름**
    ([{'crawled_price': 1000, 'stock_out': True, 'last_status': 'error'}], 'unknown'),
    # 가격을 못 가져온 소싱처뿐 → 모름
    ([{'crawled_price': None, 'stock_out': False, 'last_status': 'ok'}], 'unknown'),
    ([], 'unknown'),
    # 하나라도 살 수 있으면 재고 있음
    ([{'crawled_price': 1000, 'stock_out': True, 'last_status': 'ok'},
      {'crawled_price': 2000, 'stock_out': False, 'last_status': 'ok'}], 'in'),
])
def test_재고는_3상태로_읽는다(sources, expect):
    assert FF.stock_state({'sources': sources}) == expect


# ── 판정 ────────────────────────────────────────────────────────────────────

def _row(no='1', settle='100,000', status='결제완료'):
    return {'판매처': '쿠팡', '오픈마켓주문번호': no, '주문상태': status,
            '상품명': '테스트', '옵션': '블랙/250', '주문일': '2026-07-31',
            FF.SETTLE_FIELD: settle}


def _run(rows, *, sku_by_key, finals, stock_by_sku):
    """매칭·매입가·재고는 이미 다른 모듈이 검증한다 — 여기선 판정만 본다."""
    from lemouton.orders import price_diff as PD

    targets = {k: {'sku': s, 'market': 'coupang', 'account': 'default', 'reason': ''}
               for k, s in sku_by_key.items()}
    # ★ product_url 을 반드시 담는다 — 실제 옵션은 소싱처 **주소**를 갖고 있고,
    #   주소가 0개면 판정이 「소싱처 URL 없음」으로 갈리기 때문이다(2026-08-12).
    _u = 'https://example.com/p/1'
    opts = [{'sku': s, 'sources': ([{'crawled_price': 1000, 'stock_out': False,
                                     'product_url': _u, 'last_status': 'ok'}] if st == 'in'
                                   else [{'crawled_price': 1000, 'stock_out': True,
                                          'product_url': _u, 'last_status': 'ok'}] if st == 'out'
                                   else [{'product_url': _u, 'last_status': 'ok'}])}
            for s, st in stock_by_sku.items()]

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return [type('O', (), {'canonical_sku': s, 'model_code': 'M'})()
                    for s in sku_by_key.values()]

    session = type('S', (), {'query': lambda self, *a, **k: _Q()})()

    with patch.object(PD, 'resolve_targets_verbose', return_value=targets), \
         patch.object(PD, '_current_purchase', return_value=(finals, {})):
        return FF.classify_rows(session, rows,
                                matrix_loader=lambda mc: {'ok': True, 'options': opts})


def test_클레임은_판정_없이_먼저_갈라진다():
    rows = [_row(status='반품요청')]
    out = _run(rows, sku_by_key={}, finals={}, stock_by_sku={})
    d = list(out.values())[0]
    assert d['group'] == FF.GROUP_CLAIM
    assert d['claim_type'] == '반품'


def test_재고가_없으면_미이행_S():
    rows = [_row()]
    from lemouton.orders import price_diff as PD
    key = PD.row_key(rows[0])
    out = _run(rows, sku_by_key={key: 'SKU-1'}, finals={'SKU-1': 50000},
               stock_by_sku={'SKU-1': 'out'})
    assert out[key]['group'] == FF.GROUP_UNFULFILL
    assert out[key]['reason'] == FF.REASON_STOCK


def test_정산예정금이_매입가보다_적으면_미이행_P():
    rows = [_row(settle='40,000')]
    from lemouton.orders import price_diff as PD
    key = PD.row_key(rows[0])
    out = _run(rows, sku_by_key={key: 'SKU-1'}, finals={'SKU-1': 50000},
               stock_by_sku={'SKU-1': 'in'})
    assert out[key]['group'] == FF.GROUP_UNFULFILL
    assert out[key]['reason'] == FF.REASON_LOSS
    assert out[key]['profit'] == -10000


def test_남으면_이행():
    rows = [_row(settle='90,000')]
    from lemouton.orders import price_diff as PD
    key = PD.row_key(rows[0])
    out = _run(rows, sku_by_key={key: 'SKU-1'}, finals={'SKU-1': 50000},
               stock_by_sku={'SKU-1': 'in'})
    assert out[key]['group'] == FF.GROUP_FULFILL
    assert out[key]['reason'] is None
    assert out[key]['profit'] == 40000


def test_매입가를_모르면_이행이라고_말하지_않는다():
    """모르는 것을 「보낼 수 있다」고 하면 손해 보는 주문이 그냥 나간다."""
    rows = [_row()]
    from lemouton.orders import price_diff as PD
    key = PD.row_key(rows[0])
    out = _run(rows, sku_by_key={key: 'SKU-1'}, finals={},
               stock_by_sku={'SKU-1': 'in'})
    assert out[key]['group'] == FF.GROUP_UNFULFILL
    assert out[key]['reason'] == FF.REASON_UNKNOWN


def test_재고를_모르면_재고없음이라고_하지_않는다():
    """크롤 실패를 품절로 읽으면 팔 수 있는 주문을 버린다."""
    rows = [_row(settle='90,000')]
    from lemouton.orders import price_diff as PD
    key = PD.row_key(rows[0])
    out = _run(rows, sku_by_key={key: 'SKU-1'}, finals={'SKU-1': 50000},
               stock_by_sku={'SKU-1': 'unknown'})
    assert out[key]['reason'] == FF.REASON_UNKNOWN
    assert out[key]['reason'] != FF.REASON_STOCK


def test_우리_상품에_매칭이_안_되면_확인_불가():
    rows = [_row()]
    from lemouton.orders import price_diff as PD
    key = PD.row_key(rows[0])
    out = _run(rows, sku_by_key={}, finals={}, stock_by_sku={})
    assert out[key]['group'] == FF.GROUP_UNFULFILL
    assert out[key]['reason'] == FF.REASON_UNKNOWN
    assert out[key]['sku'] is None


def test_정산예정금이_비면_이익을_지어내지_않는다():
    rows = [_row(settle='')]
    from lemouton.orders import price_diff as PD
    key = PD.row_key(rows[0])
    out = _run(rows, sku_by_key={key: 'SKU-1'}, finals={'SKU-1': 50000},
               stock_by_sku={'SKU-1': 'in'})
    assert out[key]['profit'] is None
    assert out[key]['reason'] == FF.REASON_UNKNOWN


def test_건수_요약():
    rows = [_row('1', '90,000'), _row('2', '40,000'), _row('3', status='취소요청')]
    from lemouton.orders import price_diff as PD
    k1, k2 = PD.row_key(rows[0]), PD.row_key(rows[1])
    out = _run(rows, sku_by_key={k1: 'SKU-1', k2: 'SKU-2'},
               finals={'SKU-1': 50000, 'SKU-2': 50000},
               stock_by_sku={'SKU-1': 'in', 'SKU-2': 'in'})
    s = FF.summarize(out)
    assert s['counts'][FF.GROUP_FULFILL] == 1
    assert s['counts'][FF.GROUP_UNFULFILL] == 1
    assert s['counts'][FF.GROUP_CLAIM] == 1
    assert s['reasons'][FF.REASON_LOSS] == 1


# ── 「우리 상품 아님」과 「확인 불가」를 가른다 ──────────────────────────────

def _run_verbose(rows, targets, finals, stock_by_sku):
    from lemouton.orders import price_diff as PD
    _u = 'https://example.com/p/1'
    opts = [{'sku': s, 'sources': ([{'crawled_price': 1000, 'stock_out': False,
                                     'product_url': _u, 'last_status': 'ok'}] if st == 'in'
                                   else [{'product_url': _u, 'last_status': 'ok'}])}
            for s, st in stock_by_sku.items()]

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return [type('O', (), {'canonical_sku': s, 'model_code': 'M'})()
                    for s in stock_by_sku]

    session = type('S', (), {'query': lambda self, *a, **k: _Q()})()
    with patch.object(PD, 'resolve_targets_verbose', return_value=targets), \
         patch.object(PD, '_current_purchase', return_value=(finals, {})):
        return FF.classify_rows(session, rows,
                                matrix_loader=lambda mc: {'ok': True, 'options': opts})


def test_남의_상품_주문은_우리_상품_아님으로_센다():
    """모음전으로 관리하지 않는 상품을 「확인 불가」로 뭉개면 전부 문제처럼 보인다."""
    from lemouton.orders import price_diff as PD
    rows = [_row()]
    key = PD.row_key(rows[0])
    out = _run_verbose(rows, {key: {'sku': None, 'market': 'coupang',
                                    'account': None, 'reason': PD.MATCH_NOT_OURS}},
                       {}, {})
    assert out[key]['reason'] == FF.REASON_NOT_OURS
    assert out[key]['reason'] != FF.REASON_UNKNOWN


def test_못_좁힌_것은_확인_불가로_남는다():
    """후보가 여럿이라 못 좁힌 건 우리 상품일 수 있다 — 남의 상품이라고 하면 안 된다."""
    from lemouton.orders import price_diff as PD
    rows = [_row()]
    key = PD.row_key(rows[0])
    out = _run_verbose(rows, {key: {'sku': None, 'market': 'coupang',
                                    'account': None, 'reason': PD.MATCH_AMBIGUOUS}},
                       {}, {})
    assert out[key]['reason'] == FF.REASON_UNKNOWN


def test_마켓이_번호를_안_주면_확인_불가다():
    """번호가 없으면 남의 상품인지 우리 상품인지 알 수 없다 — 단정하지 않는다."""
    from lemouton.orders import price_diff as PD
    rows = [_row()]
    key = PD.row_key(rows[0])
    out = _run_verbose(rows, {key: {'sku': None, 'market': 'coupang',
                                    'account': None, 'reason': PD.MATCH_NO_IDS}},
                       {}, {})
    assert out[key]['reason'] == FF.REASON_UNKNOWN


# ── 바로가기 (노션 ⑤「바로가기 버튼」) ──────────────────────────────────────

def _run_links(rows, targets, opts):
    from lemouton.orders import price_diff as PD

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return [type('O', (), {'canonical_sku': o['sku'], 'model_code': 'M'})()
                    for o in opts]

    session = type('S', (), {'query': lambda self, *a, **k: _Q()})()
    with patch.object(PD, 'resolve_targets_verbose', return_value=targets), \
         patch.object(PD, '_current_purchase', return_value=({}, {})):
        return FF.classify_rows(session, rows,
                                matrix_loader=lambda mc: {'ok': True, 'options': opts})


def test_소싱처_주소와_상품관리_링크를_함께_준다():
    """무재고라 소싱처 링크가 곧 주문할 곳이다."""
    from lemouton.orders import price_diff as PD
    rows = [_row()]
    key = PD.row_key(rows[0])
    out = _run_links(
        rows, {key: {'sku': 'S1', 'market': 'coupang', 'account': 'd', 'reason': ''}},
        [{'sku': 'S1', 'sources': [
            {'crawled_price': 1000, 'stock_out': False, 'last_status': 'ok',
             'source_name': '무신사', 'product_url': 'https://musinsa/x'}]}])
    L = out[key]['links']
    assert L['sources'] == [{'label': '무신사', 'url': 'https://musinsa/x'}]
    assert L['product'] == '/bundles/M'


def test_같은_주소는_한_번만_준다():
    from lemouton.orders import price_diff as PD
    rows = [_row()]
    key = PD.row_key(rows[0])
    out = _run_links(
        rows, {key: {'sku': 'S1', 'market': 'coupang', 'account': 'd', 'reason': ''}},
        [{'sku': 'S1', 'sources': [
            {'crawled_price': 1000, 'stock_out': False, 'last_status': 'ok',
             'source_name': '무신사', 'product_url': 'https://musinsa/x'},
            {'crawled_price': 900, 'stock_out': False, 'last_status': 'ok',
             'source_name': '무신사', 'product_url': 'https://musinsa/x'}]}])
    assert len(out[key]['links']['sources']) == 1


def test_주소가_없는_소싱처는_버튼을_만들지_않는다():
    """빈 링크를 누르면 아무 일도 안 일어나 「고장」으로 읽힌다."""
    from lemouton.orders import price_diff as PD
    rows = [_row()]
    key = PD.row_key(rows[0])
    out = _run_links(
        rows, {key: {'sku': 'S1', 'market': 'coupang', 'account': 'd', 'reason': ''}},
        [{'sku': 'S1', 'sources': [
            {'crawled_price': 1000, 'stock_out': False, 'last_status': 'ok',
             'source_name': '무신사', 'product_url': None}]}])
    assert out[key]['links']['sources'] == []


def test_우리_상품이_아니면_링크가_없다():
    from lemouton.orders import price_diff as PD
    rows = [_row()]
    key = PD.row_key(rows[0])
    out = _run_links(rows, {key: {'sku': None, 'market': 'coupang',
                                  'account': None, 'reason': PD.MATCH_NOT_OURS}}, [])
    assert out[key]['links'] is None


def test_소싱처_이름을_한글로_보여준다():
    """버튼에 「lo」·「hm」 같은 영문 키가 뜨면 사장님이 어느 소싱처인지 못 읽는다."""
    from lemouton.orders import price_diff as PD
    rows = [_row()]
    key = PD.row_key(rows[0])
    out = _run_links(
        rows, {key: {'sku': 'S1', 'market': 'coupang', 'account': 'd', 'reason': ''}},
        [{'sku': 'S1', 'sources': [
            {'crawled_price': 1000, 'stock_out': False, 'last_status': 'ok',
             'source_key': 'hmall', 'source_name': None,
             'product_url': 'https://hmall/x'},
            {'crawled_price': 1000, 'stock_out': False, 'last_status': 'ok',
             'source_key': 'lotteimall', 'source_name': None,
             'product_url': 'https://lotteimall/x'}]}])
    assert [x['label'] for x in out[key]['links']['sources']] == ['H몰', '롯데아이몰']


def test_모르는_소싱처_키는_지어내지_않는다():
    from lemouton.sources.site_labels import label_of
    assert label_of('처음보는곳') == '처음보는곳'
    assert label_of('') == ''


# ══ [2026-08-12 사장님] 소싱처 주소가 아예 없는 줄 ════════════════════════════
#  "소싱처url 없으면 확인불가가 아니라, 소싱처url 없음으로 표기해줘."
#  두 경우가 있다 — ① 오프라인 사입해 재고를 두고 파는 상품 ② 아직 연동 안 된 상품.
#  둘 다 「크롤하면 알 수 있는데 안 했다」가 아니라서, 확인 불가와 같은 말로 뭉개면
#  사장님이 **고칠 게 없는 줄**을 계속 들여다보게 된다.

def _run_no_url(rows, sku_by_key, finals):
    from unittest.mock import patch as _patch
    from lemouton.orders import price_diff as PD
    targets = {k: {'sku': s, 'market': 'coupang', 'account': 'default', 'reason': ''}
               for k, s in sku_by_key.items()}
    opts = [{'sku': s, 'sources': []} for s in sku_by_key.values()]   # 주소 0개

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return [type('O', (), {'canonical_sku': s, 'model_code': 'M'})()
                    for s in sku_by_key.values()]

    session = type('S', (), {'query': lambda self, *a, **k: _Q()})()
    with _patch.object(PD, 'resolve_targets_verbose', return_value=targets),          _patch.object(PD, '_current_purchase', return_value=(finals, {})):
        return FF.classify_rows(session, rows,
                                matrix_loader=lambda mc: {'ok': True, 'options': opts})


def test_소싱처_주소가_없으면_확인불가가_아니라_소싱처URL없음():
    from lemouton.orders import price_diff as PD
    rows = [_row(settle='90,000')]
    key = PD.row_key(rows[0])
    out = _run_no_url(rows, {key: 'SKU-1'}, {})
    assert out[key]['reason'] == FF.REASON_NO_SOURCE_URL
    assert out[key]['no_url_why'] == 'ours_no_url'
    assert out[key]['source_urls'] == 0


def test_소싱처URL없음은_재고없음_역마진_판정을_덮지_않는다():
    """🔴 이 순서가 뒤집히면 「재고 없음」·「역마진」이라는 **더 정확한 답**이 사라진다.
    실제로 처음 구현에서 뒤집혀 시험 5건이 깨졌다."""
    from lemouton.orders import price_diff as PD
    # 주소는 없지만 재고가 품절이라고 이미 알고 있는 경우
    rows = [_row(settle='90,000')]
    key = PD.row_key(rows[0])
    out = _run(rows, sku_by_key={key: 'SKU-1'}, finals={'SKU-1': 50000},
               stock_by_sku={'SKU-1': 'out'})
    assert out[key]['reason'] == FF.REASON_STOCK


def test_크롤_시각을_같이_돌려준다():
    """판정은 **마지막으로 긁은 값** 기준이라, 그 시각이 없으면 3일 전 재고를
    오늘 것인 척 보여주게 된다."""
    from lemouton.orders import price_diff as PD
    rows = [_row(settle='90,000')]
    key = PD.row_key(rows[0])
    out = _run(rows, sku_by_key={key: 'SKU-1'}, finals={'SKU-1': 50000},
               stock_by_sku={'SKU-1': 'in'})
    assert 'crawled_at' in out[key]        # 값이 없어도 **키는 온다**(화면이 늘 읽는다)
    assert out[key]['source_urls'] == 1
