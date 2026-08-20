"""rarely-changing 참조(설정성) 데이터용 워커별 TTL 캐시.

get_cached_badge_counts 와 동일 패턴(워커별·monotonic·짧은 TTL).
★ 원칙: 가격·재고·혜택 같은 '실시간/정확성' 데이터엔 절대 쓰지 말 것.
  관리자가 가끔만 바꾸는 설정 데이터(소싱처 레지스트리·마켓 목록 등)에만 사용.
  반드시 plain 데이터(dict/list/tuple)만 캐시 — ORM 객체 캐시 금지(세션 분리 문제).
"""
import time as _time

_store: dict = {}


def cached(key: str, ttl: float, loader):
    """key 의 캐시가 ttl(초) 내면 그대로, 아니면 loader() 실행해 갱신 후 반환."""
    now = _time.monotonic()
    e = _store.get(key)
    if e is not None and (now - e[0]) < ttl:
        return e[1]
    val = loader()
    _store[key] = (now, val)
    return val


def invalidate(key: str = None) -> None:
    """key 캐시 무효화(None 이면 전체). 설정 변경 직후 즉시 반영시키고 싶을 때 호출."""
    if key is None:
        _store.clear()
    else:
        _store.pop(key, None)
