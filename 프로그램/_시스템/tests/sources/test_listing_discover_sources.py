# -*- coding: utf-8 -*-
"""소싱처 넓히기 — 무신사 말고도 리스팅에서 상품을 골라낼 수 있어야 한다.

━━ 이 파일의 값은 전부 **실측**이다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026-08-08 각 소싱처 검색·목록 페이지를 실제로 열어 링크 모양을 눈으로 확인하고
그대로 옮겼다(지어낸 규칙 0건). 확인한 주소:
  · SSF      https://www.ssfshop.com/search/result?keyword=나이키        → 27건
  · 롯데온    https://www.lotteon.com/search/search/search.ecn?...q=나이키 → 48건
  · 롯데아이몰 https://www.lotteimall.com/search/searchMain.lotte?...      → 26건
  · 현대H몰   https://www.hmall.com/md/pde/search?searchTerm=나이키       → 40건

━━ 🔴 크롤할 수 있는 곳만 넓힌다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`sourcing/crawlers/__init__.py::build_crawlers` 가 아는 8곳이 전부다. ABC마트·GS샵·
29CM 는 **크롤러가 아예 없다** — 주소만 모아 봐야 아무도 못 긁는다(조용한 실패).
그래서 여기서도 안 넣는다.
"""
import pytest

from lemouton.sources.listing_discover import (
    dom_rule_for, extract_product_urls, page_urls_for)


# ── SSF (삼성물산) ────────────────────────────────────────────────────
#   실측: 상품 주소에 **브랜드 칸이 끼어 있다** — `/NIKE-GOLF/GRTN.../good`.
#   브랜드 칸은 아무 값이나 넣어도 상품이 열리지만(직접 확인), 목록이 알려 준
#   진짜 브랜드를 그대로 쓴다 — 사장님이 「소싱처 바로가기」로 열었을 때 화면 주소와
#   같아야 한다.
SSF_HTML = """
<a href="/NIKE-GOLF/GRTN26072152182/good?utag=ref_sch:%EB%82%98%EC%9D%B4%ED%82%A4$set:1">A</a>
<a href="/kuho-plus/GM0026030904432/good">B</a>
<a href="/NIKE-GOLF/GRTN26072152182/good">A 또(썸네일·제목 둘 다 링크)</a>
<a href="/Sports-Goods/list?dspCtgryNo=SFME37A22">카테고리 — 상품 아님</a>
<a href="/Beanpole-Men/OUTLET/list?currentPage=1">목록 — 상품 아님</a>
"""


def test_SSF_브랜드칸까지_살려서_주소를_만든다():
    urls = extract_product_urls(SSF_HTML, source_key='ssf')

    assert urls == ['https://www.ssfshop.com/NIKE-GOLF/GRTN26072152182/good',
                    'https://www.ssfshop.com/kuho-plus/GM0026030904432/good'], urls


def test_SSF_카테고리_목록은_currentPage_로_넘긴다():
    """실측 — 검색 페이지는 무한 스크롤이라 안 먹지만 **카테고리 목록은 진짜 넘어간다**
    (currentPage=1 과 2 의 상품 60개가 서로 달랐다)."""
    got = page_urls_for('https://www.ssfshop.com/Beanpole-Men/OUTLET/list?dspCtgryNo=SFMA44',
                        source_key='ssf', page_from=1, page_to=3)

    assert got == [
        'https://www.ssfshop.com/Beanpole-Men/OUTLET/list?dspCtgryNo=SFMA44&currentPage=1',
        'https://www.ssfshop.com/Beanpole-Men/OUTLET/list?dspCtgryNo=SFMA44&currentPage=2',
        'https://www.ssfshop.com/Beanpole-Men/OUTLET/list?dspCtgryNo=SFMA44&currentPage=3'], got


