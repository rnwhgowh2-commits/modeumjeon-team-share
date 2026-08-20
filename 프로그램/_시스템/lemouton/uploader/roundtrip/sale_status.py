# -*- coding: utf-8 -*-
"""판매상태 판정 — **정본 하나**(`lemouton/catalog/status.unify_status`)만 쓴다.

🔴 [2026-08-06 실측] 손으로 만든 낱말 판정("중지"·"중단"·"정지")이 쿠팡에서 통째로
   빗나갔다. 쿠팡의 실제 statusName 은 **부분승인완료 · 승인반려 · 상품삭제** 라
   후보 300개를 훑고 0건이 나왔다(같은 계정 카탈로그엔 판매중지 4,621건).

   그 표는 이미 `catalog/status.py` 에 라이브 실측 근거와 함께 있었다.
   같은 개념을 두 곳에서 각자 판정하면 한쪽이 바뀐 날 조용히 갈라진다.

**안전 방향**
    · 모르는 값은 판매중지로도, 판매중으로도 **단정하지 않는다**.
      모르는 값을 판매중지로 보면 → 진짜 팔리는 상품을 건드린다(위험).
      모르는 값을 판매중으로 보면 → 시험이 거부된다(안전).
    · 대기(waiting)·품절(soldout)은 판매중지가 아니다 — 시험 대상에서 뺀다.
      대기 상품을 건드리면 심사 흐름이 꼬인다.
"""
from __future__ import annotations

from lemouton.catalog.status import unify_status


def unified(market: str, raw) -> str:
    """마켓 원본 상태 → 통일 상태(sale/soldout/stopped/waiting/unknown)."""
    return unify_status(market, raw)


def is_stopped(market: str, raw) -> bool:
    """판매중지인가. **모르면 False** — 모르는 값을 건드리지 않는다."""
    return unified(market, raw) == "stopped"


def is_on_sale(market: str, raw) -> bool:
    """판매중인가. **모르면 False** — 단정하지 않는다.

    ⚠️ 왕복 시험의 「판매중이면 거부」 게이트는 이 함수의 반대가 아니다.
       거부 여부는 `is_stopped()` 가 True 일 때만 통과시키는 쪽으로 판단한다
       (모르는 상태 = 시험 안 함).
    """
    return unified(market, raw) == "sale"
