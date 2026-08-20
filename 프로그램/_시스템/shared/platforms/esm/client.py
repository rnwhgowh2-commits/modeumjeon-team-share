# -*- coding: utf-8 -*-
"""ESM 2.0(옥션·G마켓) HTTP 클라이언트 — JWT 인증·rate limit·재시도.

주문조회는 "5초당 1회" 제한이라 요청 간 최소 간격(order_min_interval_sec)을 강제한다.
config = shared.platforms.AUCTION | GMARKET (base_url·master_id·secret_key·site_id·seller_id·paths).
"""
from __future__ import annotations

import logging
import threading
import time

from .auth import build_headers

logger = logging.getLogger(__name__)

# ★ 주문조회 5초/1회 스로틀은 **계정 단위**로 프로세스 전역 공유한다.
#   인스턴스 안에만 기억하면, 백필처럼 창마다 새 클라이언트를 만드는 경로가
#   창 사이 간격 0 으로 연타해 ResultCode 3000 이 난다(2026-07-22 재백필 실측:
#   G마켓 창 30개 연속 실패). 제한은 판매자 계정별 → 키=계정 식별자(계정 간 병렬 안전).
#
# ★★ 프로세스 전역만으로는 부족하다 — gunicorn 워커가 3개(별도 프로세스)라
#   인메모리 dict 를 공유 못 한다. 주문화면·배송검사·자동전환이 서로 다른 워커에서
#   같은 계정을 5초 내 부르면 3000 → 그 계정이 화면에서 통째로 빠짐('불러오지 못했어요').
#   그래서 '다음 허용 시각'을 **DB 한 행**에 두고 워커·프로세스·인스턴스가 공유한다.
#   _ORDER_LOCK 은 이제 **프로세스 안 스레드 직렬화**(+ SQLite 쓰기 경쟁 방지)용이고,
#   프로세스 간 직렬화는 DB 행 잠금이 한다. DB 불가 시 인메모리로 폴백(현행 동작 유지).
_ORDER_LAST_CALL: dict = {}
_ORDER_LOCK = threading.Lock()
_THROTTLE_TABLE_READY = False
_THROTTLE_TABLE_LOCK = threading.Lock()


def _ensure_order_throttle_table() -> None:
    """esm_order_throttle 테이블을 멱등 생성. 프로세스당 1회만 시도(캐시).

    부팅 마이그레이션과 별개로 자기충족 — 마이그레이션이 안 돌았어도(테스트 등)
    동작한다. 실패하면 조용히 넘어가고 호출부가 인메모리로 폴백한다.
    """
    global _THROTTLE_TABLE_READY
    if _THROTTLE_TABLE_READY:
        return
    with _THROTTLE_TABLE_LOCK:
        if _THROTTLE_TABLE_READY:
            return
        from shared.db import engine
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS esm_order_throttle ("
                "throttle_key TEXT PRIMARY KEY, "
                "next_slot_epoch DOUBLE PRECISION NOT NULL DEFAULT 0)"))
        _THROTTLE_TABLE_READY = True


def _reserve_order_slot_db(key_str: str, gap: float, now: float) -> float:
    """DB(공유상태)에 다음 슬롯을 원자적으로 예약하고 그 시각(epoch)을 돌려준다.

    INSERT ... DO NOTHING 으로 행을 보장한 뒤, UPDATE ... RETURNING 으로 예약값을
    앞당긴다(next = max(now, 기존 + gap)). PG 는 행 잠금이 워커를 직렬화하고,
    SQLite 는 호출부의 _ORDER_LOCK 이 프로세스 안 스레드를 직렬화한다(단일 프로세스).
    """
    _ensure_order_throttle_table()
    from shared.db import engine
    from sqlalchemy import text
    fn = "GREATEST" if engine.dialect.name == "postgresql" else "MAX"
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO esm_order_throttle (throttle_key, next_slot_epoch) "
            "VALUES (:k, 0) ON CONFLICT (throttle_key) DO NOTHING"), {"k": key_str})
        val = conn.execute(text(
            f"UPDATE esm_order_throttle "
            f"SET next_slot_epoch = {fn}(:now, next_slot_epoch + :gap) "
            f"WHERE throttle_key = :k RETURNING next_slot_epoch"),
            {"now": now, "gap": gap, "k": key_str}).scalar()
    return float(val)


