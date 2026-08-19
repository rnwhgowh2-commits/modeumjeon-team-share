# -*- coding: utf-8 -*-
"""[2026-08-13 사장님 확정 「b」] 샵마인 대조의 **노랑에 사유를 붙인다.**

■ 왜 필요해졌나

  2026-08-12 에 「배송비도 수수료를 뗀다」를 고치면서, 우리 N열(정산 배송비포함)이
  샵마인 값보다 **배송비 수수료만큼 작아졌다**(쿠팡 실측 132원).

      샵마인 = 실결제 − 수수료 + **고객배송비 전액**      117,924
      우리   = 상품정산 + **배송비 정산 실값**(수수료 뗀)  117,792

  차이 132원 > 허용오차 6원이라 「일치(초록)」가 안 되고, 샵마인 값이 재현식
  (`실결제 − 수수료 + 배송비`)에 걸려 「정의차이(노랑)」가 된다. 라이브 2,072건.

  🔴 그런데 종전 코드는 노랑에 **아무 설명도 안 남겼다.** 화면은 「정의차이 2,072건」
  이라고만 말한다. 「1건=5만원 정합성」이 목적인 화면에서 2,072건이 이유 없이 노랑이면,
  사장님은 무엇이 틀어졌는지 알 길이 없다.

■ 그래서 — 노랑마다 **왜 노란지**를 남기고, 사유별로 모아 화면에 올린다.

  ★ 사유는 **지어내지 않는다.** 그 줄의 배송비·배송비정산 실값으로 실제 계산해
    `차이 == 고객배송비 − 배송비 정산` 일 때만 「배송비 수수료 차이」라고 부른다.
    설명이 안 되면 「설명 못 함」으로 남긴다 — 그게 사실이다.
"""
from lemouton.markets import shopmine_recon as SR


def _sm(**kw):
    """샵마인 한 줄. 정산(배송비포함) = 실결제 − 수수료 + 고객배송비 (45건 전수 실측)."""
    d = {"market": "coupang", "order_no": "O1", "sm_alias": "브랜드마켓",
         "order_date": "2026-07-01", "qty": 1, "unit": 128900,
         "paid": 132900, "fee": 18976, "ship": 4000, "opt_add": 0,
         "product": "코트", "option": "블랙/95"}
    d.update(kw)
    d.setdefault("settle_incl", d["paid"] - d["fee"] + d["ship"])
    return d


def _our(**kw):
    """우리 한 줄. N열은 _finalize 가 M + 배송비정산 으로 만든다."""
    d = {"판매처": "쿠팡", "오픈마켓주문번호": "O1", "주문일": "2026-07-01 10:00",
         "수량": 1, "단가": 128900, "실결제금액": 132900,
         "정산예정금액": 113924, "배송비": 4000, "_ship_settle": 3868,
         "_settle_source": "real", "주문상태": "배송완료"}
    d.update(kw)
    d.setdefault("정산예정금(배송비포함)",
                 d["정산예정금액"] + (d.get("_ship_settle")
                                      if d.get("_ship_settle") is not None
                                      else d["배송비"]))
    return d


def _run(sm=None, our=None):
    return SR.reconcile([sm or _sm()], [our or _our()])


def _settle(out, market="coupang"):
    return out["fields"][market]["settle"]


# ── 판정 자체는 안 바뀐다 (맞던 것까지 흔들지 않는다) ──────────

def test_배송비_수수료_차이는_노랑으로_남는다():
    out = _run()
    assert _settle(out)["def"] == 1, f'노랑이 아니다: {_settle(out)}'
    assert _settle(out)["diff"] == 0, '빨강으로 잘못 갔다'


def test_배송비가_없는_주문은_그대로_초록():
    out = _run(sm=_sm(ship=0), our=_our(배송비=0, _ship_settle=None))
    assert _settle(out)["match"] == 1, f'배송비 없는 줄까지 노랗게 만들었다: {_settle(out)}'


# ── 🔴 여기부터가 이번에 더하는 것 ────────────────────────────

def test_노랑에_왜_노란지가_남는다():
    out = _run()
    사유들 = out["def_reasons"]["coupang"]["settle"]
    assert 사유들, '노랑인데 사유가 하나도 없다 — 화면이 이유를 말할 수 없다'
    이름 = next(iter(사유들))
    assert "배송비 수수료" in 이름, f'사유 이름이 뜻을 안 담는다: {이름}'
    assert 사유들[이름]["건수"] == 1


def test_사유마다_금액이_얼마나_갈리는지_같이_센다():
    """건수만 있으면 「132원짜리 2,072건」인지 「큰 금액 몇 건」인지 못 가른다."""
    out = _run()
    사유 = next(iter(out["def_reasons"]["coupang"]["settle"].values()))
    assert 사유["금액합"] == 4000 - 3868, f'차이 금액을 안 모은다: {사유}'


def test_사유는_그_줄_실값으로_확인한_것만_붙인다():
    """🔴 지어내지 않는다 — 배송비 수수료로 설명이 **안 되는** 차이엔 그 이름을 안 붙인다.

    같은 노랑이어도 원인이 다를 수 있다. 뭉뚱그리면 화면이 거짓말을 한다.
    """
    # 배송비 정산 실값이 없는데(추정) 우리 값만 딴 데서 달라진 경우
    our = _our(_ship_settle=None, 정산예정금액=113000)   # N = 113,000 + 4,000
    out = _run(our=our)
    사유들 = out["def_reasons"]["coupang"]["settle"]
    for 이름 in 사유들:
        assert "배송비 수수료" not in 이름, \
            f'설명이 안 되는 차이에 배송비 수수료라고 이름 붙였다: {이름}'


def test_노랑도_표본을_남긴다():
    """빨강만 표본이 있어 노랑은 어느 주문인지 확인할 길이 없었다."""
    out = _run()
    표본 = out["defs"]
    assert 표본, '노랑 표본이 없다'
    r = 표본[0]
    assert r["order_no"] == "O1" and r["field"] == "settle"
    assert r["shop"] == 117924 and r["ours"] == 117792
    assert "배송비 수수료" in r["reason"]


def test_초록과_빨강엔_사유를_안_붙인다():
    """설명이 필요한 건 노랑뿐이다 — 초록에 사유를 달면 화면이 시끄러워진다."""
    out = _run(sm=_sm(ship=0), our=_our(배송비=0, _ship_settle=None))
    assert not out["def_reasons"].get("coupang", {}).get("settle")
    assert out["defs"] == []
