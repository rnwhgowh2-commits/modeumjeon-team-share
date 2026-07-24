# -*- coding: utf-8 -*-
"""마켓 원본 상태코드 → 통일 4상태.

★ 모르는 코드를 '판매중'으로 만들면 안 된다 — 품절인 상품이 판매중으로 보이면
  오버셀(재고 없는데 팔림)이 난다. 모르면 'unknown' 으로 남기고 화면에 그대로 띄운다.
"""
import pytest

from lemouton.catalog.status import unify_status, UNIFIED


def test_통일_상태는_네_가지에_unknown_까지_다섯():
    assert UNIFIED == ('sale', 'soldout', 'stopped', 'waiting', 'unknown')


@pytest.mark.parametrize('market,raw,expect', [
    # 스마트스토어 — 문서 코드 [WAIT, SALE, OUTOFSTOCK, UNADMISSION, REJECTION,
    #                        SUSPENSION, CLOSE, PROHIBITION, DELETE]
    ('smartstore', 'SALE', 'sale'),
    ('smartstore', 'OUTOFSTOCK', 'soldout'),
    ('smartstore', 'SUSPENSION', 'stopped'),
    ('smartstore', 'CLOSE', 'stopped'),
    ('smartstore', 'PROHIBITION', 'stopped'),
    ('smartstore', 'WAIT', 'waiting'),
    ('smartstore', 'UNADMISSION', 'waiting'),
    # 롯데온 — slStatCd [END/SALE/SOUT/STP]
    ('lotteon', 'SALE', 'sale'),
    ('lotteon', 'SOUT', 'soldout'),
    ('lotteon', 'STP', 'stopped'),
    ('lotteon', 'END', 'stopped'),
    # 11번가 — 103=판매중 104=품절 105=전시중지 101=승인대기 102=승인전
    ('eleven11', '103', 'sale'),
    ('eleven11', '104', 'soldout'),
    ('eleven11', '105', 'stopped'),
    ('eleven11', '101', 'waiting'),
    ('eleven11', '102', 'waiting'),
    # ESM — 11=판매중 21=판매중지 22=직권중지 31=SKU품절
    ('auction', '11', 'sale'),
    ('auction', '31', 'soldout'),
    ('auction', '21', 'stopped'),
    ('auction', '22', 'stopped'),
    ('gmarket', '11', 'sale'),
    # 쿠팡 — APPROVED/PARTIAL_APPROVED/SAVED/IN_REVIEW/APPROVING/DENIED/DELETED
    ('coupang', 'APPROVED', 'sale'),
    ('coupang', 'PARTIAL_APPROVED', 'stopped'),
    ('coupang', 'DENIED', 'stopped'),
    ('coupang', 'SAVED', 'waiting'),
    ('coupang', 'IN_REVIEW', 'waiting'),
    ('coupang', 'APPROVING', 'waiting'),
])
def test_마켓별_코드가_통일_상태로(market, raw, expect):
    assert unify_status(market, raw) == expect


def test_모르는_코드는_unknown_이지_판매중이_아니다():
    """★ 여기가 핵심 — 모르는 코드를 sale 로 만들면 오버셀이 난다."""
    assert unify_status('smartstore', 'NEWCODE_2027') == 'unknown'
    assert unify_status('lotteon', 'ZZZ') == 'unknown'
    assert unify_status('coupang', '') == 'unknown'
    assert unify_status('smartstore', None) == 'unknown'


def test_모르는_마켓도_unknown():
    assert unify_status('없는마켓', 'SALE') == 'unknown'


def test_대소문자와_공백은_너그럽게():
    assert unify_status('smartstore', ' sale ') == 'sale'
    assert unify_status('coupang', 'approved') == 'sale'
