# -*- coding: utf-8 -*-
"""SSG 도 **화면이 아니라 받은 글**에서 읽는다 — 라이브 진단이 그렇게 답했다.

🔴 근거 (2026-08-13 라이브 실측, 확장 0.7.96)

    0건(나이키 신발 - 추천•인기 상품, SSG.COM
        · 링크 62 · 선택자 0 · 받은글 57
        · 많은 모양 /×24 , /search.ssg×7 , /customer/main.ssg×3 ,
                    /customer/noticeList.ssg×3 , /event/eventMain.ssg×2)

   **화면엔 상품이 0개인데 받은 글엔 57개가 있다.** 링크 62개는 전부 홈·검색·
   고객센터·이벤트다. 현대H몰과 **정확히 같은 경우**다 — 서버는 상품을 보내는데
   브라우저 안 앱이 화면을 다르게 그린다.

★ 추측이 아니다. SSG 는 브라우저 도구로 못 열어(정책 차단) 눈으로 확인할 수 없어서,
  **확장이 사장님 크롬에서 대신 세어 보낸 숫자**로 판정했다.

★ 「받은 글에서 읽기」를 함부로 넓히지 않는다 — 화면에서 읽으면 화면에 없는
  배너·광고가 안 딸려 오는 장점이 있다. **실측으로 확인된 곳만** 넣는다.
"""
from __future__ import annotations

from lemouton.sources import listing_discover as LD


def test_SSG는_받은_글에서_고른다():
    assert 'ssg' in LD._HTML_SCAN, (
        'SSG 는 화면에 상품 링크가 0개이고 받은 글에만 57개가 있습니다(라이브 실측). '
        '화면에서 읽으면 영영 0건입니다.'
    )


def test_규칙에_받은글_읽기가_실려_나간다():
    """서버가 확장에 내려주는 규칙에 `html_scan` 이 켜져 있어야 실제로 먹는다."""
    rule = LD.dom_rule_for('ssg')
    assert rule['html_scan'] is True, (
        '규칙에 안 실리면 서버만 고친 것이 되고 확장은 그대로 화면에서 읽습니다 — '
        '「규칙을 넣었다」와 「그 규칙이 쓰인다」는 다른 사실입니다.'
    )


def test_H몰도_그대로다():
    assert LD.dom_rule_for('hmall')['html_scan'] is True


def test_함부로_넓히지_않았다():
    """🔴 실측으로 확인된 곳만 넣는다 — 나머지는 화면에서 읽는 편이 낫다."""
    assert LD._HTML_SCAN == {'hmall', 'ssg'}, (
        f'받은 글에서 읽는 소싱처가 {sorted(LD._HTML_SCAN)} 로 늘었습니다. '
        '실측 근거 없이 넓히면 화면에 없는 배너·광고까지 상품으로 걷힙니다.'
    )
    for key in ('musinsa', 'lotteon', 'lotteimall', 'lemouton', 'ssf'):
        assert LD.dom_rule_for(key)['html_scan'] is None, f'{key} 는 화면에서 읽어야 합니다.'


def test_상품주소_규칙은_그대로다():
    """받은 글에서 읽어도 **번호를 뽑는 규칙과 주소 틀은 같다**(규칙 한 벌 원칙)."""
    got = LD.product_url_for('1000552535854', source_key='ssg')
    assert got == 'https://www.ssg.com/item/itemView.ssg?itemId=1000552535854'


def test_받은_글에서_상품번호를_뽑는다():
    """SSG 검색 결과가 받은 글에 담아 보내는 모양 그대로 뽑히는지."""
    html = ('<div>...</div>'
            '<a href="/item/itemView.ssg?itemId=1000552535854&siteNo=6001">가</a>'
            '<script>{"link":"/item/itemView.ssg?itemId=1000552535999&x=1"}</script>')
    got = LD.extract_product_urls(html, source_key='ssg')
    assert got == ['https://www.ssg.com/item/itemView.ssg?itemId=1000552535854',
                   'https://www.ssg.com/item/itemView.ssg?itemId=1000552535999'], got
