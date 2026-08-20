# -*- coding: utf-8 -*-
"""무신사는 **화면이 스스로 다음 쪽 주소를 알려 준다.**

━━ 🔴 내가 틀렸던 것 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
「무신사는 `page=` 로 넘어간다」고 규칙에 적어 뒀는데 **서버가 그 값을 아예 무시한다.**
실측(2026-08-08): `page=1` 과 `page=2` 의 응답이 **글자 수까지 거의 같고**
목록 상품번호가 완전히 동일했다(둘 다 `totalCount 2412`).
그대로 뒀으면 「5쪽까지」로 시켜도 **같은 1쪽을 5번 긁고** 「5장 봤다」고 거짓말했다.

━━ 진짜 창구 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
검색 페이지 HTML 안에 목록 응답이 통째로 들어 있고, 거기 `pagination` 이 있다:

    "pagination": {"page":1, "size":60, "totalCount":2412, "totalPages":41,
                   "hasNext":true,
                   "nextPageUrl":"https://api.musinsa.com/api2/dp/v2/plp/goods?...&hmacId=..."}

🔴 **주소를 우리가 조립하면 안 된다.** `hmacId` 라는 서명이 붙어 있어,
  `page=2` 로 손수 바꿔 부르면 **403 「잘못된 접근입니다」**가 돌아온다(실측).
  받은 `nextPageUrl` 을 **그대로** 따라가야 한다.

실측 결과 — 2쪽 60개 · 3쪽 60개 · 4쪽 60개, 누적 180개(중복 0). 총 41쪽 2,412개.
"""
import pytest

from lemouton.sources.listing_discover import dom_rule_for, next_page_url_from


HTML = ('{"list":[{"goodsNo":6842612}],'
        '"pagination":{"page":1,"size":60,"totalCount":2412,'
        '"nextPageUrl":"https://api.musinsa.com/api2/dp/v2/plp/goods?gf=A'
        '\\u0026keyword=%EB%82%98%EC%9D%B4%ED%82%A4\\u0026page=2\\u0026size=60'
        '\\u0026hmacId=acd7f7cf","hasNext":true,"totalPages":41}}')


def test_다음_쪽_주소를_그대로_꺼낸다():
    got = next_page_url_from(HTML, source_key='musinsa')

    assert got == ('https://api.musinsa.com/api2/dp/v2/plp/goods?gf=A'
                   '&keyword=%EB%82%98%EC%9D%B4%ED%82%A4&page=2&size=60'
                   '&hmacId=acd7f7cf'), got


def test_서명을_손대지_않는다():
    """🔴 `hmacId` 를 빼거나 page 를 손수 바꾸면 403 「잘못된 접근입니다」가 온다."""
    got = next_page_url_from(HTML, source_key='musinsa')

    assert 'hmacId=acd7f7cf' in got, got


def test_마지막_쪽이면_없다고_답한다():
    last = '{"pagination":{"page":41,"hasNext":false,"totalPages":41}}'

    assert next_page_url_from(last, source_key='musinsa') is None


def test_다음_쪽_규칙을_모르는_곳은_None():
    """롯데온은 단추로 넘긴다 — 여기서 억지로 주소를 찾지 않는다."""
    assert next_page_url_from(HTML, source_key='lotteon') is None


def test_무신사는_이제_주소_파라미터로_넘긴다고_말하지_않는다():
    """🔴 이 시험이 없으면 「page=」 거짓말이 조용히 되살아난다."""
    from lemouton.sources.listing_discover import _PAGE_PARAM

    assert 'musinsa' not in _PAGE_PARAM


def test_확장에_다음쪽_규칙이_실려_간다():
    r = dom_rule_for('musinsa')

    assert r.get('next_url_re'), r
