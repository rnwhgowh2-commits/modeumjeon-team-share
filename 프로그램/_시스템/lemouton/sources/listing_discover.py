# -*- coding: utf-8 -*-
"""리스팅 URL → 상품 URL 목록 — 대량등록 수집의 입구.

━━ 이 파일이 하는 일 / 안 하는 일 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**한다**   — 받은 HTML 에서 「상품 링크」를 고르는 **규칙**, 페이지 범위 주소 만들기.
**안 한다** — 페이지를 여는 일. 그건 브라우저가 필요하고, 브라우저는 **로컬 PC 워커**가
             돌린다(「크롤은 로컬 PC」 원칙). 서버는 규칙만 안다.

이렇게 가른 이유는 하나다 — **규칙을 시험할 수 있어야 하기 때문**이다.
규칙이 브라우저에 묶여 있으면 「상품 링크를 제대로 고르나」를 영영 못 물어본다.

━━ 재구현 금지 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`sourcing/crawlers/musinsa.py::discover_variants` 가 이미 무신사 검색 페이지를 열어
`a[href*="/products/"]` 를 전부 긁는다(모델명으로 같은 상품의 다른 색을 찾는 용도).
여기 무신사 규칙은 **그 규칙 그대로**다. 새 크롤러를 만들지 않는다.

🔴 모르는 소싱처는 **빈 목록이 아니라 예외**로 말한다.
  빈 목록으로 답하면 「그 소싱처엔 상품이 없다」로 읽혀 조용히 0건이 된다.
  「규칙을 모른다」와 「상품이 없다」는 다른 사실이다.
"""
from __future__ import annotations

import re


#: 한 번에 훑을 수 있는 페이지 수 상한.
#: 🔴 실수로 1~9999 를 넣으면 소싱처를 두들기게 된다(차단·계정 위험). 사람이 정한 안전선.
#: ★ [2026-08-08] 20 → 60. 무신사 「나이키」가 **41쪽 2,412개**라 20 으로는 절반도 못 걷는다
#:   (사장님: 「무신사 같은 경우 몇천개도 돼」). 60쪽 = 무신사 기준 3,600개까지.
#:   ★ 쪽 사이에 0.7초를 쉬므로 60쪽이면 약 1분 — 소싱처를 몰아치지 않는다.
MAX_PAGES = 60

