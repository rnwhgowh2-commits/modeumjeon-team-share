"""_SingleFlightTTLCache — 8초 TTL + 싱글플라이트(폭주 차단) + 키별 슬롯 단위 테스트.

라이브 장애(2026-07-12): 폴링 엔드포인트가 캐시 만료 순간 여러 스레드에서 동시에
무거운 계산을 돌려 DB·워커를 마비시켰다. 이 캐시는 (1) 신선하면 producer 미호출,
(2) 만료+직전값 있으면 한 스레드만 갱신·나머지는 stale, (3) 값 없으면 1회만 채운다.
(4) key 별 슬롯 — 실행/정지 토글 같은 상태를 key 에 실으면 상태가 바뀌는 즉시
   다른 슬롯을 봐서 stale 교차 오염이 없다.
"""
import threading

from webapp.routes.api import _SingleFlightTTLCache


def test_fresh_hit_calls_producer_once():
    c = _SingleFlightTTLCache(ttl=100.0)
    calls = {"n": 0}

    def prod():
        calls["n"] += 1
        return {"v": calls["n"]}

    first = c.get("k", prod)
    for _ in range(50):
        assert c.get("k", prod) == first     # 전부 캐시 히트
    assert calls["n"] == 1                    # producer 딱 1회


def test_empty_cache_fills_once():
    c = _SingleFlightTTLCache(ttl=100.0)
    assert c.get("k", lambda: {"v": 1}) == {"v": 1}


def test_distinct_keys_do_not_cross_contaminate():
    """★ 다른 key 는 서로 다른 슬롯 — 한 상태(enabled)의 값이 다른 상태로 새지 않는다.

    라이브/테스트 버그의 핵심: 단일값 캐시는 enabled=True 페이로드를 enabled=False
    요청에 그대로 줬다. key 분리로 상태 토글이 지연 없이 정확히 반영된다.
    """
    c = _SingleFlightTTLCache(ttl=100.0)
    assert c.get(True, lambda: {"enabled": True}) == {"enabled": True}
    # 같은 시간창(TTL 내)에 key=False 로 물으면 True 값이 아니라 새로 계산해야 한다
    assert c.get(False, lambda: {"enabled": False}) == {"enabled": False}
    # 각 key 는 자기 값을 캐시 유지
    assert c.get(True, lambda: {"enabled": "SHOULD_NOT_RUN"}) == {"enabled": True}
    assert c.get(False, lambda: {"enabled": "SHOULD_NOT_RUN"}) == {"enabled": False}


def test_expired_with_prior_value_serves_stale_when_locked():
    """만료 + 직전값 있음 + 다른 스레드가 갱신 중(락 보유) → stale 반환, producer 미호출."""
    c = _SingleFlightTTLCache(ttl=0.0)        # 즉시 만료
    c.entries["k"] = [0.0, {"v": "old"}]       # 아주 오래된 직전값
    calls = {"n": 0}

    def prod():
        calls["n"] += 1
        return {"v": "new"}

    # 다른 스레드가 갱신 중인 상황 재현 = 락을 미리 잡아둔다
    c.lock.acquire()
    try:
        # 만료됐지만 직전값이 있고 락을 못 잡으므로 stale 반환
        assert c.get("k", prod) == {"v": "old"}
        assert calls["n"] == 0                 # producer 안 불림(폭주 차단)
    finally:
        c.lock.release()

    # 락 풀린 뒤엔 정상 갱신
    assert c.get("k", prod) == {"v": "new"}
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

    threads = [threading.Thread(target=lambda: c.get("k", prod)) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls["n"] == 1
