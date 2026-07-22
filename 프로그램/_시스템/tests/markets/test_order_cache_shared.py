# -*- coding: utf-8 -*-
"""주문 캐시가 gunicorn 워커 간(프로세스 간) 공유되는지 — L2(DB) 캐시.

L1(프로세스 메모리)만 있으면 워커 3개가 각자 캐시해 같은 계정 주문을 최대 3번
재조회한다(ESM 5초 throttle 대기를 3배로 태움). '다음 허용 시각' throttle 수정
([[project_esm_order_throttle_crossproc_fix]])의 짝 — 조회 자체를 워커 간 공유해 줄인다.
"""
import lemouton.markets.order_export as oe


def _fake_rows(mk):
    return [{"주문일": "2026-07-22 00:00:00", "판매처": mk, "상품명": "X"}]


import pytest


@pytest.fixture(autouse=True)
def _reset_caches():
    """L1(인메모리) + L2(DB) 둘 다 비운다 — 테스트 간 오염 방지."""
    oe.clear_cache()
    try:
        from shared.db import engine
        from sqlalchemy import text
        with engine.begin() as c:
            c.execute(text("DELETE FROM order_rows_cache"))
    except Exception:
        pass
    yield
    oe.clear_cache()


def test_캐시가_워커_간_공유된다_L2(monkeypatch):
    """한 워커가 채운 캐시를, L1 을 비운 '다른 워커'가 실조회 없이 받는다."""
    n = {"fetch": 0}

    def _counting_order_rows(mk, **kw):
        n["fetch"] += 1
        return _fake_rows(mk)

    monkeypatch.setattr(oe, "order_rows", _counting_order_rows)

    w = []
    rows1 = oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=w)
    assert len(rows1) == 1 and n["fetch"] == 1        # 워커A: 실조회 1회 + 캐시 채움

    oe._CACHE.clear()                                 # 워커B: L1(프로세스 메모리)만 비움(=새 프로세스)

    w2 = []
    rows2 = oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=w2)
    assert len(rows2) == 1
    assert n["fetch"] == 1, "L1 을 비운 다른 워커가 재조회하면 L2(DB) 공유가 안 되는 것"


def test_L2_경고도_함께_되살린다(monkeypatch):
    """부분 실패 경고가 캐시에 저장·복원돼야 — 캐시 적중 때 경고가 사라지면 조용한 실패."""
    def _order_rows_with_warn(mk, warnings=None, **kw):
        if warnings is not None:
            warnings.append(f"[{mk}] 일부 계정 제외")
        return _fake_rows(mk)

    monkeypatch.setattr(oe, "order_rows", _order_rows_with_warn)

    w1 = []
    oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=w1)
    assert any("제외" in x for x in w1)

    oe.clear_cache()                                  # 다른 워커
    w2 = []
    oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=w2)
    assert any("제외" in x for x in w2), "L2 적중 때 경고가 사라지면 조용한 실패"
