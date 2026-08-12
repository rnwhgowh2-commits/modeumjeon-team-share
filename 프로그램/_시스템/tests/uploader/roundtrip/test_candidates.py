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


# ── 🔴 ESM — sellStatus 요청 필터가 무시된다(지도 실측). 행 값으로 걸러야 한다 ──
from lemouton.uploader.roundtrip.candidates import esm_suspended_from_search


def _row(goods_no, iac=None, gmkt=None, name="상품"):
    st = {}
    if iac is not None:
        st["iac"] = iac
    if gmkt is not None:
        st["gmkt"] = gmkt
    return {"goodsNo": goods_no, "goodsName": name, "sellStatus": st,
            "siteGoodsNo": {"iac": f"A{goods_no}", "gmkt": f"G{goods_no}"}}


def test_직권중지_22_는_후보에서_뺀다():
    """🔴 [2026-08-07 사고] 22=직권중지는 **마켓이 강제로 세운** 상품이다.
    지재권 등의 사유라 수정 API 가 거부한다 — 시험 대상으로 잡으면 안 된다.

    지도 원문: 「sellStatus 요청 파라미터가 **무시된다**」 → 응답 행 값으로 걸러야 한다.
    「응답 행의 sellStatus 는 사이트별 {gmkt,iac}(11=판매중/21=판매중지/22=직권중지)
     — **행 값이 진실**」
    """
    rows = [_row("A", iac="21"), _row("B", iac="22"), _row("C", iac="11")]

    got = esm_suspended_from_search(rows, market="auction")

    assert [g["origin_product_no"] for g in got] == ["A"]


def test_사이트별로_따로_본다():
    """옥션은 판매중지인데 G마켓은 직권중지일 수 있다 — 내 사이트 값만 본다."""
    rows = [_row("X", iac="21", gmkt="22")]

    assert [g["origin_product_no"] for g in esm_suspended_from_search(rows, market="auction")] == ["X"]
    assert esm_suspended_from_search(rows, market="gmarket") == []


def test_상태를_모르면_후보에서_뺀다():
    """모르는 값을 판매중지로 보면 진짜 팔리는 상품을 건드린다."""
    assert esm_suspended_from_search([_row("Y")], market="auction") == []
    assert esm_suspended_from_search([_row("Z", iac="99")], market="auction") == []


def test_후보에_실제_상태값을_함께_준다():
    """무엇을 보고 골랐는지 화면에서 확인할 수 있어야 한다."""
    got = esm_suspended_from_search([_row("A", iac="21")], market="auction")

    assert got[0]["status"] == "21"
    assert got[0]["channel_product_no"] == "AA"


# ── 판매중 상품 후보 (사장님 확정 2026-08-07) ────────────────────────────────
def test_판매중_상품만_고를_수도_있다():
    """가격 +100원·재고 +1 만 왕복하므로 판매중 상품도 시험 대상이 된다."""
    page = _page(_item(1, 11, "판매중", "SALE"),
                 _item(2, 22, "중지", "SUSPENSION"),
                 _item(3, 33, "품절", "OUTOFSTOCK"))

    got = suspended_from_search(page, want="sale")

    assert [c["origin_product_no"] for c in got] == [1]
    assert got[0]["status"] == "SALE"


def test_기본은_여전히_판매중지다():
    page = _page(_item(1, 11, "판매중", "SALE"), _item(2, 22, "중지", "SUSPENSION"))

    assert [c["origin_product_no"] for c in suspended_from_search(page)] == [2]


def test_판매중을_고를_때도_한_채널이라도_다르면_뺀다():
    """한 원상품 아래 채널이 여럿이면 전부 같은 상태여야 한다."""
    page = _page({"originProductNo": 5, "channelProducts": [
        {"channelProductNo": 51, "name": "A", "statusType": "SALE"},
        {"channelProductNo": 52, "name": "A", "statusType": "SUSPENSION"},
    ]})

    assert suspended_from_search(page, want="sale") == []


def test_ESM도_판매중_11_을_고를_수_있다():
    """🔴 esm.186 원문: 「판매중지 상품은 가격 수정되지 않습니다」
    → ESM 가격 왕복은 **판매중(11)** 상품에만 성립한다."""
    rows = [_row("A", iac="21"), _row("B", iac="11"), _row("C", iac="22")]

    got = esm_suspended_from_search(rows, market="auction", want="sale")

    assert [g["origin_product_no"] for g in got] == ["B"]
    assert got[0]["status"] == "11"


def test_ESM_기본은_여전히_판매중지_21():
    rows = [_row("A", iac="21"), _row("B", iac="11")]

    assert [g["origin_product_no"] for g in esm_suspended_from_search(rows, market="auction")] == ["A"]