# ── 롯데온 ────────────────────────────────────────────────────────────
#   🔴 실측에서 잡은 함정 — 검색 결과에 **묶음상품** `/p/product/bundle/LE1430173936`
#     이 섞여 있다. 순진하게 `/p/product/([A-Za-z0-9_]+)` 로 잡으면 상품번호가
#     `bundle` 이 되고, 묶음이 몇 개든 **전부 같은 한 건으로 뭉개진다.**
LOTTEON_HTML = """
<a href="https://www.lotteon.com/p/product/LO2474809267">A</a>
<a href="https://www.lotteon.com/p/product/bundle/LE1430173936">묶음 — 상품 아님</a>
<a href="https://www.lotteon.com/p/product/bundle/LE1383818644">묶음 — 상품 아님</a>
<a href="https://www.lotteon.com/p/product/PD60669549">B</a>
"""


def test_롯데온_묶음상품은_빼고_고른다():
    urls = extract_product_urls(LOTTEON_HTML, source_key='lotteon')

    assert urls == ['https://www.lotteon.com/p/product/LO2474809267',
                    'https://www.lotteon.com/p/product/PD60669549'], urls


def test_롯데온_묶음이_상품번호_bundle_로_뭉개지지_않는다():
    """이 시험이 없으면 묶음 20개가 조용히 한 건이 된다."""
    urls = extract_product_urls(LOTTEON_HTML, source_key='lotteon')

    assert not any('bundle' in u for u in urls), urls


# ── 롯데아이몰 ────────────────────────────────────────────────────────
#   🔴 **링크를 보면 안 된다.** `a[href*=viewGoodsDetail]` 로 잡히는 것은 전부
#     메뉴 속 추천 배너다 — 검색 결과가 아니다.
#     실증(2026-08-08): 「검색된 상품이 없습니다」가 뜨는 검색어에서도 그 링크가
#     **25건 그대로** 나왔다. 그대로 뒀으면 검색할 때마다 엉뚱한 상품 25건이
#     크롤 대기에 들어가 초안까지 됐을 것이다(조용히 틀린 데이터).
#   진짜 결과는 `data-goods-no` 다(나이키 60건 · 결과 없음 0건, 실측 대조).
LOTTEIMALL_HTML = """
<p class="info1" data-goods-no="3092098045">A</p>
<p class="info1" data-goods-no="2901997165">B</p>
<p class="info1" data-goods-no="3092098045">A 또</p>
<a href="https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=3272278659">추천 배너 — 상품 아님</a>
<a href="/planshop/viewPlanShopDetail.lotte?plan_no=1">기획전 — 상품 아님</a>
"""


def test_롯데아이몰은_링크가_아니라_속성에서_고른다():
    urls = extract_product_urls(LOTTEIMALL_HTML, source_key='lotteimall')

    assert urls == [
        'https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=3092098045',
        'https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2901997165'], urls


def test_롯데아이몰_추천배너는_상품이_아니다():
    """🔴 이걸 안 막으면 결과 0건인 검색에서도 엉뚱한 상품 25건이 들어온다."""
    urls = extract_product_urls(LOTTEIMALL_HTML, source_key='lotteimall')

    assert not [u for u in urls if '3272278659' in u], urls


# ── 현대H몰 ──────────────────────────────────────────────────────────
#   🔴 실측 1차 — 상품 카드가 **`<a href>` 가 아니다**(검색 결과 29개 링크 중 상품 0건).
#     그래서 처음엔 화면 속성 `data-slitm-cd` 로 잡았다.
#   🔴 실측 2차(2026-08-08 라이브) — **그것도 부족했다.** `page=3` 을 열어 보니
#     화면(DOM `[data-slitm-cd]`)은 1쪽 36개, 받은 글(HTML `"slitmCd":`)은 3쪽 36개,
#     **겹침 0**. 브라우저 안 앱이 다시 1쪽을 불러 화면을 덮어쓴다.
#     → **받은 글에서 읽는다**(`_HTML_SCAN`). 자세한 것은 test_html_scan_sources.py.
HMALL_HTML = """
{"list":[{"slitmCd":"2152524048"},{"slitmCd":"2149351778"},{"slitmCd":"2152524048"}]}
<div data-slitm-cd="9999999999">화면에 그려진 1쪽 상품 — 지금 쪽이 아닐 수 있다</div>
<a href="/md/dpa/searchSpexSectItem?sectId=3140693">기획 — 상품 아님</a>
"""


