# -*- coding: utf-8 -*-
"""소싱처 상세 HTML 안 **타 마켓 브랜딩 이미지** 감지 (자동 제거 ❌ · 표면화 ⭕).

배경 — 소싱처 셀러가 상세페이지에 **경쟁 마켓 기획전 배너**를 심어 둔다.
실측(2026-07-23, `tests/sources/fixtures/ssg_detail_iframe.html` = 라이브 원본):

    <a href="https://department.ssg.com/plan/planShop.ssg?...">
      <img src="https://nike2094.godohosting.com/products/info/ssg_banner.jpg">

링크(`a`)는 공통 관문이 이미 unwrap 으로 버렸지만 **사진은 그대로 남는다**. 그 상세가
`lemouton/registration/compile_more.py:98` 을 지나 옥션·G마켓·11번가·롯데온 본문으로
올라간다 → **판매금지·상품삭제** 사유.

★ **사장님 결정 (나)안 — 자동으로 지우지 않는다.** 파일명 판정은 오탐이 나서
  (`ssg` 가 들어간 멀쩡한 상품 사진) 자동 삭제는 상품 사진을 지운다. 그래서 이 모듈은
  **감지·표면화만** 하고, 빼는 것은 사장님이 화면에서 고른 것만 한다.
"""
import pathlib

import pytest

from lemouton.sourcing.crawlers.foreign_assets import (
    detect_foreign_market_assets, remove_assets_from_detail,
)

FIX = pathlib.Path(__file__).parent / "fixtures"


def _urls(hits):
    return [h['url'] for h in hits]


# ─────────────────────────────────────────────────────────────
# 1) 잡아야 하는 것 — 타 마켓 브랜딩
# ─────────────────────────────────────────────────────────────
def test_SSG_기획전_배너_사진을_잡는다():
    """실측 원본 그대로. 파일명 몸통이 `ssg_` 로 시작한다."""
    html = ('<div><img src="https://nike2094.godohosting.com'
            '/products/info/ssg_banner.jpg"></div>')
    hits = detect_foreign_market_assets(html)
    assert len(hits) == 1, hits
    assert hits[0]['url'].endswith('/ssg_banner.jpg')
    assert hits[0]['token'] == 'ssg'
    assert hits[0]['where'] == 'img'


def test_남아_있는_타마켓_링크도_잡는다():
    """`a` 는 공통 관문이 unwrap 하지만, 어떤 경로로든 남아 있으면 그것도 표면화한다."""
    html = '<a href="https://department.ssg.com/plan/planShop.ssg?x=1">기획전</a>'
    hits = detect_foreign_market_assets(html)
    assert len(hits) == 1, hits
    assert hits[0]['where'] == 'link'
    assert hits[0]['token'] == 'ssg'


@pytest.mark.parametrize('url,token', [
    ('https://cdn.example.com/img/coupang_event.jpg', 'coupang'),
    ('https://cdn.example.com/img/11st_sale.png', '11st'),
    ('https://cdn.example.com/img/gmarket_banner.jpg', 'gmarket'),
    ('https://cdn.example.com/img/auction_bnr.jpg', 'auction'),
    ('https://cdn.example.com/img/lotteon-plan.jpg', 'lotteon'),
    ('https://cdn.example.com/img/lotteimall_2026.jpg', 'lotteimall'),
    ('https://cdn.example.com/img/interpark.jpg', 'interpark'),
    ('https://cdn.example.com/img/wemakeprice_1.jpg', 'wemakeprice'),
    ('https://cdn.example.com/img/tmon.jpg', 'tmon'),
    ('https://cdn.example.com/img/emart_mall.jpg', 'emart'),
    ('https://cdn.example.com/img/shinsegae_point.jpg', 'shinsegae'),
    ('https://cdn.example.com/img/elevenst.jpg', 'elevenst'),
    ('https://sell.smartstore.naver.com/img/x.jpg', 'smartstore'),
    ('https://cdn.example.com/naver/talk.jpg', 'naver'),
    ('https://cdn.example.com/coupang/rocket.jpg', 'coupang'),
])
def test_마켓_토큰_15종을_호스트든_경로든_잡는다(url, token):
    hits = detect_foreign_market_assets(f'<img src="{url}">')
    assert hits, url
    assert hits[0]['token'] == token, (url, hits)


