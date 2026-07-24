# -*- coding: utf-8 -*-
"""쿠팡 정산 조회 실패를 조용히 삼키지 않는다(2026-07-24).

정산 조회가 깨지면 통째로 삼켜지고 {} 가 돌아가, 화면엔 「추정」 정산액만 남았다.
사장님 눈엔 그냥 숫자라 '못 가져온 것'과 '아직 정산 전인 것'이 구별되지 않았다.
"""
from lemouton.markets import order_export as oe


def test_drain_returns_and_clears():
    oe._CP_SETTLE_ERRORS.clear()
    oe._CP_SETTLE_ERRORS.append("HTTPError: 400")
    assert oe._drain_cp_settle_errors() == ["HTTPError: 400"]
    assert oe._drain_cp_settle_errors() == []      # 비웠다 — 다음 조회로 이월되지 않는다


def test_drain_dedupes():
    """계정·기간창이 여럿이면 같은 사유가 겹친다 — 배너에 한 번만."""
    oe._CP_SETTLE_ERRORS.clear()
    oe._CP_SETTLE_ERRORS.extend(["HTTPError: 400", "HTTPError: 400", "Timeout"])
    assert oe._drain_cp_settle_errors() == ["HTTPError: 400", "Timeout"]