#: 소싱처별 「상품 링크」 규칙 — (상품번호를 잡는 정규식, 상품 URL 조립틀).
#: 🔴 여기에 없는 소싱처는 **규칙을 모르는 것**이다. 지어내지 않는다.
#: 🔴 크롤러가 있는 곳만 넣는다(`sourcing/crawlers/__init__.py::build_crawlers` 8곳).
#:   주소만 모아도 긁을 사람이 없으면 조용한 0건이 된다 — ABC마트·GS샵·29CM 가 그렇다.
#:
#: ★ 아래 값은 전부 2026-08-08 **실측**이다(각 검색 페이지를 열어 링크를 눈으로 확인).
_PRODUCT_LINK = {
    # musinsa: `/products/3976350` — discover_variants 가 쓰는 규칙 그대로.
    'musinsa': (re.compile(r'/products/(\d+)'),
                'https://www.musinsa.com/products/{id}'),
    # ssf: `/NIKE-GOLF/GRTN26072152182/good` — **브랜드 칸이 주소의 일부**다.
    #   그래서 잡는 덩어리가 `브랜드/상품번호` 둘이다(다른 소싱처는 번호 하나).
    'ssf': (re.compile(r'/([A-Za-z0-9][A-Za-z0-9\-]*/[A-Z0-9]{8,})/good'),
            'https://www.ssfshop.com/{id}/good'),
    # lotteon: `/p/product/LO2474809267`
    #   🔴 `/p/product/bundle/LE...`(묶음상품)이 섞여 있다. `bundle` 을 빼지 않으면
    #     상품번호가 죄다 `bundle` 이 되어 **묶음 전부가 한 건으로 뭉개진다.**
    'lotteon': (re.compile(r'/p/product/(?!bundle\b)([A-Za-z0-9_]+)'),
                'https://www.lotteon.com/p/product/{id}'),
    # lotteimall: 🔴 **링크를 보면 안 된다.** `a[href*=viewGoodsDetail]` 로 잡히는 25건은
    #   전부 메뉴 속 추천 배너(`recom_swiper`·`plan_banner`)다 — 검색 결과가 아니다.
    #   실증(2026-08-08): 「검색된 상품이 없습니다」가 뜨는 검색어에서도 그 링크가
    #   **25건 그대로** 나왔다. 그대로 뒀으면 검색할 때마다 엉뚱한 상품 25건이
    #   크롤 대기에 들어가 초안까지 됐다.
    #   진짜 결과는 `data-goods-no` 속성이다(나이키 60건 · 결과 없음 0건, 실측 대조).
    'lotteimall': (re.compile(r'data-goods-no="(\d+)"'),
                   'https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no={id}'),
    # hmall: 🔴 **링크가 아니다.** 상품 카드가 `<a href>` 가 아니라서 링크만 찾으면
    #   영영 0건이다(실측: 검색 결과 29개 링크 중 상품 0건). 번호는 속성에만 있다.
    # hmall: 🔴 **화면이 아니라 받은 글에서 읽는다**(2026-08-08 라이브에서 드러남).
    #   `page=3` 을 열어 보니 화면(DOM `[data-slitm-cd]`)은 **1쪽 36개**,
    #   받은 글(HTML `"slitmCd":`)은 **3쪽 36개**, **겹침 0**이었다 —
    #   서버는 3쪽을 보내는데 브라우저 안 앱이 다시 1쪽을 불러 화면을 덮어쓴다.
    #   그래서 6쪽을 시켜도 결과가 36개(1쪽 분량)뿐이었다.
    'hmall': (re.compile(r'"slitmCd"\s*:\s*"?(\d{6,})'),
              'https://www.hmall.com/md/pda/itemPtc?slitmCd={id}'),
    # lemouton(카페24): `/product/detail.html?product_no=140`
    #   🔴 카페24 템플릿 자리표시자 `product_no={$*product_no}` 가 HTML 에 그대로
    #     남아 있다. **숫자만** 잡지 않으면 목록마다 가짜 상품이 한 건씩 섞인다.
    'lemouton': (re.compile(r'product_no=(\d+)'),
                 'https://lemouton.co.kr/product/detail.html?product_no={id}'),
    # ssg: `/item/itemView.ssg?itemId=1000552535854&siteNo=…&salestrNo=…`
    #   상품 주소 모양은 `sourcing/crawlers/ssg.py` 첫 줄에 적힌 그대로다
    #   (그 크롤러가 라이브에서 SSG 상품을 실제로 긁는다 — 지어낸 값이 아니다).
    #   🔴 **다만 검색 결과 화면을 내 눈으로 못 봤다** — SSG 는 앱 브라우저·크롬 연결
    #     둘 다 정책 차단이고 서버로 받아도 403 이다(2026-08-08 확인).
    #     그래서 확장이 사장님 크롬에서 대신 재 보게 하고, 첫 결과를 사장님 화면
    #     숫자와 대조하기 전에는 **「검증됨」이라 적지 않는다.**
    'ssg': (re.compile(r'itemView[.]ssg[?][^"<>]*?itemId=(\d+)'),
            'https://www.ssg.com/item/itemView.ssg?itemId={id}'),
}

