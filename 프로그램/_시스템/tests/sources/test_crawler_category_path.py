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

  ss_lemouton : `window.__PRELOADED_STATE__` 의
             `simpleProductForDetailPage.A.category.wholeCategoryName`
             (네이버가 '>' 로 이어 주는 완성 경로. DOM 엔 빵부스러기가 없다)
             — 실 페이지 확인: 패션잡화>여성신발>스니커즈/운동화>워킹화
  lotteimall : `div.location` 의 **직계** `a.home` + `div.his > a.one`
             (각 `div.his` 안의 `div.hislayer` 는 **형제 카테고리** 드롭다운이라
              경로가 아니다 — SSG 와 같은 함정. 직계 자식만 읽는다)
             — 실 페이지 확인: 홈 / 패션슈즈 / 스니커즈/운동화 / 런닝화/워킹화
  hmall    : **빵부스러기 없음**(2026-07-23 실측). PDP 는 SSR `__NEXT_DATA__` +
             렌더 DOM 어디에도 카테고리 '이름'이 없고, `itemPtc.itemDScfCd`
             (예: '39040802') 숫자 분류코드만 있다 → 이름 사전이 없으니
             경로로 못 쓴다. **빈 문자열 = 카테고리 확인불가**로 고정한다(추측 금지).

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


def test_스스르무통_상품페이지에서_카테고리경로를_뽑는다():
    """네이버 스마트스토어(브랜드스토어) — inline `__PRELOADED_STATE__` 의 완성 경로.

    fixture 출처 = 2026-07-23 `brand.naver.com/lemouton/products/9496367527` 라이브
    GET 원본(크롤러가 실제로 받는 그 HTML — `smartstore.naver.com` 은 비로그인 GET 시
    로그인 리다이렉트라 크롤러가 brand 호스트로 swap한다). 브라우저 창으로는 확인 못 함
    (naver 도메인이 브라우저 도구 정책상 차단) → 크롤 경로와 동일한 서버 GET 으로 확보.
    """
    from lemouton.sourcing.crawlers.ss_lemouton import SsLemoutonCrawler

    url = "https://smartstore.naver.com/lemouton/products/9496367527"
    res = SsLemoutonCrawler().parse_html(_html("ss_lemouton"), url)
    assert res.category_path == '패션잡화>여성신발>스니커즈/운동화>워킹화'


def test_스스르무통_상태파싱_실패하면_빈문자열():
    """`__PRELOADED_STATE__` 가 없으면 카테고리도 '확인불가'(빈 문자열)."""
    from lemouton.sourcing.crawlers.ss_lemouton import SsLemoutonCrawler

    res = SsLemoutonCrawler().parse_html(
        "<html><body>없음</body></html>",
        "https://brand.naver.com/lemouton/products/1",
    )
    assert res.category_path == ''


def test_롯데아이몰_상품페이지에서_카테고리경로를_뽑는다():
    """롯데아이몰 — `div.location` 직계 자식만(hislayer 드롭다운=형제 카테고리 함정).

    fixture 출처 = 2026-07-23 `www.lotteimall.com/goods/viewGoodsDetail.lotte?
    goods_no=2559329941` 라이브 SSR 원본. 같은 URL 을 실브라우저로도 열어
    화면 빵부스러기가 「홈 패션슈즈 스니커즈/운동화 런닝화/워킹화」임을 대조했다.
    """
    from lemouton.sourcing.crawlers.lotteon import LotteCrawler

    url = "https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559329941"
    res = LotteCrawler().parse_html(_html("lotteimall"), url)
    # 'hislayer' 안의 형제 카테고리(여성브랜드의류·패션잡화 …)가 섞이면 안 된다
    assert res.category_path == '패션슈즈>스니커즈/운동화>런닝화/워킹화'


