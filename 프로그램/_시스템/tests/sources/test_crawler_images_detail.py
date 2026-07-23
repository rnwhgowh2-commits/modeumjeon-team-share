# -*- coding: utf-8 -*-
"""[M4-4] 크롤 결과에 소싱처 상품 이미지 URL·상세페이지가 실려 오는지.

배경 — 6마켓 전부 **대표 이미지가 필수**, 옥션·G마켓·11번가·롯데온 4마켓은
**상세 HTML 도 필수**(`lemouton/registration/compile_more.py`). 그런데 크롤이 둘 다
전혀 안 가져왔다(`CrawlResult` 에 필드 자체가 없었음) → 등록 자체가 막힌다.

★ 지식재산권 — 이미지는 브랜드 저작물이다. 이 단계는 **URL 수집·저장까지**만 하고
  파일을 내려받거나 마켓에 올리지 않는다. 실제 업로드는 브랜드별 지재권 제외 정책을
  통과한 건에 대해서만 이후 단계에서 한다.

★ `_BLOCK_RESOURCE_TYPES`(이미지 다운로드 차단)와는 무관하다 — 그 라우트는 이미지
  *바이트*만 막고 HTML 의 `<img src>` 문자열은 그대로 온다. 우리는 문자열만 읽는다.

fixture 는 `tests/sources/fixtures/<source>_product.html` — **라이브 상품 페이지 원본**
(2026-07-23 캡처, M3 카테고리 작업이 확보한 그 파일 그대로). 지어낸 마크업이 아니다.
"""
import json
import pathlib
from dataclasses import asdict

import pytest

from lemouton.sourcing.crawlers.base import (
    CrawlResult, build_image_urls, sanitize_detail_html,
)

FIX = pathlib.Path(__file__).parent / "fixtures"


def _html(key: str) -> str:
    p = FIX / f"{key}_product.html"
    if not p.exists():
        pytest.skip(f"fixture 없음: {p.name}")
    return p.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# 그릇 (CrawlResult)
# ─────────────────────────────────────────────────────────────
def test_크롤결과에_이미지목록과_상세html_필드가_있고_기본값은_빈값():
    r = CrawlResult(source='musinsa', product_url='https://x', product_name_raw='테스트')
    assert r.image_urls == []
    assert r.detail_html == ''
    d = asdict(r)                       # asdict → JSON → 확장까지 자동 전파되는 경로
    assert 'image_urls' in d and 'detail_html' in d
    json.dumps(d, ensure_ascii=False)   # JSON 직렬화 가능해야 전파된다


def test_크롤결과_이미지목록은_인스턴스마다_독립이다():
    """가변 기본값 공유 사고 방지 — 한 상품 이미지가 다른 상품에 새면 오등록이다."""
    a = CrawlResult(source='s', product_url='u', product_name_raw='n')
    b = CrawlResult(source='s', product_url='u', product_name_raw='n')
    a.image_urls.append('https://x/1.jpg')
    assert b.image_urls == []


# ─────────────────────────────────────────────────────────────
# 공통 조립기 — 이미지 URL
# ─────────────────────────────────────────────────────────────
def test_이미지URL_상대경로는_절대화하고_순서유지_중복제거한다():
    got = build_image_urls(
        ['/web/product/big/a.jpg', '//cdn.x.com/b.png', 'https://x.com/c.jpg',
         '/web/product/big/a.jpg'],
        base_url='https://lemouton.co.kr/product/detail.html?product_no=219')
    assert got == ['https://lemouton.co.kr/web/product/big/a.jpg',
                   'https://cdn.x.com/b.png',
                   'https://x.com/c.jpg']


def test_이미지URL_상품사진이_아닌것은_버린다():
    """아이콘·로고·1px 트래킹 픽셀이 섞이면 그대로 마켓 대표이미지가 된다."""
    got = build_image_urls(
        ['https://x.com/img/icon_new.gif', 'https://x.com/common/logo.png',
         'https://x.com/blank.gif', 'https://x.com/btn_buy.png',
         'https://x.com/noimage.jpg', 'data:image/png;base64,AAA',
         'https://x.com/product/real_photo.jpg'],
        base_url='https://x.com/')
    assert got == ['https://x.com/product/real_photo.jpg']


