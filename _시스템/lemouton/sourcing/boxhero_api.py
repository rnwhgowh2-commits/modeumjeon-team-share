"""박스히어로 Open API 클라이언트.

API 문서: https://rest.boxhero-app.com/docs/api
요금 제한: Endpoint별 5 QPS — 429 응답 시 Retry-After 헤더 기반 백오프.

현재 read-only 사용 (list_items)만 구현 (YAGNI).
추후 update_quantity 등은 필요 시 추가.
"""
import time
from typing import Iterator

import requests

BASE_URL = "https://rest.boxhero-app.com"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3


class BoxHeroClient:
    """박스히어로 Open API 클라이언트 (Bearer 토큰 인증)."""

    def __init__(self, token: str, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def list_items(self, page_size: int = 100) -> Iterator[dict]:
        """모든 아이템을 cursor 기반 페이지네이션으로 yield.

        Yields:
            dict: API가 반환하는 item 객체 원형. 키 예시:
                  sku, barcode, name, brand, modelName, size,
                  currentQuantity, purchasePrice 등.
        """
        cursor = None
        while True:
            params = {"limit": page_size}
            if cursor:
                params["cursor"] = cursor

            resp = self._get_with_retry("/v1/items", params=params)
            data = resp.json()
            for item in data.get("items", []):
                yield item
            cursor = data.get("nextCursor")
            if not cursor:
                break

    def _get_with_retry(self, path: str, **kwargs) -> requests.Response:
        """GET 요청 + 429/5xx 자동 재시도.

        - 429: Retry-After 헤더(초) 만큼 sleep 후 재시도 (재시도 횟수 미차감 — 정상 백오프).
        - 5xx: 지수 백오프 (1, 2, 4초).
        """
        url = f"{self.base_url}{path}"
        last_resp: requests.Response | None = None
        for attempt in range(MAX_RETRIES):
            resp = requests.get(
                url,
                headers=self.headers,
                timeout=DEFAULT_TIMEOUT,
                **kwargs,
            )
            last_resp = resp
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "1"))
                time.sleep(retry_after)
                continue
            if resp.status_code >= 500 and attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp

        # 모든 재시도 소진
        assert last_resp is not None
        last_resp.raise_for_status()
        return last_resp
