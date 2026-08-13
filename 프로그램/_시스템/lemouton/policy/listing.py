# -*- coding: utf-8 -*-
"""정책 「등록 기본값」 항목 → 마켓으로 나가는 모양.

지금 다루는 것은 **미성년자 구매** 하나다. 나머지 칸(과세·상품상태·판매기간·제조사)은
아직 어느 마켓 payload 에도 정책값으로 안 들어간다 — 상수가 박혀 있다.

🔴 [2026-08-13] 무엇이 잘못이었나 — 정책에 「전연령 구매 가능 / 19세 이상만」을
  고르는 칸이 있는데 **읽는 코드가 0곳**이었다. `ProductDraft.minor_purchasable` 은
  `default=True` 인 채 아무도 안 채웠고, 쿠팡은 `adultOnly='EVERYONE'` 이 상수로
  박혀 있었다. 결과 — **고르신 값이 통째로 무시되고 늘 전연령으로 등록**됐다.
  성인 상품이면 그대로 미성년자에게 노출된다.

🔴 **어느 쪽으로도 지어내지 않는다.**
  · 안 고르셨으면 마켓 기본값(전연령) — 「19세 이상만」으로 넘겨짚으면 멀쩡한 상품이
    안 팔린다.
  · 모르는 값이어도 성인전용으로 바꾸지 않는다 — 오타 하나로 전 상품이 막힌다.
  즉 **정확히 「19세 이상만」일 때만** 미성년자 구매를 막는다.
"""
from __future__ import annotations

#: 정책 화면에 뜨는 말 그대로 (process_rule_schema 의 listing.minor_purchase choices)
ADULT_ONLY_LABEL = '19세 이상만'
EVERYONE_LABEL = '전연령 구매 가능'

#: 지금 이 값을 실제로 보내는 마켓. 나머지는 spec 에 칸 자체가 없다.
#:   · smartstore  detailAttribute.minorPurchasable (boolean)
#:   · coupang     items[].adultOnly (ADULT_ONLY | EVERYONE)
#: 🔴 11번가(minorSelCnYn)·옥션/G마켓(isAdultProduct)·롯데온은 아직 못 보낸다 —
#:   조립기의 spec 에 칸을 만들고 전송 함수 인자까지 늘려야 한다. 「된다」고 말하지 않는다.
SUPPORTED = ('smartstore', 'coupang')
UNSUPPORTED_NOTE = ('이 마켓은 미성년자 구매 설정을 보낼 자리를 아직 안 만들었습니다 — '
                    '저장은 되지만 마켓으로 나가지 않습니다.')


def minor_purchasable_of(rules) -> bool:
    """미성년자가 살 수 있나. `True` = 전연령(마켓 기본값).

    Args:
        rules: 가공정책 전체. `rules['listing']['minor_purchase']` 를 본다.
    """
    listing = ((rules or {}).get('listing') or {})
    return str(listing.get('minor_purchase') or '').strip() != ADULT_ONLY_LABEL


def coupang_adult_only(minor_purchasable) -> str:
    """쿠팡이 아는 말로. 🔴 상수를 박지 말고 이 함수 하나를 부른다."""
    return 'EVERYONE' if minor_purchasable else 'ADULT_ONLY'
