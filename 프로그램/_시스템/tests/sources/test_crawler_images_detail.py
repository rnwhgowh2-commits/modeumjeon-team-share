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


def test_상세HTML_이미지는_절대URL로_바꾸고_링크주소는_버린다():
    """이미지 = 마켓 서버에서 열려야 하니 절대화. 링크 = 남의 몰 주소니 폐기.

    ⚠️ [2026-07-23 리뷰지적 C1 로 계약이 바뀐 자리] 종전엔 `a/@href` 도 절대화했다.
       그건 '없던 남의 몰 링크를 작동하는 링크로 만드는' 짓이었다(판매금지 사유).
       아래 `test_상세HTML_링크는_텍스트만_남기고_주소를_버린다` 가 새 계약의 본진.
    """
    got = sanitize_detail_html(
        '<div><img src="/web/upload/d1.jpg"><a href="/about">안내</a></div>',
        base_url='https://lemouton.co.kr/product/detail.html?product_no=219')
    assert 'https://lemouton.co.kr/web/upload/d1.jpg' in got
    assert 'https://lemouton.co.kr/about' not in got and 'href' not in got
    assert '안내' in got


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
    """`.xans-product-addimage img` 5장 중 첫 장은 대표 렌디션이라 뺀다(아래 I6 참조)."""
    res = _lemouton()
    assert len(res.image_urls) == 5                     # 대표 1 + 진짜 추가 4
    assert all(u.startswith('https://lemouton.co.kr/web/product/') for u in res.image_urls)
    assert len(set(res.image_urls)) == 5                 # 중복 없음