# ─────────────────────────────────────────────────────────────
# 2) 잡으면 안 되는 것 — 오탐 (멀쩡한 상품 사진이 지워진다)
# ─────────────────────────────────────────────────────────────
def test_SSG_상품사진_CDN_은_감지하지_않는다():
    """🔴 이게 오탐의 본체다. SSG 상품 사진은 `sitem.ssgcdn.com` 에 있다.

    ①토큰 경계상 `ssgcdn` 은 `ssg` 다음이 글자라 애초에 안 걸리고
    ②그래도 새면 안 되니 **상품 이미지 CDN 화이트리스트**로 한 번 더 막는다.
    """
    html = ('<img src="https://sitem.ssgcdn.com/58/80/93/item/'
            '1000809938058_i1_1200.jpg">'
            '<img src="https://simg.ssgcdn.com/58/80/93/item/x_i2_1200.jpg">')
    assert detect_foreign_market_assets(html) == []


@pytest.mark.parametrize('url', [
    # 화이트리스트 — 소싱처들의 상품 사진 CDN (호스트에 마켓 이름이 들어간다)
    'https://image.lotteimall.com/goods/x/1234567890_1.jpg',
    'https://image2.lotteimall.com/goods/x/1234567890_2.jpg',
    'https://shop-phinf.pstatic.net/2026/07/1_abc.jpg',
    # 토큰 경계 — 다른 낱말 안에 우연히 들어간 것
    'https://cdn.example.com/img/lastmonth_lookbook.jpg',   # …s-TMON-th
    'https://cdn.example.com/img/themart_edition.jpg',      # th-EMART
    'https://cdn.example.com/img/2011street_style.jpg',     # 2011ST-reet
    'https://cdn.example.com/img/navera_collection.jpg',    # NAVER-a
    'https://cdn.example.com/img/auctions_guide.jpg',       # AUCTION-s
    'https://cdn.example.com/img/a1tmon2_hash.jpg',         # 해시 한복판
])
def test_경계_오탐이_나지_않는다(url):
    assert detect_foreign_market_assets(f'<img src="{url}">') == [], url


def test_쿼리스트링은_보지_않는다():
    """🔴 SSG 는 상품 URL 에 `ckwhere=naver`(네이버 유입 쿠폰)를 실제로 달고 다닌다.

    추적·유입 파라미터까지 보면 멀쩡한 상품 사진이 전부 「네이버 이미지」가 된다.
    """
    html = '<img src="https://sitem.ssgcdn.com/58/item/x_i1_1200.jpg?ckwhere=naver">'
    assert detect_foreign_market_assets(html) == []


def test_상품사진_CDN_은_하위도메인까지_인정하고_사칭_도메인은_아니다():
    """`a.ssgcdn.com` 은 화이트리스트지만 `ssgcdn.com.evil.kr` 은 남의 도메인이다."""
    ok = '<img src="https://newimg.ssgcdn.com/item/a_i1.jpg">'
    assert detect_foreign_market_assets(ok) == []
    bad = '<img src="https://sitem.ssgcdn.com.evil.kr/ssg_banner.jpg">'
    assert len(detect_foreign_market_assets(bad)) == 1


# ─────────────────────────────────────────────────────────────
# 3) 결과 모양
# ─────────────────────────────────────────────────────────────
def test_같은_주소가_여러_번_나와도_한_번만_보고한다():
    u = 'https://cdn.example.com/img/coupang_event.jpg'
    html = f'<img src="{u}"><p>글</p><img src="{u}">'
    assert len(detect_foreign_market_assets(html)) == 1


def test_상대경로는_base_url_로_절대화해서_보고한다():
    """화면에서 그대로 눌러 확인해야 하고, 제거 API 도 같은 주소로 지운다."""
    hits = detect_foreign_market_assets(
        '<img src="/products/info/ssg_banner.jpg">',
        base_url='https://nike2094.godohosting.com/goods/1')
    assert _urls(hits) == [
        'https://nike2094.godohosting.com/products/info/ssg_banner.jpg']


