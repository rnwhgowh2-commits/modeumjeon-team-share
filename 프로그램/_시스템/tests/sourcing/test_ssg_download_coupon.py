# -*- coding: utf-8 -*-
"""[TEST] SSG 「쿠폰보기」 다운로드 쿠폰 레이어 파서.

■ 무엇을 잠그나
  네이버 경유(`ckwhere=ssg_naver`)로 들어가면 PDP 「쿠폰보기」 레이어에 채널 전용
  제휴쿠폰이 뜬다. 종전 파서(`_parse_product_coupon`)는 `dt`가 "상품쿠폰"인
  `dl.cdtl_cpn_wrap` 블록만 봤고 정규식이 리터럴 「N% 상품쿠폰」을 요구해서
  「[제휴할인] 백화점 8% 쿠폰」을 **한 건도 못 잡았다**
  (docs/소싱처별-정답지-읽는법.md D6 · 지도 §11 SSG).

■ 실측 근거 (픽스처 = 사장님이 저장해 준 실제 PDP, 2026-07-23)
  fixtures/ssg_download_coupon_layer.html
    · itemId=1000806023198 · siteNo=6009 · 즉시할인가(최적가) 71,638원
    · 다운로드 쿠폰 2장 — [제휴할인] 백화점 8% 쿠폰 5,731원 / 백화점 5% 쿠폰 3,581원
    · 검산: 71,638 × 8% = 5,731.04 → 5,731 · 71,638 × 5% = 3,581.9 → 3,581
      → **쿠폰 기준금액 = 즉시할인가(표면노출가)** 임이 두 장 모두에서 맞아떨어진다.

■ 보수 규칙 (사장님 확정 규율 준수)
  · 제휴(경유) 쿠폰이 여러 장이면 **큰 쪽 1장만** — 동시 적용 가능 여부는 주문서에서만
    확정된다(아이몰 P31 교훈: PDP 만 보고 칸을 추론하지 말 것). 1장만 깎으면 틀려도
    매입가 과대 = 안전 방향이다.
  · 「적용 중인 쿠폰」 그룹은 이미 가격에 반영된 것이라 **읽지 않는다**(재차감 금지).
  · 쓱클럽(멤버십) 쿠폰은 제외 — 지도 §11 SSG STEP2 확정.
"""
import io
import os

import pytest
from bs4 import BeautifulSoup

from lemouton.sourcing.crawlers.ssg import (
    _parse_download_coupons,
    _parse_product_coupon,
)

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures',
                       'ssg_download_coupon_layer.html')


@pytest.fixture(scope='module')
def soup():
    html = io.open(FIXTURE, encoding='utf-8').read()
    return BeautifulSoup(html, 'lxml')


def test_기존_상품쿠폰_파서는_이_페이지에서_0건(soup):
    """D6 재현 — 종전 경로로는 제휴쿠폰이 안 잡힌다(이 테스트가 회귀 기준선)."""
    assert _parse_product_coupon(soup) == {}


def test_다운로드_쿠폰_2장을_라벨_요율_금액까지_뽑는다(soup):
    cps = _parse_download_coupons(soup)
    assert len(cps) == 2, cps
    assert cps[0]['label'] == '[제휴할인] 백화점 8% 쿠폰'
    assert cps[0]['rate'] == pytest.approx(0.08)
    assert cps[0]['amount'] == 5731
    assert cps[0]['is_affiliate'] is True
    assert cps[1]['label'] == '[제휴할인] 백화점 5% 쿠폰'
    assert cps[1]['rate'] == pytest.approx(0.05)
    assert cps[1]['amount'] == 3581


def test_실측_검산_금액이_표면가x요율과_일치한다(soup):
    """기준금액 = 즉시할인가(표면노출가) 71,638원 — 두 장 모두 일치."""
    surface = 71638
    for c in _parse_download_coupons(soup):
        assert int(surface * c['rate']) == c['amount'], c


def test_경유쿠폰은_큰_쪽_1장만_고른다(soup):
    from lemouton.sourcing.crawlers.ssg import pick_download_coupon
    picked = pick_download_coupon(_parse_download_coupons(soup))
    assert picked['rate'] == pytest.approx(0.08)
    assert picked['amount'] == 5731


def test_레이어가_없으면_빈_리스트(soup):
    """경유 안 한 PDP·구조 변경 시 조용히 0건 — 추측값 만들지 않는다."""
    assert _parse_download_coupons(BeautifulSoup('<html></html>', 'lxml')) == []


def test_적용중인_쿠폰_그룹은_읽지_않는다():
    """이미 가격에 반영된 쿠폰을 또 깎으면 매입가 과소(마진 착시)."""
    html = '''<div id="store_modal_view_coupon_detail"><div class="dialog_scrollable">
      <div class="dialog_group"><p class="dialog_tit">적용 중인 쿠폰</p>
        <div class="dialog_coupon"><div class="dialog_coupon_detail">
          <span class="dialog_coupon_detail_tit">[제휴할인] 이미적용 9% 쿠폰</span>
          <span class="dialog_coupon_detail_price"><em>9,000</em><span>원</span></span>
        </div></div></div></div></div>'''
    assert _parse_download_coupons(BeautifulSoup(html, 'lxml')) == []


def test_쓱클럽_쿠폰은_제외한다():
    html = '''<div id="store_modal_view_coupon_detail"><div class="dialog_scrollable">
      <div class="dialog_group"><p class="dialog_tit">다운로드 쿠폰</p>
        <div class="dialog_coupon"><div class="dialog_coupon_detail">
          <span class="dialog_coupon_detail_tit">쓱클럽 10% 쿠폰</span>
          <span class="dialog_coupon_detail_price"><em>7,000</em><span>원</span></span>
        </div></div></div></div></div>'''
    assert _parse_download_coupons(BeautifulSoup(html, 'lxml')) == []


def test_파싱결과가_옵션_상품쿠폰_키로_실린다(soup):
    """엔진 계약 — 라벨에 「제휴」가 있으면 api_benefits 가 channel='naver_via' 로
    경유 축에 넣고 OK캐시백과 택1시킨다. 그 입력이 이 키들이다."""
    from lemouton.sourcing.crawlers.ssg import coupon_fields_from_layer
    out = coupon_fields_from_layer(soup)
    assert out['product_coupon_rate'] == pytest.approx(0.08)
    assert '제휴' in out['product_coupon_label']
    assert out.get('product_coupon_min_order', 0) == 0


def test_기존_상품쿠폰이_있으면_레이어로_덮지_않는다():
    """무회귀 — 종전에 잡히던 일반 상품쿠폰은 그대로 둔다."""
    from lemouton.sourcing.crawlers.ssg import merge_coupon_fields
    existing = {'product_coupon_rate': 0.12, 'product_coupon_label': '백화점 12% 상품쿠폰'}
    layer = {'product_coupon_rate': 0.08, 'product_coupon_label': '[제휴할인] 백화점 8% 쿠폰'}
    assert merge_coupon_fields(existing, layer) == existing


def test_기존이_비면_레이어_값을_쓴다():
    from lemouton.sourcing.crawlers.ssg import merge_coupon_fields
    layer = {'product_coupon_rate': 0.08, 'product_coupon_label': '[제휴할인] 백화점 8% 쿠폰'}
    assert merge_coupon_fields({}, layer) == layer