#: 소싱처별 페이지 파라미터 이름. 없으면 페이지 넘김을 모르는 것.
#: 🔴 「검색 페이지가 무한 스크롤이라 안 먹는 곳」은 일부러 비워 둔다 —
#:   있지도 않은 파라미터를 붙이면 같은 1페이지를 10번 훑고 「10장 봤다」고 거짓말한다.
#:   실측: 롯데온 `page=2`·롯데아이몰 `startIndex=2`·SSF 검색 `currentPage=2` 모두
#:   1페이지와 첫 상품이 같았다. SSF 는 **카테고리 목록**에서만 진짜로 넘어간다.
_PAGE_PARAM = {
    # 🔴 [2026-08-08] musinsa 를 뺐다. `page=` 를 **서버가 아예 무시한다** —
    #   1쪽과 2쪽 응답의 상품번호가 완전히 같았다(둘 다 totalCount 2412).
    #   그대로 뒀으면 「5쪽까지」로 시켜도 같은 1쪽을 5번 긁고 「5장 봤다」고 거짓말했다.
    #   무신사는 응답이 주는 `nextPageUrl` 을 따라간다(`_NEXT_URL_RE`).
    'ssf': 'currentPage',
    # 🔴 [2026-08-08] H몰은 「스크롤」로 보이지만 **주소로 넘어간다.**
    #   __NEXT_DATA__ 에 totalCount 16,406 · totalPages 456(쪽당 36개)이 있었고
    #   `page=` 를 붙이니 그대로 넘어갔다(6쪽 216개, 중복 0).
    #   ★ `pageNo=` 는 안 먹는다(1쪽과 같음) — 이름을 확인 안 하면 같은 쪽을 반복한다.
    #   ★ 진짜 마우스 휠로 굴려도 `[data-slitm-cd]` 는 같은 36개였다(화면만 갈아 끼움).
    'hmall': 'page',
    # ssg: 사장님이 2쪽으로 넘긴 뒤의 주소를 그대로 주셨다 — `&page=2`.
    'ssg': 'page',
    # 르무통은 검색·카테고리 둘 다 `page` 로 **진짜 넘어간다**(1쪽·2쪽 상품 25개가 달랐다).
    'lemouton': 'page',
}

#: 「검색 결과가 없다」고 화면이 말할 때 쓰는 글귀.
#: 🔴🔴 [2026-08-08 실측] 소싱처 대부분이 **결과가 0건이어도 추천 상품을 화면에 깐다.**
#:   실측 — 무신사 19 · 롯데온 25 · 롯데아이몰 25 · 현대H몰 12 · 르무통 1 / SSF 만 0.
#:   막지 않으면 **오타 한 번에 엉뚱한 상품 수십 건이 크롤 대기에 들어가 초안까지 된다.**
#: ★ 글귀는 화면에 보이는 말이라 소싱처가 UI 를 바꾸면 안 맞을 수 있다 —
#:   그래서 **이게 없다고 0건으로 만들지는 않는다.** 있을 때만 「없다」고 확정한다.
_EMPTY_TEXT = {
    'musinsa': '검색 결과가 없습니다',      # 뒤에 「회원가입 이벤트 상품」 19건이 깔린다
    'lotteon': '검색결과가 없습니다',
    'lotteimall': '검색된 상품이 없습니다',
    'hmall': '검색결과가 없습니다',
    'lemouton': '검색결과가 없습니다',      # 결과 0건인데 상단 노출 상품 1건이 잡혔다
}

#: 응답이 **스스로 알려 주는 다음 쪽 주소**를 꺼내는 규칙.
#: 🔴 주소를 우리가 조립하면 안 된다 — 무신사는 `hmacId` 라는 서명이 붙어 있어
#:   `page=2` 로 손수 바꿔 부르면 **403 「잘못된 접근입니다」**가 온다(실측).
#:   받은 주소를 **글자 그대로** 따라가야 한다.
#: ★ 실측(2026-08-08): 무신사 나이키 = 41쪽 2,412개, 쪽당 60개, 중복 0.
_NEXT_URL_RE = {
    'musinsa': r'"nextPageUrl"\s*:\s*"([^"]+)"',
}

#: 소싱처별 「다음」 단추 — 눌러 가며 여러 장을 걷는다(주소로도 스크롤로도 못 넘기는 곳).
#: 🔴 모르는 곳은 **비워 둔다.** 선택자를 추측해 넣으면 「더 있음」이 늘 켜지거나
#:   늘 꺼져서 둘 다 거짓말이 된다.
#: 🔴 **같은 소싱처인데 주소 종류에 따라 페이지 넘김이 다른** 경우.
#:   여기 걸리는 주소는 페이지 파라미터를 **안 붙인다**(붙이면 같은 1쪽을 반복한다).
#: ★ 실측(2026-08-08) — SSF 는 카테고리 목록에서만 `currentPage` 가 먹고,
#:   검색 결과에서는 1쪽·2쪽·`page=2` 가 **상품 60개까지 완전히 겹쳤다.**
_NO_PAGE_PATH = {
    'ssf': re.compile(r'/search/result'),
}