def test_지연로딩_이미지도_data_src_로_본다():
    """상세를 정제하기 전 원본을 넘겨도 놓치지 않는다(Cafe24 edibot 형태)."""
    html = ('<img src="data:image/gif;base64,R0lGOD" '
            'data-src="https://cdn.example.com/img/coupang_event.jpg">')
    hits = detect_foreign_market_assets(html)
    assert _urls(hits) == ['https://cdn.example.com/img/coupang_event.jpg']


def test_빈값_None_은_빈_리스트다():
    assert detect_foreign_market_assets(None) == []
    assert detect_foreign_market_assets('') == []
    assert detect_foreign_market_assets('<p>사진 없음</p>') == []


# ─────────────────────────────────────────────────────────────
# 4) 실 fixture — SSG 상세 iframe 원본 (라이브 캡처)
# ─────────────────────────────────────────────────────────────
def _ssg_detail() -> str:
    p = FIX / "ssg_detail_iframe.html"
    if not p.exists():
        pytest.skip("fixture 없음: ssg_detail_iframe.html")
    from lemouton.sourcing.crawlers.ssg import parse_detail_iframe_html
    return parse_detail_iframe_html(
        p.read_text(encoding="utf-8"),
        'https://itemdesc.ssg.com/item/iframePItemDtlDesc.ssg?itemId=1000809938058')


def test_SSG_실상세에서_배너_3장만_잡고_상품_안내사진은_남긴다():
    """5장 중 3장이 SSG 브랜딩(`ssg_banner`·`notice_ssg`·`ssg_guide_banner`),
    나머지 2장(`PARTNER_01`·`size_shoes_man`)은 셀러가 만든 안내 사진이라 그대로 둔다."""
    hits = detect_foreign_market_assets(_ssg_detail())
    names = sorted(u.rsplit('/', 1)[-1] for u in _urls(hits))
    assert names == ['notice_ssg.jpg', 'ssg_banner.jpg', 'ssg_guide_banner.png'], names
    assert all(h['token'] == 'ssg' for h in hits), hits


# ─────────────────────────────────────────────────────────────
# 5) 선택 제거 — 사장님이 고른 것만 뺀다
# ─────────────────────────────────────────────────────────────
def test_고른_이미지만_빼고_나머지는_그대로_둔다():
    html = _ssg_detail()
    target = 'https://nike2094.godohosting.com/products/info/ssg_banner.jpg'
    out, removed = remove_assets_from_detail(html, [target])
    assert removed == 1
    assert 'ssg_banner.jpg' not in out
    # 나머지 4장은 살아 있어야 한다 — 통째로 지우면 상세가 반토막 난다.
    for keep in ('PARTNER_01.JPG', 'size_shoes_man.jpg',
                 'notice_ssg.jpg', 'ssg_guide_banner.png'):
        assert keep in out, keep


def test_없는_주소를_주면_아무것도_지우지_않는다():
    html = '<div><img src="https://cdn.example.com/a.jpg"></div>'
    out, removed = remove_assets_from_detail(html, ['https://cdn.example.com/zzz.jpg'])
    assert removed == 0
    assert 'a.jpg' in out


def test_빈_목록이면_원본_그대로다():
    html = '<div><img src="https://cdn.example.com/a.jpg"></div>'
    out, removed = remove_assets_from_detail(html, [])
    assert removed == 0
    assert 'a.jpg' in out


def test_링크는_주소만_있어도_지울_수_있다():
    html = ('<p><a href="https://department.ssg.com/plan/planShop.ssg">기획전</a>'
            '<img src="https://cdn.example.com/a.jpg"></p>')
    out, removed = remove_assets_from_detail(
        html, ['https://department.ssg.com/plan/planShop.ssg'])
    assert removed == 1
    assert 'department.ssg.com' not in out
    assert '기획전' in out          # 글은 남긴다(unwrap 규약과 같다)
    assert 'a.jpg' in out