def test_이미지URL_확장자로_확증안되면_제외한다():
    """HTML 페이지·API 경로를 이미지로 오수집하면 마켓 등록이 통째로 반려된다."""
    assert build_image_urls(['https://x.com/goods/view?no=1'], 'https://x.com/') == []


def test_이미지URL_기준URL_없는_상대경로는_추측하지_않고_버린다():
    assert build_image_urls(['/img/a.jpg']) == []


def test_이미지URL_못쓸값이면_빈리스트이고_예외를_던지지_않는다():
    assert build_image_urls(None) == []
    assert build_image_urls([]) == []
    assert build_image_urls(['', '   ', None]) == []


# ─────────────────────────────────────────────────────────────
# 공통 조립기 — 상세 HTML
# ─────────────────────────────────────────────────────────────
def test_상세HTML_스크립트와_추적태그를_제거한다():
    got = sanitize_detail_html(
        '<div><script>track()</script><p>소재 안내</p>'
        '<iframe src="//ad.x.com/px"></iframe><noscript>x</noscript></div>')
    assert '<script' not in got and 'track()' not in got
    assert '<iframe' not in got and '<noscript' not in got
    assert '소재 안내' in got


def test_상세HTML_이벤트핸들러_속성을_제거한다():
    got = sanitize_detail_html('<div onclick="steal()"><p onmouseover="x()">본문</p></div>')
    assert 'onclick' not in got and 'onmouseover' not in got
    assert '본문' in got


def test_상세HTML_이미지와_링크를_절대URL로_바꾼다():
    """마켓 서버에서 열려야 하므로 상대경로는 그대로 두면 깨진 이미지가 된다."""
    got = sanitize_detail_html(
        '<div><img src="/web/upload/d1.jpg"><a href="/about">안내</a></div>',
        base_url='https://lemouton.co.kr/product/detail.html?product_no=219')
    assert 'https://lemouton.co.kr/web/upload/d1.jpg' in got
    assert 'https://lemouton.co.kr/about' in got


def test_상세HTML_지연로딩_data_src_도_이미지로_살린다():
    got = sanitize_detail_html(
        '<div><img data-src="//cdn.x.com/d2.jpg"></div>', base_url='https://x.com/')
    assert 'https://cdn.x.com/d2.jpg' in got


def test_상세HTML_알맹이가_없으면_빈문자열이다():
    """텍스트도 이미지도 없는 껍데기 = '상세 확인불가'. 빈 div 를 저장하지 않는다."""
    assert sanitize_detail_html('<div class="cont"><script>x()</script></div>') == ''
    assert sanitize_detail_html('') == ''
    assert sanitize_detail_html(None) == ''


# ─────────────────────────────────────────────────────────────
# 소싱처별 실 fixture — 르무통(Cafe24)
# ─────────────────────────────────────────────────────────────
LEMOUTON_URL = ("https://lemouton.co.kr/product/detail.html"
                "?product_no=219&cate_no=64&display_group=1")


def _lemouton():
    from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
    return LemoutonCrawler(prefer_playwright=False).parse_html(_html("lemouton"), LEMOUTON_URL)


def test_르무통_대표이미지는_og_image_이고_첫원소다():
    """실화면 확인(2026-07-23): og:image = `.keyImg img.BigImage` 와 같은 파일."""
    res = _lemouton()
    assert res.image_urls[0] == (
        'https://lemouton.co.kr/web/product/big/202508/'
        '9644b9963f6e0b9882b50d788c40694c.jpg')


def test_르무통_추가이미지까지_절대URL로_모은다():
    """`.xans-product-addimage img` 5장. `//lemouton.co.kr/...` → https 절대화."""
    res = _lemouton()
    assert len(res.image_urls) == 6                     # 대표 1 + 추가 5
    assert all(u.startswith('https://lemouton.co.kr/web/product/') for u in res.image_urls)
    assert len(set(res.image_urls)) == 6                 # 중복 없음


