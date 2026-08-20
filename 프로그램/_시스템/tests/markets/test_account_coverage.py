# -*- coding: utf-8 -*-
"""계정 커버리지 — 등록해 뒀는데 주문이 하나도 안 들어오는 계정 찾기.

2026-07-24 실측: 11번가 브랜드웨이 계정을 등록하기 전에는 그 계정 주문이
경고 한 줄 없이 통째로 안 보였다. 최소한 「조용한 계정」은 드러내야 한다.
"""
from lemouton.markets import account_coverage as ac


def _patch(monkeypatch, registered, rows, markets=("eleven11",)):
    from lemouton.markets import order_export as oe, order_store as os_
    monkeypatch.setattr(oe, "supported_markets", lambda: set(markets))
    monkeypatch.setattr(oe, "_active_accounts",
                        lambda m: [(f"P{i}", n) for i, n in enumerate(registered)])
    monkeypatch.setattr(os_, "load", lambda *a, **k: rows)


def test_주문이_안_들어온_계정을_찾아낸다(monkeypatch):
    _patch(monkeypatch, ["브랜드타임", "브랜드웨이"],
           [{"쇼핑몰별칭": "브랜드타임(11번가)"}])
    got = ac.survey()
    assert got["silent_total"] == 1
    assert got["markets"][0]["silent"] == ["브랜드웨이"]


def test_마켓이름_괄호가_붙어도_같은_계정으로_본다(monkeypatch):
    """'브랜드타임' 과 '브랜드타임(11번가)' 를 다르게 보면 멀쩡한 계정이 잘못 잡힌다."""
    _patch(monkeypatch, ["브랜드타임"], [{"쇼핑몰별칭": "브랜드타임(11번가)"}])
    assert ac.survey()["silent_total"] == 0


def test_전부_들어오면_조용한_계정이_없다(monkeypatch):
    _patch(monkeypatch, ["가", "나"],
           [{"쇼핑몰별칭": "가"}, {"쇼핑몰별칭": "나"}])
    assert ac.survey()["silent_total"] == 0


def test_등록이_아예_없는_마켓은_말하지_않는다(monkeypatch):
    """등록을 안 했으면 조용한 게 당연하다 — 경고할 일이 아니다."""
    _patch(monkeypatch, [], [])
    got = ac.survey()
    assert got["markets"] == [] and got["silent_total"] == 0


def test_별칭이_빈_행은_계정으로_치지_않는다(monkeypatch):
    """빈 별칭을 '봤다'로 치면 조용한 계정을 놓친다."""
    _patch(monkeypatch, ["브랜드웨이"], [{"쇼핑몰별칭": ""}, {"쇼핑몰별칭": None}])
    assert ac.survey()["markets"][0]["silent"] == ["브랜드웨이"]
