# -*- coding: utf-8 -*-
"""대시보드 API — 화면이 읽는 모양을 고정한다."""
from webapp.routes.catalog.dashboard import build_dashboard


def test_마켓_계정_상태로_묶여_나온다():
    counts = {'lotteon': {'브랜드위시': {'sale': 44102, 'soldout': 612,
                                     'stopped': 3246}}}
    out = build_dashboard(counts, measured={}, group_counts={})
    m = out['markets'][0]
    assert m['market'] == 'lotteon'
    assert m['total'] == 47960
    a = m['accounts'][0]
    assert a['account_key'] == '브랜드위시'
    assert a['sale'] == 44102
    assert a['total'] == 47960


def test_없는_상태는_0_으로_채운다():
    """화면이 빈칸 대신 0 을 그리게 — 빈칸은 '모름'으로 오해된다."""
    out = build_dashboard({'coupang': {'세소': {'sale': 72}}},
                          measured={}, group_counts={})
    a = out['markets'][0]['accounts'][0]
    assert a['soldout'] == 0
    assert a['stopped'] == 0
    assert a['waiting'] == 0


def test_모르는_상태가_있으면_따로_알려준다():
    """★ unknown 을 숨기면 새 코드가 생긴 걸 아무도 모른다."""
    out = build_dashboard({'lotteon': {'A': {'sale': 5, 'unknown': 3}}},
                          measured={}, group_counts={})
    a = out['markets'][0]['accounts'][0]
    assert a['unknown'] == 3
    assert out['unknown_total'] == 3


def test_확인_시각이_계정마다_붙는다():
    from datetime import datetime, timezone
    t = datetime(2026, 7, 24, 3, 0, tzinfo=timezone.utc)
    out = build_dashboard({'lotteon': {'A': {'sale': 1}}},
                          measured={('lotteon', 'A'): t}, group_counts={})
    assert out['markets'][0]['accounts'][0]['measured_at'] is not None


def test_한_번도_확인_안_한_계정은_시각이_없다():
    """★ 없는 걸 '방금'으로 채우면 낡은 숫자를 최신인 척 보여주게 된다."""
    out = build_dashboard({'lotteon': {'A': {'sale': 1}}},
                          measured={}, group_counts={})
    assert out['markets'][0]['accounts'][0]['measured_at'] is None


def test_전체_합계가_따로_나온다():
    out = build_dashboard(
        {'lotteon': {'A': {'sale': 10, 'soldout': 1}},
         'coupang': {'B': {'sale': 20}}},
        measured={}, group_counts={})
    assert out['summary']['total'] == 31
    assert out['summary']['sale'] == 30
    assert out['summary']['soldout'] == 1


def test_모음전으로_담은_수가_요약에_들어간다():
    out = build_dashboard({'lotteon': {'A': {'sale': 10}}},
                          measured={}, group_counts={'groups': 3, 'linked': 7})
    assert out['summary']['groups'] == 3
    assert out['summary']['linked'] == 7


def test_마켓은_상품이_많은_순으로_나온다():
    out = build_dashboard(
        {'coupang': {'A': {'sale': 20}}, 'lotteon': {'B': {'sale': 100}}},
        measured={}, group_counts={})
    assert [m['market'] for m in out['markets']] == ['lotteon', 'coupang']


def test_계정도_많은_순으로_나온다():
    out = build_dashboard(
        {'lotteon': {'작은계정': {'sale': 5}, '큰계정': {'sale': 500}}},
        measured={}, group_counts={})
    keys = [a['account_key'] for a in out['markets'][0]['accounts']]
    assert keys == ['큰계정', '작은계정']


def test_아무것도_없어도_터지지_않는다():
    """아직 한 번도 안 훑은 상태 — 화면이 빈 표를 그릴 수 있어야 한다."""
    out = build_dashboard({}, measured={}, group_counts={})
    assert out['markets'] == []
    assert out['summary']['total'] == 0
    assert out['unknown_total'] == 0