def test_르무통_이미지에_카페24_스킨아이콘이_섞이지_않는다():
    """`.keyImg` 안 확대 아이콘(img.echosting.cafe24.com/…zoom.gif) 오수집 방지."""
    res = _lemouton()
    assert not any('echosting.cafe24.com' in u for u in res.image_urls)
    assert not any(u.endswith('.gif') for u in res.image_urls)


def test_르무통_small_을_big_으로_치환하지_않는다():
    """[추측 금지 핀] 2026-07-23 HEAD 실측 근거.

    ① `/web/product/extra/small/…` 과 `/extra/big/…` 은 같은 파일(둘 다 200,
       content-length 70037 동일) → 치환해도 얻는 게 없다.
    ② `/web/product/small/…b6352ad8….jpg` 를 `/big/` 으로 바꾸면 **404**.
       치환했으면 마켓에 깨진 이미지가 올라갔을 것이다.
    """
    res = _lemouton()
    assert any('/web/product/small/' in u for u in res.image_urls)
    assert any('/web/product/extra/small/' in u for u in res.image_urls)


def test_르무통_상세HTML_은_상품상세영역만_가져온다():
    """`#proDetail div.inner div.cont` — 이미지 18장짜리 이미지형 상세."""
    res = _lemouton()
    assert res.detail_html.startswith('<div class="cont"')
    assert res.detail_html.count('<img') == 18
    assert len(res.detail_html) > 2000


def test_르무통_상세HTML_에_이벤트배너와_스크립트가_없다():
    """`#proDetail` 통째로 쓰면 쇼핑몰 시즌 이벤트 배너(남의 몰 홍보)가 딸려 온다."""
    res = _lemouton()
    assert '<script' not in res.detail_html
    assert 'eventArea' not in res.detail_html
    assert '/event/summer_2026.html' not in res.detail_html
    assert '/web/upload/NNEditor/' not in res.detail_html       # 이벤트 배너 이미지 경로


def test_르무통_상세HTML_지연로딩_이미지가_실주소로_바뀐다():
    """Cafe24 edibot 은 src 에 1px base64 placeholder 를 넣는다 — 그대로면 백지."""
    res = _lemouton()
    assert 'src="data:image' not in res.detail_html
    assert ('src="https://lemouton.co.kr/lemouton/Product/Classic2/260629/'
            'Lemouton_Classic2_01_01.jpg"') in res.detail_html


def test_르무통_상세영역이_없으면_빈문자열이고_예외를_던지지_않는다():
    from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler

    res = LemoutonCrawler(prefer_playwright=False).parse_html(
        "<html><body><h2>이름</h2></body></html>", LEMOUTON_URL)
    assert res.image_urls == []
    assert res.detail_html == ''


# ─────────────────────────────────────────────────────────────
# 리소스 차단 정책 — 이미지 URL 수집과 무관함을 핀으로 박는다
# ─────────────────────────────────────────────────────────────
def test_이미지_리소스차단은_그대로_둔다():
    """`block_heavy_resources` 는 이미지 *바이트* 다운로드만 막는다.

    HTML(document)·JS(script)·API(xhr) 는 통과하므로 `<img src>`·`data-src`·
    JSON-LD·`__PRELOADED_STATE__` 문자열은 그대로 손에 들어온다. 우리는 URL 문자열만
    읽으므로 차단을 풀 이유가 없다(풀면 크롤이 느려질 뿐 얻는 게 없다).
    """
    from lemouton.sourcing.crawlers.base import _BLOCK_RESOURCE_TYPES

    assert 'image' in _BLOCK_RESOURCE_TYPES
    assert 'document' not in _BLOCK_RESOURCE_TYPES
    assert 'script' not in _BLOCK_RESOURCE_TYPES
    assert 'xhr' not in _BLOCK_RESOURCE_TYPES
    assert 'fetch' not in _BLOCK_RESOURCE_TYPES
