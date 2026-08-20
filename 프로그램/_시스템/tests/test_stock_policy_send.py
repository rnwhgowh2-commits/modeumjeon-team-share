# -*- coding: utf-8 -*-
"""마켓 전송 재고 규칙 회귀 시험 — 「무재고 상품이 품절로 올라가던」 사고 고정.

실측 사고(2026-08-06): 「상품수집&전송」 보내기 경로가 전 옵션에 재고 0을 보냈다.
  · a_output 의 boxhero_stock 이 0 고정
  · formatter 가 소싱처 크롤 재고(sources)를 payload 로 넘기지 않음
  · 쿠팡·스마트스토어·롯데온 어댑터엔 0 차단 가드가 없음(ESM 만 유효범위로 막힘)

사장님 확정 규칙: 보낼 재고 = 내 재고 + 크롤 재고, 상한 100, 확인 불가면 보류.
"""
from lemouton.formatter.stock_policy import STOCK_CAP, resolve_send_stock


def test_무재고_상품은_크롤재고가_나간다():
    """내 창고 재고 0이어도 소싱처에 5개 있으면 5개를 보낸다 (품절 금지)."""
    stock, reason = resolve_send_stock(0, [5])
    assert (stock, reason) == (5, "ok")


def test_사입_상품은_소싱처_없어도_내재고가_나간다():
    stock, reason = resolve_send_stock(7, [])
    assert (stock, reason) == (7, "ok")


def test_혼합이면_합산된다():
    stock, reason = resolve_send_stock(3, [4, 2])
    assert (stock, reason) == (9, "ok")


def test_상한_100_을_넘지_않는다():
    stock, reason = resolve_send_stock(50, [500, 300])
    assert stock == STOCK_CAP == 100
    assert reason == "ok"


def test_확인불가면_전송_보류_0을_보내지_않는다():
    """크롤 재고 None = 확인 불가. 품절로 단정하면 오전송이다."""
    stock, reason = resolve_send_stock(0, [None])
    assert stock is None
    assert reason == "unknown"


def test_확인불가여도_아는_재고가_있으면_보낸다():
    stock, reason = resolve_send_stock(0, [None, 4])
    assert (stock, reason) == (4, "ok")


def test_전부_확실히_0이면_진짜_품절():
    stock, reason = resolve_send_stock(0, [0, 0])
    assert (stock, reason) == (0, "soldout")


def test_음수_재고는_0으로_방어():
    stock, reason = resolve_send_stock(-5, [-3])
    assert (stock, reason) == (0, "soldout")


def test_esm_유효범위_안이다():
    """ESM 재고 규격 1~99,999 — 상한 100 은 그 안이라 규격 위반이 안 난다.

    (지도 과거이력: 「ESM 재고 0 전송 = 오버셀」 — 0 은 무효, 품절은 사이트별 플래그)
    """
    stock, _ = resolve_send_stock(0, [99999])
    assert 1 <= stock <= 99999