#: **화면이 아니라 받은 글(HTML)에서** 상품번호를 읽어야 하는 소싱처.
#: 🔴 H몰은 서버가 보낸 쪽과 화면이 그리는 쪽이 다르다(위 주석 참조).
#: 🔴 SSG 도 같다 — ★ 실측(2026-08-13 라이브, 확장 0.7.96):
#:     0건(나이키 신발 - 추천•인기 상품, SSG.COM
#:         · 링크 62 · 선택자 0 · **받은글 57**
#:         · 많은 모양 /×24 , /search.ssg×7 , /customer/main.ssg×3 , /event/eventMain.ssg×2)
#:   **화면엔 상품이 0개인데 받은 글엔 57개**가 있었다. 링크 62개는 전부 홈·검색·
#:   고객센터·이벤트다. SSG 는 브라우저 도구로 못 열어(정책 차단) 눈으로 확인할 수
#:   없어서, **확장이 사장님 크롬에서 대신 세어 보낸 숫자**로 판정했다.
#: ★ 다른 곳은 화면에서 읽는다 — 화면에서 읽는 편이 「눈에 보이는 것과 같다」는
#:   장점이 있다(화면에 없는 배너·광고가 안 딸려 온다). 추측으로 넓히지 않는다.
_HTML_SCAN = {'hmall', 'ssg'}

_MORE_SELECT = {
    'lotteon': 'a.srchPaginationNext',      # 실측: 「다음」 — 눌러서 상품이 바뀜
    # 🔴🔴 [2026-08-13 라이브 실측] 아이몰의 `a.next.ico`(「다음」)는 **다음 쪽이 아니라
    #   「다음 10쪽 묶음」**이다. 한 번 눌렀더니 1쪽 → **11쪽**으로 뛰었다.
    #   그래서 60번 눌러도 1·11·21… 쪽만 걷고 **아홉 쪽씩 통째로 건너뛰었다.**
    #   (라이브: 60번 눌러 705개 — 60쪽×60개=3,600 이어야 할 자리)
    # ★ 「지금 쪽(`a.on`) 바로 다음 것」을 누르면 한 쪽씩 정확히 넘어간다(12→13 실측).
    #   묶음 끝(20쪽)에서는 그 다음이 「다음」 단추라 21쪽으로 이어진다 — 한 벌로 끝난다.
    'lotteimall': '.wrap_page a.on + a',
}

#: 확장(로컬 PC)이 페이지 안에서 쓸 규칙 — 어떤 요소의 어느 값을 볼 것인가.
#: 🔴 확장에 규칙을 **박아 두지 않는다.** 예전엔 `a[href*="/products/"]` 가 확장 안에
#:   박혀 있어 소싱처를 넣어도 무신사 말고는 0건이었다. 규칙을 아는 곳은 서버 하나다.
_DOM_SELECT = {
    'musinsa':    ('a[href*="/products/"]', 'href'),
    'ssf':        ('a[href*="/good"]', 'href'),
    'lotteon':    ('a[href*="/p/product/"]', 'href'),
    'lotteimall': ('[data-goods-no]', 'data-goods-no'),
    'hmall':      ('[data-slitm-cd]', 'data-slitm-cd'),
    'lemouton':   ('a[href*="product_no="]', 'href'),
    'ssg':        ('a[href*="itemView.ssg"]', 'href'),
}


