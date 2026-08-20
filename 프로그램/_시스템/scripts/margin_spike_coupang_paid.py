# -*- coding: utf-8 -*-
"""쿠팡 발주서 응답에 '실결제금액' 을 만들 수 있는 필드가 있는지 확인한다 (스펙 §4 미결).

배경
----
쿠팡 주문 API(ordersheets)는 실결제금액을 주지 않는다. 그래서 미정산 주문의
정산예정금액을 `(단가×수량 + 배송비) × 0.8845` 로 추정한다.
샵마인은 `실결제금액 × 0.8845` 를 쓴다. 계수(0.8845 = 1 − 0.1155)는 같지만
**곱하는 베이스가 다르다** — 쿠폰·즉시할인이 걸린 주문에서 값이 갈리고,
우리 쪽 추정이 과대해진다.

이 스크립트는 추측 대신 **실계정 응답을 열어 확인**한다.
  · 필드 있음  → 쿠팡 빌더에 실결제금액을 채우고 추정 베이스를 교체한다.
  · 필드 없음  → 없는 대로 둔다. 지어내지 않는다.

실행 위치 (중요)
--------------
마켓 API 는 **서버 IP 허용목록**에 묶여 있다(AWS 54.116.196.90).
로컬 PC 에서 실행하면 인증 이전에 IP 로 거부된다.
반드시 서버에서, 실계정 키가 로드된 환경에서 실행할 것.

    ssh <서버>
    cd <배포경로>/프로그램/_시스템
    python scripts/margin_spike_coupang_paid.py

출력
----
shipmentBox / orderItems 의 전체 키 목록 + 금액으로 보이는 후보 필드.
결과를 스펙 §4 '수정 2' 아래에 그대로 붙여넣고 결론을 적는다.
"""
import datetime as _dt
import json
import os
import sys

# `python scripts/margin_spike_coupang_paid.py` 로 직접 실행해도 lemouton/shared 를 찾도록.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KST = _dt.timezone(_dt.timedelta(hours=9))

# 금액·할인·결제로 읽히는 이름 조각. 넓게 잡는다 — 놓치는 것보다 노이즈가 낫다.
MONEY_HINTS = ("price", "Price", "amount", "Amount", "discount", "Discount",
               "paid", "Paid", "coupon", "Coupon", "pay", "Pay", "fee", "Fee")


def _sample_boxes(client, since, until, want=5):
    """발주서(shipmentBox) 표본 수집.

    ⚠ fetch_orders 는 리스트가 아니라 **dict** 를 돌려준다(`{"data": [...], "nextToken": ...}`).
    `list(fetch_orders(...))` 하면 dict 의 '키'를 순회하게 된다 — order_export.coupang_order_rows
    가 실제로 쓰는 방식(status 별 순회 + resp["data"])을 그대로 따른다.
    """
    from shared.platforms.coupang.orders import fetch_orders

    boxes = []
    for st in ("ACCEPT", "INSTRUCT", "DEPARTURE", "DELIVERING", "FINAL_DELIVERY"):
        resp = fetch_orders(since, until, client=client, status=st)
        for b in (resp.get("data") or []):
            boxes.append(b)
            if len(boxes) >= want:
                return boxes
    return boxes


def main() -> None:
    from lemouton.markets.order_export import _account_client

    client = _account_client("coupang")
    until = _dt.datetime.now(KST)
    since = until - _dt.timedelta(days=7)

    boxes = _sample_boxes(client, since, until)
    if not boxes:
        print("최근 7일 주문이 없습니다. 기간을 늘려 다시 실행하세요.")
        return

    box_keys, item_keys = set(), set()
    for b in boxes:
        box_keys |= set(b.keys())
        for it in b.get("orderItems", []):
            item_keys |= set(it.keys())

    print(f"표본 발주서 {len(boxes)}건\n")
    print("=== shipmentBox 키 ===")
    print(sorted(box_keys))
    print("\n=== orderItems 키 ===")
    print(sorted(item_keys))
    print("\n=== 금액 후보 (box) ===")
    print(sorted(k for k in box_keys if any(h in k for h in MONEY_HINTS)))
    print("\n=== 금액 후보 (item) ===")
    print(sorted(k for k in item_keys if any(h in k for h in MONEY_HINTS)))

    print("\n=== 첫 주문 원본 (금액 필드만) ===")
    b = boxes[0]
    print(json.dumps({k: v for k, v in b.items()
                      if any(h in k for h in MONEY_HINTS)},
                     ensure_ascii=False, indent=1))
    for it in b.get("orderItems", [])[:1]:
        print(json.dumps({k: v for k, v in it.items()
                          if any(h in k for h in MONEY_HINTS)},
                         ensure_ascii=False, indent=1))

    print("\n판정 기준:")
    print("  실결제금액 = (판매가 − 할인) 을 재구성할 수 있는 필드 조합이 있는가?")
    print("  있으면 → 쿠팡 빌더에 '실결제금액' 을 채우고 _cp_estimate_settle 베이스를 교체.")
    print("  없으면 → 스펙 §4 에 '<날짜> 실계정 확인, 필드 없음' 을 명시하고 현행 유지.")


if __name__ == "__main__":
    main()