def test_현대H몰은_빵부스러기가_없어_빈문자열이다():
    """현대H몰 = 카테고리 **확인불가**. 코드만 있고 이름이 없어 경로를 못 만든다.

    fixture 출처 = 2026-07-23 `www.hmall.com/md/pda/itemPtc?slitmCd=2225894478`
    라이브 SSR 원본(크롤러가 파싱하는 그 HTML). 같은 URL 을 실브라우저로 렌더해
    빵부스러기 DOM·JSON-LD·og 메타가 **전부 없음**을 확인했다. `itemPtc.itemDScfCd`
    ('39040802') 는 숫자 분류코드일 뿐 이름 사전이 없다 → 지어내지 않고 빈 문자열.
    """
    from lemouton.sourcing.crawlers.hmall import HmallCrawler

    url = "https://www.hmall.com/md/pda/itemPtc?slitmCd=2225894478"
    res = HmallCrawler().parse_html(_html("hmall"), url)
    assert res.product_name_raw          # 파싱 자체는 정상(상품명은 나온다)
    assert res.category_path == ''       # 카테고리만 확인불가


def test_빵부스러기가_없으면_빈문자열이고_예외를_던지지_않는다():
    """추출 실패 = '카테고리 확인불가'(빈 문자열). 크롤 자체를 죽이지 않는다."""
    from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler

    res = LemoutonCrawler(prefer_playwright=False).parse_html(
        "<html><body><h2>이름</h2></body></html>",
        "https://lemouton.co.kr/product/detail.html?product_no=1",
    )
    assert res.category_path == ''


# ─────────────────────────────────────────────────────────────
# 확장(크롬) 배관 정적 핀 — 여기가 끊기면 수집해도 '조용히 유실'된다
#   무신사·롯데온 2개 소싱처는 추출이 서버가 아니라 확장 background.js 에 있고,
#   확장 결과는 toItemBG 가 실어 보내는 키만 /api/sources/crawl-result 로 간다.
#   ★ category_path 는 BENEFIT_PASSTHROUGH(혜택 화이트리스트)에 넣지 않는다 —
#     그 배열은 서버 OPTION_DYNAMIC_KEYS 와 정적으로 핀돼 있어(⊆ 관계,
#     tests/pricing/test_parse_path_benefit_no_stomp.py) 거기 넣으면
#     dynamic_benefits_json 에도 중복 저장된다(전용 컬럼이 이미 진실 원천).
#     대신 toItemBG 에 명시 필드로 넣고, 그 사실을 여기서 핀 박는다.
# ─────────────────────────────────────────────────────────────
_EXT = pathlib.Path(__file__).resolve().parents[2] / "extension" / "moum-crawler"


def _bg() -> str:
    return (_EXT / "background.js").read_text(encoding="utf-8")


def test_확장_toItemBG_가_카테고리경로를_crawl_result_로_실어보낸다():
    import re

    bg = _bg()
    m = re.search(r"function toItemBG\(x\) \{(.*?)\n\}", bg, re.S)
    assert m, "background.js 에 toItemBG 정의가 없음"
    assert "category_path" in m.group(1), (
        "toItemBG 가 category_path 를 안 보낸다 — 확장이 수집해도 서버에 도달 못 한다")


def test_확장_결과조립_분기_전부에_카테고리경로가_배선돼_있다():
    """same-origin·BG_JS·navGrab+parse·fetchRawParse·fetchMusinsa·fetchHmall 6분기."""
    bg = _bg()
    # 5분기는 파서/추출기 응답에서 꺼내 오고(catPathOf), 무신사 창없이 어댑터만 직접 조립.
    assert bg.count("category_path: catPathOf(") >= 5, "결과 조립 분기 배선 누락"
    assert "category_path: _cat" in bg, "무신사 창없이 어댑터(fetchMusinsaAdapter) 배선 누락"


def test_확장_버전이_manifest_와_background_에서_같다():
    """상습 불일치 이력 — 두 값이 어긋나면 로드 버전 진단이 거짓말을 한다."""
    import json
    import re

    manifest_v = json.loads((_EXT / "manifest.json").read_text(encoding="utf-8"))["version"]
    m = re.search(r'const MOUM_EXT_VERSION = "([\d.]+)"', _bg())
    assert m, "background.js 에 MOUM_EXT_VERSION 상수가 없음"
    assert m.group(1) == manifest_v, f"버전 불일치: background {m.group(1)} vs manifest {manifest_v}"
