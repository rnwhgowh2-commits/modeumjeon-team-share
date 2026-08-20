# -*- coding: utf-8 -*-
"""단건 실전송 화면의 마켓 목록이 **실제 지원 범위와 어긋나 있었다**(2026-08-12).

`scoped_send._account_adapter` 는 진작 6마켓(스스·쿠팡·롯데온·11번가·옥션·G마켓)을
다 만들 수 있었는데, 화면 목록 `SEND_MARKETS` 만 3개로 잠겨 있었다.
그래서 옥션·G마켓·11번가에 등록된 상품은 화면에서 **고를 수조차 없었다**.

🔴 「코드가 없다」와 「목록에 안 적었다」는 다른 문제다. 뒤엣것은 에러도 안 나서
   있는 기능이 없는 것처럼 굳는다.

같은 날 6마켓 전부 라이브 왕복(가격 +100 · 재고 ±1 전송 후 원복)으로 쓰기가
되는 걸 실측했다 — 근거 없이 여는 게 아니다.
"""
from __future__ import annotations

from lemouton.uploader.scoped_send import _account_adapter
from webapp.routes.live_send_test import ROUNDTRIP_MARKETS, SEND_MARKETS


def test_화면_목록이_어댑터_지원범위와_같다():
    keys = {m["key"] for m in SEND_MARKETS}

    assert keys == set(ROUNDTRIP_MARKETS), (
        f"화면에서 못 고르는 마켓이 있다: {set(ROUNDTRIP_MARKETS) - keys}")


def test_모든_목록_마켓이_실어댑터를_가진다():
    """목록에만 있고 어댑터가 없으면 고른 순간 죽는다."""
    for m in SEND_MARKETS:
        try:
            _account_adapter(m["key"], None, live=True)
        except ValueError as e:
            raise AssertionError(f"{m['key']} 어댑터가 없다: {e}") from None
        except Exception:  # noqa: BLE001 — 자격증명 없음 등은 여기 관심사가 아니다
            pass


def test_표시명이_비어_있지_않다():
    for m in SEND_MARKETS:
        assert (m.get("label") or "").strip(), f"표시명이 없다: {m}"
