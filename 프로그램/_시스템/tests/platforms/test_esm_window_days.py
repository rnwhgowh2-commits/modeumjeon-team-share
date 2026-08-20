# -*- coding: utf-8 -*-
"""ESM 조회기간 상한은 마켓마다 다르다 — 옥션 180일 / G마켓 31일.

근거: 공식문서 etapi.gmarket.com/67
  · G마켓 "31일 이하의 범위만 조회할 수 있습니다"
  · 옥션  180일 이하 범위 조회 가능

기존 코드는 둘 다 31일로 쪼개고 있었다. 옥션은 필요 호출 수가 6배로 늘어나는데,
ESM 주문조회는 **5초당 1회**(계정별) 제한이라 그대로 대기 시간이 된다.
예: 최근 180일 · 상태 5종 → 31일 분할이면 30회(=150초), 180일이면 5회(=25초).
"""
import datetime as _dt

from shared.platforms.esm import orders as mod


def _span(market, days):
    until = _dt.datetime(2026, 7, 20, 12, 0)
    since = until - _dt.timedelta(days=days)
    return list(mod._windows(since, until, market))


def test_옥션은_180일을_한_구간으로_조회한다():
    assert len(_span("auction", 180)) == 1


def test_G마켓은_180일을_31일씩_쪼갠다():
    got = _span("gmarket", 180)
    assert len(got) == 6                       # ceil(180/31)
    for a, b in got:
        assert (b - a).days <= 31


def test_구간은_빈틈도_겹침도_없다():
    """빈틈 = 주문 누락, 겹침 = 같은 주문 재조회(호출 낭비)."""
    for market in ("auction", "gmarket"):
        got = _span(market, 200)
        for (a1, b1), (a2, b2) in zip(got, got[1:]):
            assert b1 == a2                    # 앞 구간 끝 == 다음 구간 시작
        assert got[0][0] == _dt.datetime(2026, 7, 20, 12, 0) - _dt.timedelta(days=200)
        assert got[-1][1] == _dt.datetime(2026, 7, 20, 12, 0)


def test_상한_이하_기간은_한_번만_조회한다():
    assert len(_span("auction", 7)) == 1
    assert len(_span("gmarket", 7)) == 1


def test_모르는_마켓은_보수적으로_31일을_쓴다():
    """상한을 넘겨 호출하면 마켓이 거부한다 — 모르면 좁은 쪽이 안전."""
    got = _span("unknown", 180)
    assert len(got) == 6
