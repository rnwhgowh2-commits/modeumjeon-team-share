# -*- coding: utf-8 -*-
"""소싱처 **한글 이름표** — 단일 원천.

크롤·주문·매트릭스가 저마다 `{'musinsa': '무신사', ...}` 를 들고 있으면, 한 곳에서
이름을 고쳐도 다른 화면엔 영문 키가 그대로 남는다. 실제로 주문 「바로가기」 버튼에
`lotteimall` · `hmall` 이 영문으로 떴다(2026-07-31 라이브 실측).

★ 모르는 키는 **지어내지 않고 키 그대로** 돌려준다 — 엉뚱한 이름을 붙이면
  사장님이 다른 소싱처로 읽는다.
"""
from __future__ import annotations

SITE_LABEL = {
    'lemouton': '르무통 공홈',
    'ss_lemouton': '스마트스토어 르무통',
    'musinsa': '무신사',
    'ssf': 'SSF샵',
    'lotteimall': '롯데아이몰',
    'lotteon': '롯데온',
    'ssg': 'SSG',
    'hmall': 'H몰',
}


def label_of(site_key) -> str:
    """소싱처 키 → 한글 이름. 모르면 키 그대로(추측 금지)."""
    k = str(site_key or '').strip()
    return SITE_LABEL.get(k, k)