def test_르무통_대표사진이_갤러리에_두번_실리지_않는다():
    """🟠 [리뷰지적 I6 · 라이브 실측 4건] 6마켓에서 「대표=A, 추가1=A」가 되던 자리.

    Cafe24 는 업로드한 대표이미지 1장을 `/web/product/{big|medium|small|tiny}/` 로
    복제 저장하는데 **렌디션마다 파일명 해시가 다르다** → URL 문자열 dedup 이 못 잡는다.
    추가이미지는 반대로 항상 `/web/product/extra/…` 아래에 있다.

    실측 근거(2026-07-23, lemouton.co.kr HEAD content-length):
      | 상품 | og:image(=대표)                        | addimage[0]                            | 크기      |
      | 219  | /big/202508/9644b99….jpg               | /small/202508/b6352ad8….jpg            | 81,946 동일 |
      | 140  | /big/202605/2f9c1646….jpg              | /small/202605/55931ab9….jpg            | 146,270 동일 |
      | 233  | /big/202311/b728730e….jpg              | /small/202311/a0d6db75….jpg            | 77,041 동일 |
      | 235  | /big/202508/04d40730….jpg              | /small/202508/a96e237b….jpg            | 65,913 동일 |
    4건 모두 addimage[0] 이 대표와 **바이트 크기까지 같고**, addimage[1..] 은 전부
    `extra/` 이며 서로 다른 크기다 → 규칙이 선다: **`extra/` 없는 렌디션은 대표 1장뿐.**
    """
    res = _lemouton()
    mains = [u for u in res.image_urls if '/web/product/extra/' not in u]
    assert len(mains) == 1, f"대표 렌디션이 여러 장 실렸다: {mains}"
    assert mains[0] == res.image_urls[0], "남는 대표는 첫 원소(=og:image big)여야 한다"
    assert '/web/product/big/' in mains[0]
    # 버려진 건 '대표의 small 판'이지 진짜 추가이미지가 아니다 — 추가 4장은 그대로
    assert sum('/web/product/extra/small/' in u for u in res.image_urls) == 4


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

    ※ ②의 그 `/web/product/small/…` 은 이제 목록에 없다 — **치환해서**가 아니라
      대표이미지의 중복 렌디션이라 뺐기 때문이다(I6). 치환 금지 원칙은 그대로다:
      남아 있는 `extra/small` 을 아무도 `extra/big` 으로 바꾸지 않는다.
    """
    res = _lemouton()
    assert any('/web/product/extra/small/' in u for u in res.image_urls)
    assert not any('/web/product/extra/big/' in u for u in res.image_urls)


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
# 소싱처별 실 fixture — SSF샵
# ─────────────────────────────────────────────────────────────
SSF_URL = "https://www.ssfshop.com/LEMOUTON/GRG426021974780/good"


def _ssf():
    from lemouton.sourcing.crawlers.ssf import SsfCrawler
    return SsfCrawler().parse_html(_html("ssf"), SSF_URL)


def test_ssf_이미지는_JSONLD_Product_image_4장이다():
    """실화면 확인(2026-07-23): JSON-LD `Product.image` = 큰 이미지 뷰어와 같은 값."""
    res = _ssf()
    assert len(res.image_urls) == 4
    assert res.image_urls[0] == (
        'https://img.ssfshop.com/cmd/LB_750x1000/src/https://img.ssfshop.com/goods/'
        'ACSH/26/02/19/GRG426021974780_0_THNAIL_ORGINL_20260219143906884.jpg')
    assert all('LB_750x1000' in u for u in res.image_urls)     # 썸네일(RB_100x133) 아님


def test_ssf_는_깨진_og_image_를_쓰지_않는다():
    """[함정 핀] SSF `meta[og:image]` 실측값 = `https://img.ssfshop.com` (경로 없음).

    이걸 대표 이미지로 썼으면 전 상품이 같은 잘못된 URL 로 등록됐을 것이다.
    """
    import re
    m = re.search(r'og:image[^>]*content="([^"]*)"', _html("ssf"))
    assert m and m.group(1) == 'https://img.ssfshop.com', "fixture 전제 변경 — 재확인 필요"
    assert m.group(1) not in _ssf().image_urls


def test_ssf_상세는_raw_HTML_에서는_빈문자열이다():
    """[정직성 핀] SSF 는 상품정보 탭을 AJAX 로 채운다 — 서버 GET 응답엔 빈 껍데기뿐.

    2026-07-23 실측: raw HTML 에 `godsTabView`·`gods-detail-img`·상세 이미지 호스트
    (`ai.esmplus.com`)가 **하나도 없다**. 창없이(raw fetch) 경로에서는 '상세 확인불가'가
    정상이고 지어내지 않는다. 값이 잡히는 건 확장 navGrab(창 렌더) 경로뿐.
    """
    raw = _html("ssf")
    assert 'godsTabView' not in raw and 'ai.esmplus.com' not in raw
    assert _ssf().detail_html == ''


def test_ssf_렌더DOM_에서는_상세이미지영역을_뽑는다():
    """fixture `ssf_detail_tab.html` = 2026-07-23 라이브 렌더 DOM 의 `#godsTabView` 원본."""
    from bs4 import BeautifulSoup
    from lemouton.sourcing.crawlers.ssf import _parse_detail_html

    p = FIX / "ssf_detail_tab.html"
    if not p.exists():
        pytest.skip("fixture 없음: ssf_detail_tab.html")
    got = _parse_detail_html(BeautifulSoup(p.read_text(encoding="utf-8"), "lxml"), SSF_URL)
    assert got.startswith('<div class="gods-detail-img"')
    assert got.count('<img') == 18
    assert 'https://ai.esmplus.com/oozootech/Lemouton/202606/mate/1.jpg' in got


def test_ssf_상세에_SSF_상품번호와_추천상품이_섞이지_않는다():
    """`#godsDetailInfoTab` 통째로 쓰면 추천상품 36장 + SSF 내부 상품번호가 딸려 온다."""
    from bs4 import BeautifulSoup
    from lemouton.sourcing.crawlers.ssf import _parse_detail_html

    p = FIX / "ssf_detail_tab.html"
    if not p.exists():
        pytest.skip("fixture 없음: ssf_detail_tab.html")
    got = _parse_detail_html(BeautifulSoup(p.read_text(encoding="utf-8"), "lxml"), SSF_URL)
    assert '상품번호' not in got
    assert 'RG4RG4LM-06-IV' not in got
    assert 'gods-detail-desc' not in got


# ─────────────────────────────────────────────────────────────
# 소싱처별 실 fixture — SSG.COM
# ─────────────────────────────────────────────────────────────
SSG_URL = ("https://www.ssg.com/item/itemView.ssg"
           "?itemId=1000809938058&siteNo=6009&salestrNo=1004")


def _ssg():
    from lemouton.sourcing.crawlers.ssg import SsgCrawler
    return SsgCrawler().parse_html(_html("ssg"), SSG_URL)


def test_ssg_이미지는_JSONLD_1200px_8장이고_https가_붙는다():
    """[함정 핀] SSG JSON-LD 는 스킴도 `//` 도 없이 호스트로 시작한다.

    실측 원본: `sitem.ssgcdn.com/58/80/93/item/1000809938058_i1_1200.jpg`.
    그냥 urljoin 하면 `https://www.ssg.com/sitem.ssgcdn.com/…` 라는 없는 주소가 된다.
    """
    res = _ssg()
    assert len(res.image_urls) == 8
    assert res.image_urls[0] == (
        'https://sitem.ssgcdn.com/58/80/93/item/1000809938058_i1_1200.jpg')
    assert all(u.startswith('https://sitem.ssgcdn.com/') for u in res.image_urls)
    assert not any('www.ssg.com/sitem' in u for u in res.image_urls)


def test_ssg_는_250px_og_image_가_아니라_1200px_를_쓴다():
    """og:image 는 같은 파일의 250px 판 — 마켓 대표이미지로 쓰기엔 작다."""
    res = _ssg()
    assert all('_1200.jpg' in u for u in res.image_urls)
    assert not any('_250.jpg' in u for u in res.image_urls)


def test_ssg_상세는_교차출처_iframe_이라_빈문자열이다():
    """[정직성 핀] SSG 상세는 페이지 안이 아니라 `itemdesc.ssg.com` iframe 안에 있다.

    2026-07-23 실측: `div#item_detail .cdtl_capture_img > iframe#_ifr_html` 의 src 가
    `https://itemdesc.ssg.com/item/iframePItemDtlDesc.ssg?itemId=…&dispSiteNo=…`.
    교차출처라 페이지 HTML 에도, 렌더 DOM outerHTML 에도 내용이 없다 → 별도 GET 필요.
    그 GET 은 네트워크 호출이라 순수 파서가 할 일이 아니고, '크롤은 로컬 PC' 원칙상
    서버 parse 엔드포인트에서 부르면 안 된다 → 다음 단계. 그때까지 '확인불가'.
    """
    raw = _html("ssg")
    assert 'itemdesc.ssg.com/item/iframePItemDtlDesc.ssg' in raw   # iframe 은 있다
    assert _ssg().detail_html == ''                                # 내용은 없다


def test_ssg_이미지_기존_카테고리_추출을_깨지_않는다():
    """같은 fixture 로 M3 카테고리도 그대로 나와야 한다(회귀 핀)."""
    assert _ssg().category_path == '스포츠웨어/용품>스포츠신발/샌들>워킹화'


# ─────────────────────────────────────────────────────────────
# 소싱처별 실 fixture — 현대H몰
# ─────────────────────────────────────────────────────────────
HMALL_URL = "https://www.hmall.com/md/pda/itemPtc?slitmCd=2225894478"


def _hmall():
    from lemouton.sourcing.crawlers.hmall import HmallCrawler
    return HmallCrawler().parse_html(_html("hmall"), HMALL_URL)


def test_현대H몰_HTML_에는_상품사진이_한장도_없다():
    """[전제 핀] PDP 원문은 13KB 스켈레톤 — `<img>` 0개, `og:image` 도 없다.

    그래서 다른 소싱처처럼 DOM·JSON-LD 에서 주소를 '읽을' 수가 없고,
    `__NEXT_DATA__` 의 **파일명 + CDN 버킷 규칙**으로 조립해야 한다(아래 테스트).
    """
    raw = _html("hmall")
    assert '<img' not in raw
    assert 'og:image' not in raw


def test_현대H몰_대표이미지는_orglImgNm_과_버킷규칙으로_만든다():
    """[조립 근거 — 추측 아님] 2026-07-23 실측.

    · 라이브 검색결과에서 (상품코드, 실제 버킷경로) **31쌍** 전수 대조 → 31/31 일치
      (예: 2225894478→4/4/89/25 · 2252190243→2/0/19/52 · 2106896831→8/6/89/06)
    · 조립 주소 HEAD 3건 전부 `200 image/jpeg`
      (547,988B / 126,379B / 66,370B), 없는 번호 `_9.jpg` 는 **404**
    """
    res = _hmall()
    assert res.image_urls == [
        'https://image.hmall.com/static/4/4/89/25/2225894478_0.jpg']


def test_현대H몰_버킷규칙_자리자르기():
    from lemouton.sourcing.crawlers.hmall import _hmall_static_bucket

    for cd, want in (('2225894478', '4/4/89/25'), ('2252190243', '2/0/19/52'),
                     ('2152675299', '2/5/67/52'), ('2211800665', '6/0/80/11'),
                     ('2106896831', '8/6/89/06'), ('2247414654', '6/4/41/47')):
        assert _hmall_static_bucket(cd) == want, cd
    # 숫자가 아니거나 너무 짧으면 조립하지 않는다(엉뚱한 주소 금지)
    assert _hmall_static_bucket('') == ''
    assert _hmall_static_bucket('abc') == ''
    assert _hmall_static_bucket('12345') == ''


def test_현대H몰_표준이름이_아니면_주소를_조립하지_않는다():
    """버킷 규칙은 **상품코드 기준**이라, 파일명이 상품코드로 시작하지 않으면
    같은 버킷에 있다고 확신할 수 없다 → 지어내지 않고 버린다."""
    from lemouton.sourcing.crawlers.hmall import _parse_image_urls

    assert _parse_image_urls({'orglImgNm': 'promo_banner.jpg'},
                             '2225894478', HMALL_URL) == []
    assert _parse_image_urls({'orglImgNm': '../../etc/x.jpg'},
                             '2225894478', HMALL_URL) == []
    assert _parse_image_urls({}, '2225894478', HMALL_URL) == []


def test_현대H몰_확대컷이_있으면_같이_담고_중복은_한번만():
    """`orglImgNm` 과 `itemBaseImgNm` 은 실측상 같은 파일이라 한 장으로 합쳐진다."""
    from lemouton.sourcing.crawlers.hmall import _parse_image_urls

    got = _parse_image_urls(
        {'orglImgNm': '2225894478_0.jpg', 'itemBaseImgNm': '2225894478_0.jpg',
         'enlg1ImgNm': '2225894478_1.jpg'}, '2225894478', HMALL_URL)
    assert got == ['https://image.hmall.com/static/4/4/89/25/2225894478_0.jpg',
                   'https://image.hmall.com/static/4/4/89/25/2225894478_1.jpg']


def test_현대H몰_상세는_HTML_에서는_빈문자열이다():
    """[정직성 핀] 상세는 페이지가 아니라 `item-dtl` API 에만 있다 — 파서는 지어내지 않는다."""
    assert _hmall().detail_html == ''


def test_현대H몰_상세는_item_dtl_응답에서_뽑는다():
    """fixture `hmall_item_dtl.json` = 2026-07-23 라이브 API 응답에서 우리가 쓰는 노드만
    남긴 것(값은 원문 그대로). 셀러 상세 이미지 18장."""
    import json as _json
    from lemouton.sourcing.crawlers.hmall import detail_html_from_item_dtl

    p = FIX / "hmall_item_dtl.json"
    if not p.exists():
        pytest.skip("fixture 없음: hmall_item_dtl.json")
    got = detail_html_from_item_dtl(_json.loads(p.read_text(encoding="utf-8")), HMALL_URL)
    assert got.count('<img') == 18
    assert 'https://ai.esmplus.com/oozootech/Lemouton/202606/mate/1.jpg' in got


def test_현대H몰_상세는_화면DOM_이_아니라_API_원문을_쓴다():
    """🟠 [함정 핀] 화면(`#smItemDetailInfoWrap`)을 긁으면 안 된다.

    실측(2026-07-23 라이브 DOM): 지연로딩이 걸려 있어 46장 중 **45장의 `src` 가
    `image.hmall.com/hmall/pd/no_image_600x600.jpg`(회색 판)** 이고 실주소는
    `data-src="//ca2.hyundaihmall.com/S/…"` 로 숨어 있다. API 원문에는 실주소가 그대로다.
    """
    import json as _json
    from lemouton.sourcing.crawlers.hmall import detail_html_from_item_dtl

    p = FIX / "hmall_item_dtl.json"
    if not p.exists():
        pytest.skip("fixture 없음: hmall_item_dtl.json")
    got = detail_html_from_item_dtl(_json.loads(p.read_text(encoding="utf-8")), HMALL_URL)
    assert 'no_image_600x600' not in got
    assert got.count('ai.esmplus.com') == 18


def test_현대H몰_상세응답이_못쓸값이면_빈문자열이고_예외를_던지지_않는다():
    from lemouton.sourcing.crawlers.hmall import detail_html_from_item_dtl

    assert detail_html_from_item_dtl(None, HMALL_URL) == ''
    assert detail_html_from_item_dtl({}, HMALL_URL) == ''
    assert detail_html_from_item_dtl({'respData': {'itemPtc': {}}}, HMALL_URL) == ''
    assert detail_html_from_item_dtl(
        {'respData': {'itemPtc': {'htmlItstCntnList': []}}}, HMALL_URL) == ''


def test_현대H몰_상세수집_실패해도_크롤전체를_죽이지_않는다(monkeypatch):
    """네트워크·WAF 실패는 '상세 확인불가'로 끝나야 한다(예외 전파 금지)."""
    from lemouton.sourcing.crawlers import hmall as _h

    def _boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(_h.requests, "get", _boom)
    assert _h.fetch_detail_html(HMALL_URL) == ''


# ─────────────────────────────────────────────────────────────
# 소싱처별 실 fixture — 롯데아이몰
# ─────────────────────────────────────────────────────────────
IMALL_URL = "https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559329941"


def _imall():
    from lemouton.sourcing.crawlers.lotteon import LotteCrawler
    return LotteCrawler().parse_html(_html("lotteimall"), IMALL_URL)


def test_아이몰_대표이미지는_thumb_product_의_큰이미지다():
    """실화면 확인(2026-07-23): `div.thumb_product img` = 화면 큰 이미지 `_L` 판."""
    res = _imall()
    assert res.image_urls[0] == (
        'https://image2.lotteimall.com/goods/41/99/32/2559329941_L.jpg')


def test_아이몰_사진이_한장이면_썸네일이_대표를_두번_실리게_하지_않는다():
    """🟠 [르무통 I6 형 함정] 이 상품은 사진이 1장뿐이다.

    썸네일 줄엔 같은 사진의 `_S` 판이 하나 있어, `_S→_L` 로 올리면 대표와 **같은 URL**
    이 되어 dedup 에 걸린다 → 최종 1장. `og:image`(`_H` 판)를 섞어 썼다면 같은 사진이
    렌디션만 달리해 두 번 실렸을 것이라 일부러 안 쓴다.
    """
    res = _imall()
    assert res.image_urls == [
        'https://image2.lotteimall.com/goods/41/99/32/2559329941_L.jpg']
    assert not any('_H' in u or '_S' in u for u in res.image_urls)


def test_아이몰_이미지에_롯데_기획전배너와_추천상품이_섞이지_않는다():
    """페이지 전체 `img` 를 긁으면 남의 몰 배너가 대표이미지가 된다 — 좁힌 근거 핀."""
    raw = _html("lotteimall")
    assert '/upload/corner/' in raw and '/upload/event/detail/' in raw   # fixture 전제
    res = _imall()
    assert not any('/upload/corner/' in u for u in res.image_urls)
    assert not any('/upload/event/' in u for u in res.image_urls)
    assert not any('imall_ec/site/images' in u for u in res.image_urls)   # 스킨 자산


def test_아이몰_썸네일여러장은_큰이미지로_올려_전부_모은다():
    """fixture `lotteimall_gallery_multi.html` = 사진 8장짜리 상품(2474798679)의
    `div.division_product_top` 실캡처(2026-07-23).

    [치환 근거 — 추측 아님] HEAD 실측(2026-07-23, 상품 5건·썸네일 17장 전수):
      · 썸네일이 있는 번호는 `_L{n}` 도 **전부 200**(17/17, 실패 0)
      · 없는 번호는 200 이 아니라 **307**(`2474798679_L20.jpg`)
      · 크기 `_S`=6,845B < `_H`=27,331B < `_L`=67,446B → 마켓용은 `_L`
    """
    from bs4 import BeautifulSoup
    from lemouton.sourcing.crawlers.lotteon import _parse_image_urls

    p = FIX / "lotteimall_gallery_multi.html"
    if not p.exists():
        pytest.skip("fixture 없음: lotteimall_gallery_multi.html")
    got = _parse_image_urls(BeautifulSoup(p.read_text(encoding="utf-8"), "lxml"),
                            "https://www.lotteimall.com/goods/viewGoodsDetail.lotte"
                            "?goods_no=2474798679")
    base = 'https://image2.lotteimall.com/goods/79/86/79/2474798679_L'
    assert got == [base + '.jpg'] + [f'{base}{i}.jpg' for i in range(1, 8)]
    assert len(got) == 8 and len(set(got)) == 8


def test_아이몰_이미지없음_회색판은_대표이미지로_쓰지_않는다():
    """`onerror` 로 갈아끼우는 `/goods/common/no_550.gif` 가 src 로 들어와도 버린다."""
    from bs4 import BeautifulSoup
    from lemouton.sourcing.crawlers.lotteon import _parse_image_urls

    soup = BeautifulSoup(
        '<div class="thumb_product"><a>'
        '<img src="https://image2.lotteimall.com/goods/common/no_550.gif"></a></div>'
        '<div class="list_thumb"><ul><li><a>'
        '<img src="https://image2.lotteimall.com/goods/41/99/32/2559329941_S.jpg">'
        '</a></li></ul></div>', "lxml")
    assert _parse_image_urls(soup, IMALL_URL) == [
        'https://image2.lotteimall.com/goods/41/99/32/2559329941_L.jpg']


def test_아이몰_상세는_셀러_상세영역만_가져온다():
    """`#speedycat_container_root` — 셀러 상세 원문(이미지 46장)."""
    res = _imall()
    assert res.detail_html.startswith('<div class="speedycat_container_root_class"')
    assert res.detail_html.count('<img') == 46
    assert 'https://ai.esmplus.com/oozootech/Lemouton/1200/notis_all.png' in res.detail_html


def test_아이몰_상세에_롯데_오늘의방송_배너가_섞이지_않는다():
    """`div.detail` 통째로 쓰면 롯데 자체 배너(`tdy_snd_banner`)가 딸려 온다."""
    raw = _html("lotteimall")
    assert 'tdy_snd_banner' in raw and 'img_banner_tdy_snd2.jpg' in raw   # fixture 전제
    res = _imall()
    assert 'tdy_snd_banner' not in res.detail_html
    assert 'img_banner_tdy_snd2.jpg' not in res.detail_html


def test_아이몰_상세_지연로딩_이미지가_실주소로_바뀐다():
    """speedycat 은 src 에 2×2 base64 placeholder 를 넣는다 — 그대로면 상세가 백지."""
    res = _imall()
    assert 'src="data:image' not in res.detail_html
    assert ('https://ca.lotteimall.com/S/ai.esmplus.com/oozootech/Lemouton/'
            '202606/buddy/1.jpg') in res.detail_html


def test_아이몰_이미지_기존_카테고리_추출을_깨지_않는다():
    assert _imall().category_path == '패션슈즈>스니커즈/운동화>런닝화/워킹화'


def test_아이몰_상세영역이_없으면_빈값이고_예외를_던지지_않는다():
    from bs4 import BeautifulSoup
    from lemouton.sourcing.crawlers.lotteon import _parse_detail_html, _parse_image_urls

    soup = BeautifulSoup("<html><body><h2>이름</h2></body></html>", "lxml")
    assert _parse_detail_html(soup, IMALL_URL) == ''
    assert _parse_image_urls(soup, IMALL_URL) == []


# ─────────────────────────────────────────────────────────────
# 소싱처별 실 fixture — 스마트스토어(브랜드스토어) 르무통
# ─────────────────────────────────────────────────────────────
SSL_URL = "https://brand.naver.com/lemouton/products/9496367527"


def _ss_lemouton(html=None):
    from lemouton.sourcing.crawlers.ss_lemouton import SsLemoutonCrawler
    return SsLemoutonCrawler().parse_html(html or _html("ss_lemouton"), SSL_URL)


def test_스스_이미지는_PRELOADED_STATE_대표1_추가4_다섯장이다():
    """실측(2026-07-23): `simpleProductForDetailPage.A` 의
    `representativeImageUrl`(대표) + `optionalImageUrls`(추가 4) = 화면 썸네일 줄과 일치.
    """
    res = _ss_lemouton()
    assert len(res.image_urls) == 5
    assert res.image_urls[0] == (
        'https://shop-phinf.pstatic.net/20260305_183/17726779000547tFJU_JPEG/'
        '9331130196567760_2025701372.jpg')
    assert all(u.startswith('https://shop-phinf.pstatic.net/') for u in res.image_urls)


def test_스스_대표사진이_추가목록에_두번_실리지_않는다():
    """[르무통 I6 형 함정 점검] 5장이 서로 다른 파일인지 — 2026-07-23 HEAD 실측 근거.

    content-length 237,542 / 658,623 / 768,133 / 687,416 / 482,191 로 전부 다르다
    (같은 사진의 렌디션 복제가 아니다). URL 도 업로드 ID 가 전부 달라 중복이 없다.
    """
    res = _ss_lemouton()
    assert len(set(res.image_urls)) == 5


def test_스스_상세는_raw_HTML_에서는_빈문자열이다():
    """[정직성 핀] 비로그인 GET 응답엔 상세 본문이 없다 — 지어내지 않는다.

    실측(2026-07-23): raw HTML 의 `__PRELOADED_STATE__` 는
    `detailContents:{"editorType":"SEONE"}` 만 주고 본문(`detailContentText`)이 없다.
    본문 API(`/n/v2/channels/{uid}/products/{id}`)는 비브라우저에서 **429 WAF**.
    """
    raw = _html("ss_lemouton")
    assert 'se-main-container' not in raw
    assert '"detailContents":{"editorType":"SEONE"}' in raw
    assert _ss_lemouton().detail_html == ''


def _ss_detail_fixture() -> str:
    p = FIX / "ss_lemouton_detail_tab.html"
    if not p.exists():
        pytest.skip("fixture 없음: ss_lemouton_detail_tab.html")
    return p.read_text(encoding="utf-8")


def test_스스_렌더DOM_에서는_상세본문을_뽑는다():
    """fixture = 2026-07-23 실 Chrome 렌더 DOM 원본(스크롤 없이 3초 대기 = navGrab 과 동일).

    라이브 수집 경로가 확장 navGrab(창 렌더)이라 서버 parse 는 이 DOM 을 받는다.
    """
    from lemouton.sourcing.crawlers.ss_lemouton import _parse_detail_html

    got = _parse_detail_html(_ss_detail_fixture(), SSL_URL)
    assert got.startswith('<div class="se-main-container"')
    # DOM 엔 16장, 남는 건 14장 — 아래 추적픽셀 2장은 공통 관문이 걷어낸다(다음 테스트).
    assert got.count('<img') == 14
    assert ('https://shop-phinf.pstatic.net/20260629_31/1782709103042BvPHk_JPEG/'
            'Lemouton_Classic2_01.jpg') in got


def test_스스_상세에_스토어_공지사항이_섞이지_않는다():
    """같은 영역에 스토어 **공지사항 프레임**(타 상품 홍보 배너·링크)이 형제로 붙어 있다.

    실측(2026-07-23): `div.goodsinfo_frame_basic_wrap` 안 공지 배너 3장
    (`proxy-smartstore.naver.net/img/…`·`sell.smartstore.naver.com/shop1.phinf…`).
    통째로 긁으면 그게 마켓 상세로 나간다 → 컨테이너를 상세 본문으로 좁힌 근거 핀.
    """
    from lemouton.sourcing.crawlers.ss_lemouton import _parse_detail_html

    raw = _ss_detail_fixture()
    assert 'goodsinfo_frame_basic_wrap' in raw and 'proxy-smartstore.naver.net' in raw
    got = _parse_detail_html(raw, SSL_URL)
    assert 'goodsinfo_frame_basic_wrap' not in got
    assert 'proxy-smartstore.naver.net' not in got
    assert 'sell.smartstore.naver.com' not in got


def test_스스_상세에_bitly_추적픽셀이_섞이지_않는다():
    """🔴 실측 발견(2026-07-23) — 셀러가 상세 본문 안에 **1×1 비콘**을 심어 놨다.

    fixture DOM 원본::

        <a class="se-module-image-link"><img class="se-image-resource" width="1" height="1"
           data-src="https://proxy-smartstore.naver.net/img/Yml0Lmx5LzNFQU1kY3E=?token=…"></a>

    base64 를 풀면 ``bit.ly/3EAMdcq`` — 네이버가 프록시해 주는 **단축 URL 이미지**다.
    직접 받아 보면 ``200 text/plain · 0 bytes``(2026-07-23 실측) = 그림이 아니라 비콘.
    그대로 두면 **우리 마켓 상세가 열릴 때마다 소싱처로 방문 신호**가 날아간다.
    공통 관문(`_is_tracking_or_non_product_img` 의 1×1 규칙)이 잡아 준다 — 그 핀.
    """
    from lemouton.sourcing.crawlers.ss_lemouton import _parse_detail_html

    raw = _ss_detail_fixture()
    assert raw.count('proxy-smartstore.naver.net/img/Yml0Lmx5LzNFQU1kY3E=') == 2
    got = _parse_detail_html(raw, SSL_URL)
    assert 'Yml0Lmx5' not in got and 'proxy-smartstore' not in got


def test_스스_상세에_동영상플레이어_마크업이_섞이지_않는다():
    """형제로 붙은 네이버 동영상 플레이어(82KB) — 상품 상세가 아니다."""
    from lemouton.sourcing.crawlers.ss_lemouton import _parse_detail_html

    got = _parse_detail_html(_ss_detail_fixture(), SSL_URL)
    assert '<video' not in got and 'pzp-pc' not in got


def test_스스_지연로딩_상세이미지는_실주소로_바뀐다():
    """SE ONE 은 `src` 에 1×1 base64 placeholder 를 넣는다 — 그대로면 마켓 상세가 백지."""
    from lemouton.sourcing.crawlers.ss_lemouton import _parse_detail_html

    got = _parse_detail_html(_ss_detail_fixture(), SSL_URL)
    assert 'src="data:image' not in got


def test_스스_상태파싱_실패하면_이미지도_상세도_빈값이다():
    res = _ss_lemouton("<html><body><h2>이름</h2></body></html>")
    assert res.image_urls == []
    assert res.detail_html == ''


def test_스스_이미지_기존_카테고리_추출을_깨지_않는다():
    assert _ss_lemouton().category_path == '패션잡화>여성신발>스니커즈/운동화>워킹화'


# ─────────────────────────────────────────────────────────────
# 공통 조립기 — 스킴 없는 호스트 시작 주소(SSG 형태)
# ─────────────────────────────────────────────────────────────
def test_이미지URL_스킴없는_호스트시작은_https를_붙인다():
    got = build_image_urls(['sitem.ssgcdn.com/58/80/93/item/x_i1_1200.jpg'],
                           base_url='https://www.ssg.com/item/itemView.ssg?itemId=1')
    assert got == ['https://sitem.ssgcdn.com/58/80/93/item/x_i1_1200.jpg']


def test_이미지URL_평범한_상대경로는_호스트로_오인하지_않는다():
    """`photo.jpg/…`·`img/a.jpg` 는 호스트가 아니다 — base_url 기준으로 붙여야 한다."""
    base = 'https://shop.example.com/product/1'
    assert build_image_urls(['img/a.jpg'], base) == ['https://shop.example.com/product/img/a.jpg']
    assert build_image_urls(['photo.jpg/b.jpg'], base) == [
        'https://shop.example.com/product/photo.jpg/b.jpg']


# ─────────────────────────────────────────────────────────────
# 리소스 차단 정책 — 이미지 URL 수집과 무관함을 핀으로 박는다
# ─────────────────────────────────────────────────────────────
def test_이미지는_abort_가_아니라_1x1_GIF_로_응답한다():
    """🔴 [실측 사고] 이미지를 `abort` 하면 이미지 URL 수집이 **망가진다**.

    2026-07-23 Playwright 실측(르무통 상품 219): 이미지 요청을 abort 하면
    Cafe24 인라인 `onerror="this.src='…'"` 가 돌아 상품 사진 src 가 전부
    `img.echosting.cafe24.com/thumb/img_product_big.gif` 회색 플레이스홀더로 바뀐다
    (대표 1 + 추가 5 = 6장 전부 오염). SSG 썸네일도 같은 onerror 패턴이다.

    → 이미지는 abort 대신 1×1 투명 GIF 로 fulfill 한다. 요청이 '성공'으로 끝나
      onerror 가 안 돌고 src 원본이 보존된다. 전송량은 여전히 0(로컬에서 43바이트
      돌려줄 뿐)이라 속도 이점은 그대로. 실측 재확인: fulfill 로 바꾼 뒤 Playwright
      경로가 정적 파서와 **똑같은 6장**을 뽑는다.

    ※ meta[og:image]·JSON-LD·`ec-data-src` 는 이미지 요청이 아니라 애초에 영향 없다.
    """
    from lemouton.sourcing.crawlers.base import (
        _BLOCK_RESOURCE_TYPES, _STUB_RESOURCE_TYPES, _STUB_GIF,
    )

    assert 'image' in _STUB_RESOURCE_TYPES, "이미지를 abort 하면 src 가 오염된다"
    assert 'media' in _BLOCK_RESOURCE_TYPES and 'font' in _BLOCK_RESOURCE_TYPES
    # 데이터 경로는 절대 안 막는다
    for t in ('document', 'script', 'xhr', 'fetch', 'stylesheet'):
        assert t not in _BLOCK_RESOURCE_TYPES and t not in _STUB_RESOURCE_TYPES
    assert _STUB_GIF.startswith(b'GIF89a') and len(_STUB_GIF) < 100


def test_라우트가_이미지는_fulfill_동영상은_abort_한다():
    """`block_heavy_resources` 가 실제로 그렇게 부르는지 — 가짜 route 로 확인."""
    from lemouton.sourcing.crawlers.base import block_heavy_resources

    calls = []

    class _Req:
        def __init__(self, t): self.resource_type = t

    class _Route:
        def __init__(self, t): self.request = _Req(t)
        def fulfill(self, **kw): calls.append(('fulfill', self.request.resource_type, kw))
        def abort(self): calls.append(('abort', self.request.resource_type, None))
        def continue_(self): calls.append(('continue', self.request.resource_type, None))

    class _Page:
        def route(self, pattern, handler): self.handler = handler

    page = _Page()
    assert block_heavy_resources(page) is True
    for t in ('image', 'media', 'font', 'document', 'script', 'xhr'):
        page.handler(_Route(t))

    kinds = {t: k for k, t, _ in calls}
    assert kinds['image'] == 'fulfill'
    assert kinds['media'] == 'abort' and kinds['font'] == 'abort'
    assert kinds['document'] == 'continue' and kinds['script'] == 'continue'
    assert kinds['xhr'] == 'continue'
    img_kw = next(kw for k, t, kw in calls if t == 'image')
    assert img_kw['status'] == 200 and img_kw['content_type'] == 'image/gif'


def test_카페24_스킨호스트_이미지는_수집에서_배제된다():
    """abort 사고의 잔재가 어떤 경로로든 새 나와도 마켓 대표이미지가 되면 안 된다."""
    got = build_image_urls(
        ['https://img.echosting.cafe24.com/thumb/img_product_big.gif',
         'https://lemouton.co.kr/web/product/big/202508/real.jpg'],
        base_url='https://lemouton.co.kr/')
    assert got == ['https://lemouton.co.kr/web/product/big/202508/real.jpg']


# ═════════════════════════════════════════════════════════════════
# [2026-07-23 리뷰지적 수정] 상세 HTML 안전판 — 마켓에 그대로 실리는 값이다
# ═════════════════════════════════════════════════════════════════
# 상세 HTML 은 옥션·G마켓·11번가·롯데온 상세설명으로 **그대로** 올라간다
# (`registration/compile_more.py` · `compile_coupang.py` 는 검사 없이 spec 에 넣는다).
# 즉 `sanitize_detail_html` 이 **유일한 관문**이다. 여기서 새면 곧바로
# 「타 쇼핑몰 링크 게시」(판매금지·계정 제재) 또는 「소싱처로 비콘 전송」이 된다.


# ── C1. 남의 몰 링크 ────────────────────────────────────────────
def test_상세HTML_링크는_텍스트만_남기고_주소를_버린다():
    """🔴 상대 href 를 절대화하면 **작동하는 남의 몰 링크**가 새로 생긴다.

    실측(2026-07-23): `<a href="/product/list.html?cate_no=64">다른 상품 보러가기</a>`
    → `https://lemouton.co.kr/product/list.html?cate_no=64` 로 절대화됐다.
    마켓 상세에 타 쇼핑몰 링크를 심으면 **판매금지·계정 제재** 사유다.
    → `a` 는 통째로 지우지 않고 **unwrap**(글은 남기고 주소만 폐기)한다.
      상세 본문 설명 글이 링크 안에 들어 있는 경우가 있어 텍스트는 살려야 한다.
    """
    got = sanitize_detail_html(
        '<div><p>소재 안내</p>'
        '<a href="/product/list.html?cate_no=64">다른 상품 보러가기</a>'
        '<a href="https://lemouton.co.kr/event/summer.html">여름세일</a></div>',
        base_url='https://lemouton.co.kr/product/detail.html?product_no=219')
    assert '<a' not in got and 'href' not in got
    assert 'lemouton.co.kr/product/list.html' not in got
    assert 'lemouton.co.kr/event/summer.html' not in got
    assert '다른 상품 보러가기' in got and '여름세일' in got   # 글은 보존
    assert '소재 안내' in got


def test_상세HTML_이미지를_감싼_링크도_주소만_버리고_이미지는_살린다():
    """이미지형 상세는 `<a href=몰링크><img 상품사진></a>` 가 흔하다 — 사진은 살려야 한다."""
    got = sanitize_detail_html(
        '<div><a href="/product/detail.html?product_no=1">'
        '<img src="/web/upload/d1.jpg"></a></div>',
        base_url='https://lemouton.co.kr/')
    assert 'href' not in got
    assert 'https://lemouton.co.kr/web/upload/d1.jpg' in got


# ── C2. 추적픽셀·비상품 이미지 ──────────────────────────────────
def test_상세HTML_추적픽셀은_제거한다():
    """🔴 우리 마켓 상세가 열릴 때마다 소싱처로 비콘이 날아간다(방문자 유출).

    실측: `<img src="//log.ssfshop.com/px.gif?pid=123" width="1" height="1">` 통과.
    """
    got = sanitize_detail_html(
        '<div><p>소재</p><img src="//log.ssfshop.com/px.gif?pid=123" width="1" height="1">'
        '<img src="https://x.com/product/real.jpg"></div>',
        base_url='https://www.ssfshop.com/')
    assert 'px.gif' not in got and 'log.ssfshop.com' not in got
    assert 'https://x.com/product/real.jpg' in got


def test_상세HTML_비상품_이미지는_수집기와_같은_필터로_거른다():
    """`build_image_urls` 에만 있던 hint/host 필터를 상세에도 똑같이 적용한다."""
    got = sanitize_detail_html(
        '<div><p>소재</p>'
        '<img src="https://img.echosting.cafe24.com/thumb/img_product_big.gif">'
        '<img src="https://x.com/common/blank.gif">'
        '<img src="https://x.com/img/icon_new.gif">'
        '<img src="https://x.com/detail/photo1.jpg"></div>',
        base_url='https://x.com/')
    assert 'echosting.cafe24.com' not in got
    assert 'blank.gif' not in got and 'icon_new.gif' not in got
    assert 'https://x.com/detail/photo1.jpg' in got


def test_상세HTML_1x1_크기표기_이미지는_제거한다():
    """확장자·경로가 멀쩡해도 1×1 은 상품 사진이 아니다(추적픽셀 위장)."""
    got = sanitize_detail_html(
        '<div><p>소재</p><img src="https://t.example.com/beacon.jpg" width="1" height="1">'
        '<img src="https://x.com/detail/photo1.jpg" width="860" height="1200"></div>')
    assert 'beacon.jpg' not in got
    assert 'photo1.jpg' in got


# ── I7. 로고·배너 무경계 필터 오탐 ──────────────────────────────
def test_이미지URL_로고티셔츠_같은_상품사진을_버리지_않는다():
    """🟠 실측 오탐 — 패션에서 '로고 티셔츠'·'로고 후디'는 흔한 **상품**이다.

    종전 규칙은 `logo`/`banner`/`sprite` 를 **경계 없는 부분문자열**로 봐서
    `logo_tee_front.jpg`·`BIG_LOGO_HOODIE_1.jpg`·`BANNER_ITEM_1.jpg` 를 전부 버렸다.
    """
    base = 'https://shop.example.com/'
    got = build_image_urls(
        ['https://shop.example.com/web/product/big/logo_tee_front.jpg',
         'https://shop.example.com/web/product/big/BIG_LOGO_HOODIE_1.jpg',
         'https://shop.example.com/web/product/big/BANNER_ITEM_1.jpg'], base)
    assert len(got) == 3, f"상품 사진이 버려졌다: {got}"


def test_이미지URL_진짜_UI자산_로고배너는_계속_버린다():
    """오탐을 고친다고 진짜 스킨 자산까지 통과시키면 안 된다(회귀 핀)."""
    base = 'https://shop.example.com/'
    got = build_image_urls(
        ['https://shop.example.com/common/logo.png',       # 파일명 몸통 = logo
         'https://shop.example.com/img/logo2.png',         # logo + 숫자
         'https://shop.example.com/banner/summer.jpg',     # 디렉터리 = banner
         'https://shop.example.com/skin/sprite.png',       # 파일명 몸통 = sprite
         'https://shop.example.com/web/product/big/real.jpg'], base)
    assert got == ['https://shop.example.com/web/product/big/real.jpg']


def test_이미지URL_후보가_있었는데_전부_버려지면_경고를_남긴다(caplog):
    """🟠 조용한 실패 금지 — 필터 오탐으로 0장이 되면 등록이 막히는데 아무 말이 없었다."""
    import logging as _lg
    with caplog.at_level(_lg.WARNING):
        assert build_image_urls(['https://x.com/common/logo.png',
                                 'https://x.com/blank.gif'], 'https://x.com/') == []
    assert any('m4img' in r.getMessage() for r in caplog.records), \
        "후보 2건이 전부 버려졌는데 경고 한 줄이 없다"


def test_이미지URL_애초에_후보가_없으면_경고하지_않는다(caplog):
    """'이 소싱처는 원래 안 준다'는 경고 대상이 아니다(경고 홍수 금지)."""
    import logging as _lg
    with caplog.at_level(_lg.WARNING):
        build_image_urls([], 'https://x.com/')
        build_image_urls(None)
    assert not [r for r in caplog.records if 'm4img' in r.getMessage()]


# ── I8. 길이 컷이 태그 중간을 자름 ──────────────────────────────
def test_상세HTML_길이컷은_태그_중간을_자르지_않는다():
    """🟠 실측 꼬리가 `...alt="상세이미지` — 깨진 HTML 이 4마켓 상세로 나갔다."""
    body = ''.join(f'<img src="https://x.com/d{i}.jpg" alt="상세이미지{i}">' for i in range(60))
    got = sanitize_detail_html(f'<div>{body}</div>', limit=500)
    assert got, "길이 초과라고 통째로 버리면 안 된다(잘라서라도 쓴다)"
    assert got.endswith('>'), f"태그 중간에서 잘렸다: ...{got[-40:]}"
    assert got.count('<img') == got.count('.jpg'), "src 가 반토막 난 img 가 있다"


def test_상세HTML_경계를_못찾으면_빈문자열이다():
    """자를 `>` 조차 없으면 깨진 조각을 마켓에 보내느니 '상세 확인불가'가 낫다."""
    assert sanitize_detail_html('<div>' + 'ㄱ' * 500, limit=3) == ''


# ── M9. bare-host 오인 ─────────────────────────────────────────
def test_이미지URL_view_do_같은_상대경로를_남의_도메인으로_만들지_않는다():
    """`view.do/a.jpg` 는 상대경로다 — `https://view.do/…`(남의 도메인)로 만들면 안 된다."""
    base = 'https://shop.example.com/goods/'
    got = build_image_urls(['view.do/a.jpg'], base)
    assert got == ['https://shop.example.com/goods/view.do/a.jpg']


# ── M10·M11. 알맹이 판정·드롭 태그 ─────────────────────────────
def test_상세HTML_빈_src_이미지는_알맹이로_치지_않는다():
    """`<img>` 가 있다고 알맹이가 아니다 — 주소가 없으면 마켓 상세는 백지다."""
    assert sanitize_detail_html('<div class="cont"><img></div>') == ''
    assert sanitize_detail_html('<div class="cont"><img src="">   </div>') == ''


def test_상세HTML_video_audio_svg_는_제거한다():
    got = sanitize_detail_html(
        '<div><p>소재</p><video src="//v.x.com/a.mp4"></video>'
        '<audio src="//v.x.com/a.mp3"></audio><svg><path d="M0"/></svg></div>')
    assert '<video' not in got and '<audio' not in got and '<svg' not in got
    assert '소재' in got


def test_상세HTML_picture_는_껍데기만_벗기고_안의_상품사진은_살린다():
    """`picture` 를 통째로 지우면 그 안 상품 사진까지 사라진다 — 껍데기만 벗긴다.

    `source` 는 (webp 대체본·추적 포함) 버리고 `img` 만 남긴다.
    """
    got = sanitize_detail_html(
        '<div><picture><source srcset="//x.com/d1.webp" type="image/webp">'
        '<img src="//x.com/detail/d1.jpg"></picture></div>')
    assert '<picture' not in got and '<source' not in got
    assert 'https://x.com/detail/d1.jpg' in got