def test_H몰은_받은_글에서_고른다():
    urls = extract_product_urls(HMALL_HTML, source_key='hmall')

    assert urls == ['https://www.hmall.com/md/pda/itemPtc?slitmCd=2152524048',
                    'https://www.hmall.com/md/pda/itemPtc?slitmCd=2149351778'], urls


# ── 르무통 (카페24) ──────────────────────────────────────────────────
#   실측 — 로그인 없이 열리고 `page` 로 **진짜 페이지가 넘어간다**(1쪽과 2쪽의
#   상품 25개가 서로 달랐다). 검색·카테고리 둘 다 같은 모양.
#   🔴 함정 — 카페24 템플릿 자리표시자 `product_no={$*product_no}` 가 HTML 에
#     그대로 남아 있다. 숫자만 잡지 않으면 이게 상품 하나로 둔갑한다.
LEMOUTON_HTML = """
<a href="/product/detail.html?product_no=140">A</a>
<a href="/product/detail.html?product_no=325&cate_no=60">B</a>
<a href="/product/detail.html?product_no=140">A 또</a>
<a href="/product/detail.html?product_no=%7B%24*product_no%7D">템플릿 자리표시자</a>
"""


def test_르무통_상품번호만_고른다():
    urls = extract_product_urls(LEMOUTON_HTML, source_key='lemouton')

    assert urls == [
        'https://lemouton.co.kr/product/detail.html?product_no=140',
        'https://lemouton.co.kr/product/detail.html?product_no=325'], urls


def test_르무통_템플릿_자리표시자는_상품이_아니다():
    """이걸 안 막으면 목록마다 가짜 상품이 한 건씩 섞인다."""
    urls = extract_product_urls(LEMOUTON_HTML, source_key='lemouton')

    assert not [u for u in urls if 'product_no' in u.split('=')[-1]], urls


def test_르무통은_page_로_넘긴다():
    got = page_urls_for('https://lemouton.co.kr/product/list_women.html?cate_no=60',
                        source_key='lemouton', page_from=1, page_to=2)

    assert got == [
        'https://lemouton.co.kr/product/list_women.html?cate_no=60&page=1',
        'https://lemouton.co.kr/product/list_women.html?cate_no=60&page=2'], got


# ── 규칙을 확장에 내려보내기 ──────────────────────────────────────────
#   🔴 이게 이 작업의 핵심이다. 확장 `_listingCollectIds` 는 **무신사 전용으로
#     박혀 있었다**(`a[href*="/products/"]`). 서버에 규칙을 넣어도 확장이 안 쓰면
#     새 소싱처는 영영 0건이다 — 「넣었다」와 「쓰인다」는 다른 사실.

@pytest.mark.parametrize('key', ['musinsa', 'ssf', 'lotteon', 'lotteimall', 'hmall',
                                 'lemouton'])
def test_아는_소싱처는_확장에_줄_규칙이_있다(key):
    r = dom_rule_for(key)

    assert r['sel'], r
    assert r['attr'], r
    assert r['id_re'], r


def test_확장에_주는_정규식은_서버가_쓰는_것과_같다():
    """두 벌이 되면 화면에서 본 개수와 저장된 개수가 소리 없이 갈린다."""
    from lemouton.sources import listing_discover as LD

    for key in ('musinsa', 'ssf', 'lotteon', 'lotteimall', 'hmall', 'lemouton'):
        assert dom_rule_for(key)['id_re'] == LD._PRODUCT_LINK[key][0].pattern, key


def test_모르는_소싱처는_빈_규칙이_아니라_예외():
    """빈 값으로 답하면 「그 소싱처엔 상품이 없다」로 읽혀 조용히 0건이 된다."""
    with pytest.raises(ValueError):
        dom_rule_for('gsshop')


def test_크롤러가_없는_소싱처는_아예_안_넣는다():
    """ABC마트·GS샵·29CM 는 크롤러가 없다 — 주소를 모아도 아무도 못 긁는다."""
    from lemouton.sources import listing_discover as LD
    from lemouton.sourcing.crawlers import build_crawlers

    crawlable = set(build_crawlers())
    assert set(LD._PRODUCT_LINK) <= crawlable, (
        f'크롤러 없는 소싱처가 리스팅 규칙에만 들어 있다: '
        f'{set(LD._PRODUCT_LINK) - crawlable}')