def _rule(source_key: str):
    key = str(source_key or '').strip().lower()
    if key not in _PRODUCT_LINK:
        raise ValueError(
            f'{key or "(빈 소싱처)"} 는 아직 리스팅에서 상품을 골라내는 규칙이 없습니다 — '
            f'그 소싱처의 검색 결과 주소 규칙을 먼저 확인해야 합니다. '
            f'지금 아는 곳: {", ".join(sorted(_PRODUCT_LINK))}.')
    return _PRODUCT_LINK[key]


def dom_rule_for(source_key: str) -> dict:
    """확장(로컬 PC)이 페이지에서 상품번호를 뽑을 때 쓸 규칙.

    Returns:
        {'sel': CSS 선택자, 'attr': 볼 속성 이름, 'id_re': 상품번호를 잡는 정규식}

    ★ 확장은 요소마다 **`속성이름="값"` 꼴 문자열을 만들어** 거기에 `id_re` 를 건다.
      그래야 규칙이 **한 벌**로 끝난다 — 링크에서 뽑는 곳(무신사 등)과 속성에서 뽑는
      곳(H몰)이 같은 정규식을 쓸 수 있다. 규칙이 두 벌이면 화면에서 본 개수와
      저장된 개수가 소리 없이 갈린다.

    🔴 모르는 소싱처는 빈 규칙이 아니라 예외다 — 빈 규칙을 주면 확장이 0건을
      돌려보내고, 그건 「그 소싱처엔 상품이 없다」로 읽힌다.
    """
    key = str(source_key or '').strip().lower()
    pat, _tpl = _rule(key)          # 모르는 곳이면 여기서 예외
    sel, attr = _DOM_SELECT[key]
    return {'sel': sel, 'attr': attr, 'id_re': pat.pattern,
            'html_scan': (key in _HTML_SCAN) or None,
            'more_sel': _MORE_SELECT.get(key),
            'next_url_re': _NEXT_URL_RE.get(key),
            'empty_text': _EMPTY_TEXT.get(key)}


def product_url_for(product_id, *, source_key: str) -> str:
    """상품번호 → 상품 주소. **주소 모양을 아는 곳은 여기 하나뿐이다.**

    확장(로컬 PC)은 페이지에서 **번호만** 긁어 보낸다. 조립을 확장에서 하면 규칙을
    아는 곳이 둘이 되고, 소싱처를 하나 붙일 때마다 확장까지 고쳐야 한다
    (그때마다 사장님께 「확장 다시 불러오기」를 부탁하게 된다).
    """
    _, tpl = _rule(source_key)
    return tpl.format(id=str(product_id).strip())


def extract_product_urls(html: str, *, source_key: str, max_items=None) -> list[str]:
    """리스팅 페이지 HTML → 상품 URL 목록(순서 유지·중복 제거).

    Args:
        html: 리스팅 페이지의 HTML(또는 렌더된 DOM 문자열).
        source_key: 'musinsa' 등. 모르는 값이면 ValueError.
        max_items: 이 개수까지만. None = 상한 없음.

    Returns:
        상품 URL 목록. **0 건은 오류가 아니다** — 검색 결과가 없을 수 있다.

    ★ 추적 꼬리표(`?srsltid=` 등)는 자연히 떨어진다 — 링크에서 **상품번호만** 뽑아
      우리 틀로 다시 조립하기 때문이다. 꼬리표가 붙은 채 저장되면 같은 상품이
      두 벌로 갈린다(`ProductDraft.source_url` 은 정규화형만 담는다는 규약과 같은 이유).
    """
    pat, tpl = _rule(source_key)
    out, seen = [], set()
    for m in pat.finditer(html or ''):
        pid = m.group(1)
        if pid in seen:
            continue
        seen.add(pid)
        out.append(tpl.format(id=pid))
        if max_items is not None and len(out) >= int(max_items):
            break
    return out


def next_page_url_from(html: str, *, source_key: str):
    """받은 HTML/JSON 에서 **다음 쪽 주소**를 그대로 꺼낸다. 없으면 None.

    🔴 조립하지 않는다 — 서명(`hmacId`)이 붙어 있어 손대면 403 이 온다.
    🔴 규칙을 모르는 소싱처는 None (여기서 억지로 찾지 않는다).
    """
    key = str(source_key or '').strip().lower()
    pat = _NEXT_URL_RE.get(key)
    if not pat:
        return None
    m = re.search(pat, html or '')
    if not m:
        return None
    # ★ JSON 안에 있어 `&` 가 글자 그대로 & (백슬래시+u0026 여섯 글자)로 적혀 있다 — raw 문자열로 맞춰야 한다.
    return m.group(1).replace('\\u0026', '&').replace('\\/', '/')


