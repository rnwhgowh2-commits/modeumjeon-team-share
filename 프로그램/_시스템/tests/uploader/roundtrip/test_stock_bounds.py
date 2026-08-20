# -*- coding: utf-8 -*-
"""재고가 **이미 상한**이면 +1 을 보낼 수 없다 — 그때는 -1 로 왕복한다.

[2026-08-12 라이브] 11번가 9532353519 왕복이 재고에서 거부됐다:
    「옵션재고 번호 1,2(상품번호:9532353519)의 수량 업데이트 실패.」
현재 재고가 **9,999**(11번가 상한)인데 10,000 을 보냈다.

🔴 왕복 시험은 "값을 흔들었다 되돌리는" 것이지 "무조건 늘리는" 게 아니다.
   위로 못 가면 아래로 흔들면 된다. 방향을 못 정하면 그 축은 확인불가로 남긴다
   (지어낸 값을 보내 원복 못 하는 것보다 낫다).

⚠️ 가격은 방향을 바꾸지 않는다 — 내리면 그 잠깐 동안 **싸게 팔릴 수 있다**(금전 손실).
   재고는 1 내렸다 올려도 손해가 없다(오히려 오버셀 위험이 준다).
"""
from __future__ import annotations

from lemouton.uploader.roundtrip.runner import _test_value
from lemouton.uploader.roundtrip.snapshot import Snapshot


def _snap(stock):
    return Snapshot(market="eleven11", product_id="P1", sale_price=1000,
                    options=(("S1", stock, None),))


def test_평소에는_재고를_1_올린다():
    assert _test_value("stock", _snap(10), None, bounds=(1, 9999)) == 11


def test_상한이면_1_내린다():
    """9,999 에서 10,000 을 보내면 마켓이 거부한다 — 아래로 흔든다."""
    assert _test_value("stock", _snap(9999), None, bounds=(1, 9999)) == 9998


def test_상한이자_하한이면_보내지_않는다():
    """흔들 방향이 없다 — 지어낸 값을 보내느니 확인불가로 남긴다."""
    assert _test_value("stock", _snap(1), None, bounds=(1, 1)) is None


def test_상한을_모르면_평소대로_올린다():
    """모르는 상한을 지어내 막으면, 되는 상품까지 시험을 못 한다."""
    assert _test_value("stock", _snap(9999), None, bounds=None) == 10000


def test_가격은_상한이_있어도_방향을_안_바꾼다():
    """내리면 그 잠깐 싸게 팔린다 — 재고와 달리 금전 손실이다."""
    assert _test_value("sale_price", _snap(10), None, bounds=(1, 9999)) == 1100
