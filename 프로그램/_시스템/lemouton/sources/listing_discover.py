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
MAX_PAGES = 20

#: 소싱처별 「상품 링크」 규칙 — (상품번호를 잡는 정규식, 상품 URL 조립틀).
#: 🔴 여기에 없는 소싱처는 **규칙을 모르는 것**이다. 지어내지 않는다.
_PRODUCT_LINK = {
    # musinsa: `/products/3976350` — discover_variants 가 쓰는 규칙 그대로.
    'musinsa': (re.compile(r'/products/(\d+)'),
                'https://www.musinsa.com/products/{id}'),
}

#: 소싱처별 페이지 파라미터 이름. 없으면 페이지 넘김을 모르는 것.
_PAGE_PARAM = {
    'musinsa': 'page',
}


def _rule(source_key: str):
    key = str(source_key or '').strip().lower()
    if key not in _PRODUCT_LINK:
        raise ValueError(
            f'{key or "(빈 소싱처)"} 는 아직 리스팅에서 상품을 골라내는 규칙이 없습니다 — '
            f'그 소싱처의 검색 결과 주소 규칙을 먼저 확인해야 합니다. '
            f'지금 아는 곳: {", ".join(sorted(_PRODUCT_LINK))}.')
    return _PRODUCT_LINK[key]


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
    if not param:
        raise ValueError(f'{key} 는 페이지 넘김 규칙을 아직 모릅니다 — 범위를 못 씁니다.')

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