def click_pages_for(source_key: str, page_from=None, page_to=None) -> int:
    """단추로 넘기는 소싱처에서 **「다음」을 몇 번 눌러 걷을지.** 1 = 첫 장만.

    ━━ 사장님 화면을 그대로 쓴다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    「몇 쪽부터 / 몇 쪽까지」 칸이 이미 있다. 주소로 넘기는 곳은 주소를 만들고,
    단추로 넘기는 곳은 **그만큼 단추를 누른다.** 같은 뜻인데 칸이 둘이면
    사장님이 어느 쪽을 채워야 할지 모른다.

    🔴 주소로 넘길 수 있는 곳은 **누르지 않는다**(1을 돌려준다) — 주소로도 넘기고
      단추도 누르면 같은 상품을 두 번 걷는다.
    🔴 상한은 `MAX_PAGES`. 실수로 1~9999 를 넣으면 소싱처를 두들긴다(차단 위험).
    """
    key = str(source_key or '').strip().lower()
    if _PAGE_PARAM.get(key):          # 주소로 넘기는 곳 — 주소를 여러 개 만든다
        return 1
    # 화면 안에서 넘기는 곳 = 「다음」 단추(롯데온·아이몰) 또는 다음쪽 주소(무신사).
    # 🔴 무신사를 여기 안 넣으면 확장이 첫 쪽만 보고 끝난다(다음쪽을 아예 안 따라감).
    if not (_MORE_SELECT.get(key) or _NEXT_URL_RE.get(key)):
        return 1
    if page_from is None and page_to is None:
        return 1                      # 임의로 넓히지 않는다
    lo = max(1, int(page_from or 1))
    hi = max(lo, int(page_to or lo))
    return min(hi - lo + 1, MAX_PAGES)


def can_resume(source_key: str, listing_url: str) -> bool:
    """**이어서 걷기가 되는 소싱처인가.**

    ① 주소로 쪽을 넘기는 곳 — 주소에 쪽 번호를 넣으면 되니 당연히 된다.
    ② 「다음」 단추로 넘기는 곳(롯데온·아이몰) — **눌러서 건너뛰면 된다.**
       늘 1쪽에서 시작해야 하는 건 맞지만, 걷지 않고 **누르기만** 하면 빠르다.
       🔴 공짜가 아니다 — 300쪽부터 걸으려면 299번을 눌러야 한다. 시한에 걸리면
         확장이 걷은 것을 들고 나오며 「더 있음」이라 말한다(조용히 잘리지 않는다).

    ★ 어느 쪽도 아닌 곳(무신사의 다음쪽 주소 · SSF 검색)은 중간부터 시작할 수단이
      아예 없다 — 그런 곳은 한 회차에 끝까지 간다(무신사 1,218 실증).
    """
    key = str(source_key or '').strip().lower()
    if _MORE_SELECT.get(key):
        return True                     # 눌러서 건너뛸 수 있다
    param = _PAGE_PARAM.get(key)
    if not param:
        return False
    bad = _NO_PAGE_PATH.get(key)
    if bad and bad.search(listing_url or ''):
        return False          # SSF 검색 주소처럼 쪽이 안 먹는 모양
    return True


def click_skip_for(source_key: str, cursor) -> int:
    """「다음」 단추 소싱처에서 **걷기 전에 몇 번 눌러 건너뛸지.**

    이어걷기 커서가 301쪽이면 300번 눌러 건너뛴 뒤 301쪽부터 걷는다.
    주소로 넘기는 곳은 0(건너뛸 필요가 없다).
    """
    key = str(source_key or '').strip().lower()
    if not _MORE_SELECT.get(key):
        return 0
    return max(0, int(cursor or 1) - 1)


