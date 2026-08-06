# -*- coding: utf-8 -*-
"""마켓에 보낼 재고 수량을 정하는 단일 원천 (2026-08-06 사장님 확정).

왜 이 파일이 생겼나 — 실측한 사고
────────────────────────────────
「상품수집&전송」의 보내기 경로가 **모든 옵션에 재고 0(품절)** 을 보내고 있었다.
  · `scripts/verify_pipeline_dryrun.build_a_output_from_stored` 가 `boxhero_stock: 0`
    으로 고정(박스히어로 records 없이 산출 불가) — 그 값이 실전송 경로로 그대로 흘렀다.
  · `formatter/pipeline.run_formatter` 가 소싱처 크롤 재고(`sources`)를 갖고 있으면서도
    payload 빌더의 `external_stock_by_sku` 자리에 **한 번도 넘기지 않았다**.
  · 쿠팡·스마트스토어·롯데온 어댑터에는 0 차단 가드가 없다(ESM 만 유효범위로 막힘).
→ 무재고(소싱처에서 사서 보내는) 상품이 마켓에서 통째로 품절 처리될 수 있는 구조였다.

규칙 (사장님 확정)
────────────────────────────────
1. 보낼 재고 = **내 창고 재고 + 소싱처 크롤 재고** (있는 쪽이 나간다)
   · 무재고 상품 → 내 재고 0이어도 크롤 재고가 나간다 (품절 안 됨)
   · 사입 상품   → 소싱처 URL 이 없어도 내 재고가 나간다
   · 혼합        → 합산
2. **상한 100개** — 소싱처에 100개가 있어도 그 이상은 올리지 않는다(못 구할 위험).
3. 크롤 재고가 **확인 불가(None)** 면 0 으로 단정하지 않고 **전송 보류 + 알림**.
   (CLAUDE.md 데이터 정합성 원칙 ①: 확인 못 하면 "확인 불가", 있다고도 없다고도 단정 금지)

마켓 규격 참고 (판매처 데이터 코드 지도 전수정독, 2026-08-06)
────────────────────────────────
· ESM(옥션·G마켓): 재고 유효범위 **1~99,999 — 0 은 무효**. 품절은 재고 0 이 아니라
  `isSoldOutSite` 사이트별 플래그/판매중지로 표현한다(지도 과거이력: "ESM 재고 0 전송 =
  오버셀"). 상한 100 은 이 범위 안이라 안전하다.
· 쿠팡: PUT vendor-items/{vendorItemId}/quantities/{quantity}
· 롯데온: POST item/stock/change 의 stkQty
"""
from __future__ import annotations

#: 마켓에 올리는 옵션당 최대 재고 (사장님 확정 2026-08-06 — 주문 몰림 시 못 구할 위험 차단)
STOCK_CAP = 100

#: 보류 사유
HOLD_UNKNOWN = "unknown"      # 크롤 재고 확인 불가 — 0 으로 단정 금지


def resolve_send_stock(own_stock, source_stocks, *, cap: int = STOCK_CAP):
    """마켓에 보낼 재고를 정한다.

    Args:
        own_stock: 내 창고 재고(사입). None/음수는 0 취급.
        source_stocks: 소싱처별 크롤 재고 리스트. **None 원소 = 확인 불가**
            (미크롤·파싱실패). 빈 리스트 = 소싱처 매핑 없음(사입 전용 상품).
        cap: 상한. 기본 STOCK_CAP(100).

    Returns:
        (stock, reason)
          · (int, 'ok')       — 이 수량을 보낸다 (1 이상, cap 이하)
          · (None, 'unknown') — **전송 보류**. 확인 불가라 0 으로 단정하면 안 된다.
          · (0, 'soldout')    — 전부 확실히 0. 진짜 품절이므로 마켓에 반영한다.
                                (ESM 은 0 이 무효라 어댑터가 막고 실패로 표면화된다 —
                                 품절 플래그 경로는 별도 작업)
    """
    own = int(own_stock or 0)
    if own < 0:
        own = 0

    srcs = list(source_stocks or [])
    unknown = any(s is None for s in srcs)
    known_sum = sum(max(0, int(s)) for s in srcs if s is not None)

    total = own + known_sum
    if total >= 1:
        return min(total, cap), "ok"
    if unknown:
        # 내 재고도 0이고 크롤 재고를 모른다 → 품절이라고 단정하지 않는다
        return None, HOLD_UNKNOWN
    # 소싱처가 확실히 0 이거나(품절), 소싱처 자체가 없고 내 재고도 0
    return 0, "soldout"
