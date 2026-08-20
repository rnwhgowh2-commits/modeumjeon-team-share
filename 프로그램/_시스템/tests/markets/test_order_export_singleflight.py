# -*- coding: utf-8 -*-
"""combined_order_rows 단일비행 — 같은 (마켓,기간) 동시 조회는 실조회 1번만.

배경: 옥션·G마켓 미리보기는 5초/1콜 제한 때문에 ~60초가 걸려 게이트웨이가 끊기도
한다. 화면이 자동 재시도할 때 이미 진행 중인 같은 조회를 또 시작하면 ESM 호출
버킷을 두 배로 태워 더 느려진다 → 진행 중이면 그 결과를 기다렸다 같이 쓴다.
(크롤큐 폴링 폭주 때와 같은 single-flight 패턴.)
"""
import threading
import time

from lemouton.markets import order_export as oe


def _rows():
    return [{"주문일": "2026-07-22 10:00:00", "판매처": "쿠팡"}]


def test_같은키_동시조회는_실조회_한번(monkeypatch):
    oe.clear_cache()
    calls = []

    def fake_fetch(markets, days, now, since=None, until=None,
                   include_settlement=True, warnings=None):
        calls.append(1)
        time.sleep(0.3)                    # 실조회가 걸리는 동안 두 번째 요청 진입
        if warnings is not None:
            warnings.append("[쿠팡·A] 테스트 경고")
        return _rows()

    monkeypatch.setattr(oe, "_fetch_combined", fake_fetch)
    results, warns = [None, None], [[], []]

    def go(i):
        results[i] = oe.combined_order_rows(["coupang"], days=7, use_cache=True,
                                            warnings=warns[i])

    t0 = threading.Thread(target=go, args=(0,))
    t0.start()
    time.sleep(0.05)                       # 첫 요청이 빌더로 등록될 시간
    t1 = threading.Thread(target=go, args=(1,))
    t1.start()
    t0.join(); t1.join()
    assert len(calls) == 1, "동시 같은 조회가 실조회를 두 번 하면 ESM 버킷을 두 배로 태운다"
    assert results[0] == results[1] == _rows()
    assert warns[0] == warns[1] == ["[쿠팡·A] 테스트 경고"], "기다린 쪽도 경고를 받아야 한다(조용한 실패 금지)"


def test_빌더_실패시_기다리던_쪽이_직접_조회(monkeypatch):
    oe.clear_cache()
    calls = []

    def fake_fetch(markets, days, now, since=None, until=None,
                   include_settlement=True, warnings=None):
        calls.append(1)
        if len(calls) == 1:
            time.sleep(0.2)
            raise RuntimeError("첫 조회 실패(일시 오류)")
        return _rows()

    monkeypatch.setattr(oe, "_fetch_combined", fake_fetch)
    out = [None, None]

    def go_fail():
        try:
            oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=[])
        except RuntimeError:
            out[0] = "raised"

    def go_wait():
        out[1] = oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=[])

    t0 = threading.Thread(target=go_fail); t0.start()
    time.sleep(0.05)
    t1 = threading.Thread(target=go_wait); t1.start()
    t0.join(); t1.join(timeout=10)
    assert out[0] == "raised"
    assert out[1] == _rows(), "빌더가 실패하면 기다리던 요청이 직접 조회해야 한다(멈춤 금지)"
    assert len(calls) == 2
