"""_SingleFlightTTLCache — 8초 TTL + 싱글플라이트(폭주 차단) 단위 테스트.

라이브 장애(2026-07-12): 폴링 엔드포인트가 캐시 만료 순간 여러 스레드에서 동시에
무거운 계산을 돌려 DB·워커를 마비시켰다. 이 캐시는 (1) 신선하면 producer 미호출,
(2) 만료+직전값 있으면 한 스레드만 갱신·나머지는 stale, (3) 값 없으면 1회만 채운다.
"""
import threading

from webapp.routes.api import _SingleFlightTTLCache


def test_fresh_hit_calls_producer_once():
    c = _SingleFlightTTLCache(ttl=100.0)
    calls = {"n": 0}

    def prod():
        calls["n"] += 1
        return {"v": calls["n"]}

    first = c.get(prod)
    for _ in range(50):
        assert c.get(prod) == first          # 전부 캐시 히트
    assert calls["n"] == 1                    # producer 딱 1회


def test_empty_cache_fills_once():
    c = _SingleFlightTTLCache(ttl=100.0)
    assert c.get(lambda: {"v": 1}) == {"v": 1}


def test_expired_with_prior_value_serves_stale_when_locked():
    """만료 + 직전값 있음 + 다른 스레드가 갱신 중(락 보유) → stale 반환, producer 미호출."""
    c = _SingleFlightTTLCache(ttl=0.0)        # 즉시 만료
    c.payload = {"v": "old"}
    c.at = 0.0                                 # 아주 오래된 것으로
    calls = {"n": 0}

    def prod():
        calls["n"] += 1
        return {"v": "new"}

    # 다른 스레드가 갱신 중인 상황 재현 = 락을 미리 잡아둔다
    c.lock.acquire()
    try:
        # 만료됐지만 직전값이 있고 락을 못 잡으므로 stale 반환
        assert c.get(prod) == {"v": "old"}
        assert calls["n"] == 0                 # producer 안 불림(폭주 차단)
    finally:
        c.lock.release()

    # 락 풀린 뒤엔 정상 갱신
    assert c.get(prod) == {"v": "new"}
    assert calls["n"] == 1


def test_concurrent_first_fill_calls_producer_once():
    """빈 캐시에 다수 스레드 동시 진입해도 producer 는 1회만(락 직렬화)."""
    c = _SingleFlightTTLCache(ttl=100.0)
    calls = {"n": 0}
    lock = threading.Lock()

    def prod():
        with lock:
            calls["n"] += 1
        return {"v": 1}

    threads = [threading.Thread(target=lambda: c.get(prod)) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls["n"] == 1
