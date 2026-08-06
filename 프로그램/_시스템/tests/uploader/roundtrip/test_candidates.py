# -*- coding: utf-8 -*-
"""시험 대상 고르기 — **판매중지 상품만** 왕복 시험에 쓴다.

사장님 확정(2026-08-06): 진짜 판매중 상품은 잠깐이라도 이름·사진이 바뀌면
노출·판매지수·재심사 위험이 있으므로 건드리지 않는다.
"""
from __future__ import annotations

from lemouton.uploader.roundtrip.candidates import suspended_from_search


def _page(*items):
    return {"contents": list(items), "totalElements": len(items)}


def _item(origin, channel, name, status):
    return {"originProductNo": origin,
            "channelProducts": [{"channelProductNo": channel, "name": name,
                                 "statusType": status}]}


def test_판매중지_상품만_고른다():
    page = _page(_item(1, 11, "판매중상품", "SALE"),
                 _item(2, 22, "중지상품", "SUSPENSION"),
                 _item(3, 33, "품절상품", "OUTOFSTOCK"))

    got = suspended_from_search(page)

    assert [c["origin_product_no"] for c in got] == [2]
    assert got[0]["name"] == "중지상품"
    assert got[0]["channel_product_no"] == 22


def test_수정용_번호는_originProductNo_다():
    """수정 API 는 originProductNo 를 요구한다 — channelProductNo 를 넣으면 실패한다
    (2026-07-17 과거이력)."""
    got = suspended_from_search(_page(_item(7, 77, "중지", "SUSPENSION")))

    assert got[0]["origin_product_no"] == 7
    assert got[0]["channel_product_no"] == 77


def test_originProductNo_가_없으면_후보에서_뺀다():
    """번호를 모르는 채 수정하면 남의 상품에 값이 갈 수 있다 — 추측 금지."""
    page = _page({"channelProducts": [{"channelProductNo": 9, "name": "번호없음",
                                       "statusType": "SUSPENSION"}]})

    assert suspended_from_search(page) == []


def test_빈_응답이어도_터지지_않는다():
    assert suspended_from_search({}) == []
    assert suspended_from_search({"contents": None}) == []


def test_한_원상품에_채널상품이_여럿이면_모두_판매중지여야_고른다():
    """하나라도 팔리고 있으면 그 원상품은 건드리면 안 된다."""
    page = _page({"originProductNo": 5, "channelProducts": [
        {"channelProductNo": 51, "name": "A", "statusType": "SUSPENSION"},
        {"channelProductNo": 52, "name": "A", "statusType": "SALE"},
    ]})

    assert suspended_from_search(page) == []