class EsmClient:
    def __init__(self, config: dict):
        self._cfg = dict(config or {})
        self.base_url = (self._cfg.get("base_url") or "https://sa2.esmplus.com").rstrip("/")

    def _throttle_key(self) -> tuple:
        return (self._cfg.get("master_id", ""), self._cfg.get("seller_id", ""),
                self._cfg.get("site_id", ""))

    # ── 인증 ──
    def _headers(self) -> dict:
        return build_headers(
            self._cfg.get("master_id", ""),
            self._cfg.get("secret_key", ""),
            self._cfg.get("site_id", ""),
            self._cfg.get("seller_id", ""),
            issuer=self._cfg.get("auth_issuer", "www.esmplus.com"),
            audience=self._cfg.get("auth_audience", "sa.esmplus.com"),
            iat=int(time.time()),
        )

    def _throttle_orders(self) -> None:
        """주문조회 5초당 1회 — 발사 시점에 자리를 '예약'하고 그때까지 기다린다.

        ★ 이 제한은 RequestOrders 와 PreRequestOrders(입금확인중)가 **같이 쓴다**
          (라이브 실측 2026-07-20: 주문조회 직후 입금확인중 호출 → ResultCode 3000).
          제한은 판매자 계정별이므로 계정 간 병렬은 안전하다.
        ★ '응답 받은 뒤 기록' 방식은 첫 호출이 끝나기 전에 들어온 두 번째 스레드가
          간격 0 으로 통과했다(주문화면·배송검사·자동전환이 같은 계정을 동시에 부르는
          실사례 → 3000). 예약을 잠금 안에서 먼저 해야 동시 진입이 직렬화된다.
        """
        gap = float(self._cfg.get("order_min_interval_sec", 5))
        key_str = "|".join(str(x) for x in self._throttle_key())
        # ★ epoch(time.time) 을 쓴다 — monotonic 은 프로세스마다 원점이 달라 DB 로 공유 불가.
        now = time.time()
        with _ORDER_LOCK:                       # 프로세스 안 스레드 직렬화(+SQLite 쓰기 경쟁 방지)
            try:
                start = _reserve_order_slot_db(key_str, gap, now)   # 프로세스 간 공유(DB 행)
            except Exception as e:              # noqa: BLE001 — DB 불가 시 조회가 멈추면 안 된다
                logger.warning("[esm] 주문조회 DB 스로틀 실패, 인메모리 폴백: %s", e)
                start = max(now, _ORDER_LAST_CALL.get(key_str, 0.0) + gap)
                _ORDER_LAST_CALL[key_str] = start
        if start > now:
            time.sleep(start - now)

    def post(self, path: str, body: dict, *, is_order: bool = False) -> dict:
        """POST {base}{path} (JSON) → JSON. 5xx/네트워크는 지수백오프 재시도.

        주문조회(is_order)는 HTTP 200 + ResultCode 3000(호출 제한)도 재시도한다 —
        gunicorn 워커가 3개라 프로세스끼리는 5초 간격을 공유하지 못하고, 자동전환·
        배송검사와 겹치면 일시적으로 3000 이 난다. 즉시 실패로 굳히면 그 계정만
        화면에서 통째로 빠진다(간헐 '불러오지 못했어요'의 원인).
        """
        import random
        import requests

        if not path:
            raise ValueError("ESM 엔드포인트 경로 미설정 — 스펙 미확보(추측 금지)")
        url = self.base_url + path
        retries = int(self._cfg.get("max_retries", 3))
        backoff = float(self._cfg.get("retry_backoff_sec", 2))
        timeout = float(self._cfg.get("request_timeout_sec", 30))
        gap = float(self._cfg.get("order_min_interval_sec", 5))
        last_exc = None
        for attempt in range(retries):
            if is_order:
                self._throttle_orders()
            rate_limited = False
            try:
                resp = requests.post(url, json=body, headers=self._headers(), timeout=timeout)
                if resp.status_code >= 500:
                    raise RuntimeError(f"ESM {resp.status_code} 서버오류")
                resp.raise_for_status()
                data = resp.json()
                if is_order and isinstance(data, dict) and data.get("ResultCode") == 3000:
                    rate_limited = True
                    raise RuntimeError(
                        f"ESM 호출제한 ResultCode=3000 {data.get('Message') or ''}".strip())
                return data
            except Exception as e:  # noqa: BLE001 — 재시도 대상. 마지막 실패는 전파.
                last_exc = e
                logger.warning("[esm] POST %s 실패(%d/%d): %s", path, attempt + 1, retries, e)
                if attempt < retries - 1:
                    if rate_limited:
                        # 제한 간격만큼 비켜서 재시도 + 지터(다른 프로세스와 위상 겹침 방지)
                        time.sleep(gap + random.uniform(0.3, 1.5))
                    else:
                        time.sleep(backoff * (attempt + 1))
        raise last_exc

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        """GET/PUT/POST {base}{path} (JSON) → JSON. 상품/가격/재고 API 용.

        주문 rate limit(5초/1회)은 적용하지 않는다(그 제한은 주문조회 전용).
        5xx/네트워크는 지수백오프 재시도, 마지막 실패는 전파(추측·폴백 금지).
        롯데온 client.request 시그니처와 동일 — Fake 클라이언트로 단위테스트 가능.
        """
        import requests

        if not path:
            raise ValueError("ESM 엔드포인트 경로 미설정 — 스펙 미확보(추측 금지)")
        url = self.base_url + path
        retries = int(self._cfg.get("max_retries", 3))
        backoff = float(self._cfg.get("retry_backoff_sec", 2))
        timeout = float(self._cfg.get("request_timeout_sec", 30))
        last_exc = None
        for attempt in range(retries):
            try:
                resp = requests.request(method.upper(), url, json=body,
                                        headers=self._headers(), timeout=timeout)
                if resp.status_code >= 500:
                    raise RuntimeError(f"ESM {resp.status_code} 서버오류")
                resp.raise_for_status()
                return resp.json()
            except Exception as e:  # noqa: BLE001 — 재시도 대상. 마지막 실패는 전파.
                last_exc = e
                logger.warning("[esm] %s %s 실패(%d/%d): %s",
                               method.upper(), path, attempt + 1, retries, e)
                if attempt < retries - 1:
                    time.sleep(backoff * (attempt + 1))
        raise last_exc

    def request_orders(self, body: dict) -> dict:
        """주문조회(RequestOrders) — 5초 rate limit 적용."""
        path = (self._cfg.get("paths") or {}).get("orders")
        return self.post(path, body, is_order=True)

    def request_settlement(self, body: dict) -> dict:
        """판매대금 정산조회(getsettleorder)."""
        path = (self._cfg.get("paths") or {}).get("settlement")
        return self.post(path, body)
