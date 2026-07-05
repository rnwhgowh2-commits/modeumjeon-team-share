"""마켓별 업로드 속도 제한 — 순수 계산 + 정책 읽기.

너무 빨리 올려 판매처가 막는 걸 방지. 실제 전송·전송기록은 P4b.
"""


def upload_allowance(per_minute: int, sent_last_minute: int) -> int:
    """지금 이 마켓에 몇 개 더 보내도 되나. 음수 없음."""
    return max(0, int(per_minute) - int(sent_last_minute))


def throttle_take(items: list, allowance: int) -> tuple[list, list]:
    """목록을 (지금 보낼, 나중에) 로 나눔. allowance 개만 지금."""
    n = max(0, int(allowance))
    return items[:n], items[n:]


def market_send_allowance(session, market: str, sent_last_minute: int) -> int:
    """정책을 읽어 이 마켓의 현재 허용량. enabled 아니거나 정책 없으면 0."""
    from lemouton.pricing.settings import get_market_policies
    pol = get_market_policies(session).get(market)
    if not pol or not pol.get("enabled"):
        return 0
    return upload_allowance(pol["per_minute"], sent_last_minute)


def seconds_to_hourly(seconds_per_item) -> int:
    """1개당 초 → 시간당 개수. 0 이하는 1초로 방어."""
    return 3600 // max(1, int(seconds_per_item))


def market_hourly_total(session, market: str) -> int:
    """마켓의 켜진(enabled·활성) 계정들 시간당 개수 합 = 총 스토어 업로드수."""
    from lemouton.pricing.settings import get_account_policies
    return sum(p["per_hour"] for p in get_account_policies(session)
               if p["market"] == market and p["enabled"])
