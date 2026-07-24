# -*- coding: utf-8 -*-
"""야간 전체 훑기 — 기본은 꺼져 있고, 켜야 돈다.

★ 기본 ON 으로 두면 배포하자마자 6마켓 36계정에 2,700 호출이 나간다.
  마켓 한도에 걸릴 수 있으니 사장님이 켜는 순간에만 돈다.
"""


def test_기본은_꺼져_있다(monkeypatch):
    from scheduler import main as M
    monkeypatch.delenv('MOUM_CATALOG_SYNC_HOUR', raising=False)
    assert M._catalog_sync_hour() is None


def test_시각을_주면_그_시각에_돈다(monkeypatch):
    from scheduler import main as M
    monkeypatch.setenv('MOUM_CATALOG_SYNC_HOUR', '3')
    assert M._catalog_sync_hour() == 3


def test_0시도_켜진_것이다(monkeypatch):
    """★ 0 을 '꺼짐'으로 읽으면 자정 동기화가 조용히 안 돈다."""
    from scheduler import main as M
    monkeypatch.setenv('MOUM_CATALOG_SYNC_HOUR', '0')
    assert M._catalog_sync_hour() == 0


def test_이상한_값은_꺼진_것으로(monkeypatch):
    from scheduler import main as M
    monkeypatch.setenv('MOUM_CATALOG_SYNC_HOUR', '새벽세시')
    assert M._catalog_sync_hour() is None
    monkeypatch.setenv('MOUM_CATALOG_SYNC_HOUR', '99')
    assert M._catalog_sync_hour() is None
    monkeypatch.setenv('MOUM_CATALOG_SYNC_HOUR', '-1')
    assert M._catalog_sync_hour() is None
    monkeypatch.setenv('MOUM_CATALOG_SYNC_HOUR', '  ')
    assert M._catalog_sync_hour() is None
