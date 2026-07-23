# -*- coding: utf-8 -*-
"""크롤 결과에 소싱처 카테고리 경로가 실려 오는지.

fixture 는 `tests/sources/fixtures/<source>_product.html` — **라이브 상품 페이지 원본**
(2026-07-23 캡처). 지어낸 마크업이 아니다. 각 소싱처 빵부스러기 근거:

  lemouton : `div.xans-product-headcategory ol li a` (Cafe24 '현재 위치')
             — 실화면 확인: 홈 / Men / 클래식 (빈 `li.displaynone` 2개는 자동 제외)
  ssf      : `<script type="application/ld+json">` 의 BreadcrumbList
             (DOM `div.breadcrumb` 도 같은 값 — JSON-LD 를 1순위로 쓴다)
             — 실화면 확인: 홈 / 백＆슈즈 / 여성 슈즈 / 운동화/스니커즈
  ssg      : `div#location.cate_location > div.lo_depth_01 > a.lo_menu`
             (각 `lo_depth_01` 안의 `div.lo_depth_02` 드롭다운은 **형제 카테고리**
              목록이라 경로가 아니다 — 직계 자식 a 만 읽는다)
             — 첫 단계는 사이트 루트 `href="/"` SSG.COM → 제외

'홈'·'Home' 최상위 더미는 제외한다(`base.build_category_path` 주석 참조).
"""
import pathlib
from dataclasses import asdict

import pytest

from lemouton.sourcing.crawlers.base import CrawlResult, build_category_path

FIX = pathlib.Path(__file__).parent / "fixtures"


def _html(key: str) -> str:
    p = FIX / f"{key}_product.html"
    if not p.exists():
        pytest.skip(f"fixture 없음: {p.name}")
    return p.read_text(encoding="utf-8")


def test_크롤결과에_카테고리경로_필드가_있고_기본값은_빈문자열():
    r = CrawlResult(source='musinsa', product_url='https://x', product_name_raw='테스트', options=[])
    assert r.category_path == ''
    assert 'category_path' in asdict(r)      # asdict → JSON → 확장까지 자동 전파되는 경로


# ─────────────────────────────────────────────────────────────
# 공통 경로 조립기
# ─────────────────────────────────────────────────────────────
def test_경로조립_공백정리하고_맨앞_홈더미만_제외한다():
    assert build_category_path([' 신발 ', '\n스니커즈\n']) == '신발>스니커즈'
    assert build_category_path(['홈', 'Men', '클래식']) == 'Men>클래식'
    assert build_category_path(['Home', '백＆슈즈']) == '백＆슈즈'
    # 중간의 '홈'은 실제 카테고리일 수 있으므로 지우지 않는다
    assert build_category_path(['가구', '홈', '데코']) == '가구>홈>데코'
    # 못 쓸 값 → 빈 문자열 (추측 금지)
    assert build_category_path([]) == ''
    assert build_category_path(['', '  ', None]) == ''
    assert build_category_path(['홈']) == ''


# ─────────────────────────────────────────────────────────────
# 소싱처별 실 fixture
# ─────────────────────────────────────────────────────────────
def test_르무통_상품페이지에서_카테고리경로를_뽑는다():
    from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler

    url = ("https://lemouton.co.kr/product/detail.html"
           "?product_no=219&cate_no=64&display_group=1")
    res = LemoutonCrawler(prefer_playwright=False).parse_html(_html("lemouton"), url)
    assert res.category_path == 'Men>클래식'


def test_ssf_상품페이지에서_카테고리경로를_뽑는다():
    from lemouton.sourcing.crawlers.ssf import SsfCrawler

    url = "https://www.ssfshop.com/LEMOUTON/GRG426021974780/good"
    res = SsfCrawler().parse_html(_html("ssf"), url)
    assert res.category_path == '백＆슈즈>여성 슈즈>운동화/스니커즈'


def test_ssg_상품페이지에서_카테고리경로를_뽑는다():
    """SSG 는 ``div#location.cate_location`` 안 `lo_depth_01` 마다 현재 카테고리 1단계.

    fixture 출처가 다른 둘과 다르다 — 2026-07-23 이 세션에서는 SSG 상품 페이지를
    새로 못 받았다(itemView 403 봇차단 + 브라우저 정책 차단). 그래서 저장소에 이미
    있던 **라이브 캡처본**(`tests/sourcing/fixtures/ssg_sample.html`, 가격 테스트가
    쓰는 그 파일)을 그대로 복사해 썼다. 지어낸 마크업이 아니다.
    """
    from lemouton.sourcing.crawlers.ssg import SsgCrawler

    url = ("https://www.ssg.com/item/itemView.ssg"
           "?itemId=1000809938058&siteNo=6009&salestrNo=1004")
    res = SsgCrawler().parse_html(_html("ssg"), url)
    # 'SSG.COM'(사이트 루트) 은 제외, `lo_depth_02` 드롭다운의 형제 카테고리도 미포함
    assert res.category_path == '스포츠웨어/용품>스포츠신발/샌들>워킹화'


def test_빵부스러기가_없으면_빈문자열이고_예외를_던지지_않는다():
    """추출 실패 = '카테고리 확인불가'(빈 문자열). 크롤 자체를 죽이지 않는다."""
    from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler

    res = LemoutonCrawler(prefer_playwright=False).parse_html(
        "<html><body><h2>이름</h2></body></html>",
        "https://lemouton.co.kr/product/detail.html?product_no=1",
    )
    assert res.category_path == ''
