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


def test_settle_map_skips_inverted_window(monkeypatch):
    """1일 미만 꼬리 창은 건너뛴다 — rec_from > rec_to 로 뒤집혀 400 을 냈다.

    since 00:00 + '지금'(시각 포함)이 30일 배수에 걸리면 [경계00:00, 경계HH:MM] 창이
    생겨 rec_to(끝-1일) < rec_from → 쿠팡 HTTP 400 → 정산 전멸(추정 고착).
    """
    import datetime as dt
    from lemouton.markets import order_export as oe
    seen = []

    def _fake_page(rec_from, rec_to, token="", max_per_page=50, client=None):
        seen.append((rec_from, rec_to))
        return {"data": [], "hasNext": False}

    monkeypatch.setattr(
        "shared.platforms.coupang.settlements.fetch_revenue_page", _fake_page)
    # 30일 경계 + 3시간 → [D0 00:00, D30 00:00], [D30 00:00, D30 03:00]
    since = dt.datetime(2026, 5, 1, 0, 0)
    until = dt.datetime(2026, 5, 31, 3, 0)
    oe._coupang_settle_map(since, until, client=object())
    # 꼬리 창(rec_from=2026-05-31 > rec_to=2026-05-30)은 호출되지 않는다
    assert all(rf <= rt for rf, rt in seen), seen