def next_window(page_from, page_to, cursor, *, more: bool):
    """이번 회차에 걸을 창 → **다음 회차가 시작할 쪽.**

    Args:
        page_from/page_to: 사장님이 적은 「몇 쪽부터~까지」(한 회차에 걷는 창).
        cursor: 지금까지의 이어걷기 위치(None = 처음부터).
        more: 이번 회차가 「더 있음」이라 답했나.

    Returns:
        다음 회차의 시작 쪽. **None 이면 처음부터** 다시 본다.

    🔴 끝까지 걸었으면 처음으로 되돌린다 — 새 상품은 앞쪽에 들어오므로
      한 바퀴 돌면 다시 1쪽부터 보는 것이 맞다. 커서를 그대로 두면
      **영영 앞쪽 새 상품을 못 본다.**
    """
    lo = max(1, int(cursor or page_from or 1))
    win = max(1, int(page_to or lo) - int(page_from or 1) + 1)
    win = min(win, MAX_PAGES)
    if not more:
        return None
    return lo + win


def window_for(page_from, page_to, cursor):
    """이번 회차에 실제로 걸을 (시작 쪽, 끝 쪽)."""
    lo = max(1, int(cursor or page_from or 1))
    win = max(1, int(page_to or lo) - int(page_from or 1) + 1)
    win = min(win, MAX_PAGES)
    return lo, lo + win - 1


def page_urls_for(listing_url: str, *, source_key: str,
                  page_from=None, page_to=None) -> list[str]:
    """리스팅 URL + 페이지 범위 → 실제로 열 주소 목록.

    범위를 안 주면 **받은 주소 그대로 한 장**만 본다(임의로 넓히지 않는다).

    ★ 이미 `page=` 가 붙어 있으면 **바꿔 끼운다.** 사장님이 2페이지 주소를 그대로
      붙여넣을 수 있는데, 뒤에 또 붙이면 `page` 가 두 번 들어가 소싱처가 어느 쪽을
      읽을지 알 수 없다.
    """
    key = str(source_key or '').strip().lower()
    if page_from is None and page_to is None:
        return [listing_url]
    param = _PAGE_PARAM.get(key)
    # 같은 소싱처라도 이 주소 모양이면 페이지 넘김이 안 먹는다(SSF 검색 결과).
    bad = _NO_PAGE_PATH.get(key)
    if param and bad and bad.search(listing_url or ''):
        param = None
    if not param:
        # 🔴 예전엔 여기서 예외를 냈다 — 그러면 범위를 적은 순간 **첫 장조차 못 걷는다.**
        #   주소로 못 넘기는 곳이라도 첫 장은 걷을 수 있고, 단추로 넘기는 곳이면
        #   `click_pages_for` 가 「몇 번 누를지」로 답한다. 걷을 수 있는 데까지는 걷는다.
        return [listing_url]

    lo = max(1, int(page_from or 1))
    hi = max(lo, int(page_to or lo))
    hi = min(hi, lo + MAX_PAGES - 1)          # 상한은 「몇 장을 훑느냐」 기준

    # ★ 주소를 **다시 조립하지 않는다.** 쿼리를 파싱해 재조립하면 한글 키워드가
    #   `%EB%82%98…` 로 바뀌어 사장님이 붙여넣은 주소와 달라진다(동작은 하지만
    #   화면·기록에 남는 값이 딴판이 되고, 소싱처가 인코딩에 까다로우면 깨진다).
    #   기존 page 만 도려내고 뒤에 붙인다 — 나머지는 글자 그대로 보존.
    stripped = re.sub(r'[?&]' + re.escape(param) + r'=[^&#]*', '', listing_url)
    # 앞 파라미터를 지워 `?&a=1` 이 된 경우 정리
    stripped = stripped.replace('?&', '?')
    if stripped.endswith('?'):
        stripped = stripped[:-1]
    joiner = '&' if '?' in stripped else '?'
    return [f'{stripped}{joiner}{param}={p}' for p in range(lo, hi + 1)]
