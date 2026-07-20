# -*- coding: utf-8 -*-
"""프로브 안전장치 — 대상 화이트리스트·호출배수·안전마진·예산·킬스위치.

★ 지키는 선
  ① 가격은 어떤 경우에도 건드리지 않는다. 재고 필드만.
     (가격 오류 = 즉시 금전 손실. 프로젝트 대원칙)
  ② 여기 등재된 **테스트 상품** 외에는 절대 대상으로 삼지 않는다.
  ③ 측정 못 한 마켓은 비워 둔다. 추정값을 넣으면 나중에 확인된 값인 줄 알고 쓴다.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── 중단 장치 ────────────────────────────────────────────────────
STOP_FILE = Path(__file__).with_name("STOP")   # 이 파일을 만들면 즉시 멈춘다
DEFAULT_BUDGET = 2000                          # 마켓당 총 API 호출 상한
CONSECUTIVE_429_ABORT = 20                     # 429 연속 이 횟수면 중단
MARKET_GAP_SEC = 300                           # 마켓 전환 간격
BURST_REST_SEC = 120                           # 버스트 측정 전 완전 휴식

# ── 램프업 ───────────────────────────────────────────────────────
#   계단식으로 올린다. 이분탐색만 하면 첫 시도가 20 req/s 라 곧바로 차단당한다.
RAMP_STEPS = (0.2, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0)
HOLD_SEC = 30.0          # 각 계단 유지 시간
COOLDOWN_SEC = 60.0      # 계단 사이 휴식


class ProbeForbidden(RuntimeError):
    """화이트리스트 밖 대상·동작. 프로브는 여기서 멈춘다."""


# ── 테스트 대상 ──────────────────────────────────────────────────
# ★ 사장님이 마켓마다 만들어 주신 **판매중지·미노출** 상품만 여기 넣는다.
#   노출 상품에 ±1 토글을 하면 그 사이 주문이 들어와 없는 재고를 판다(오버셀).
#   비어 있는 마켓은 측정하지 않는다 — 추정값 금지.
TEST_TARGETS: dict[str, dict] = {
    # "coupang":    {"product_id": "", "option_id": ""},  # option_id = vendorItemId
    # "lotteon":    {"product_id": "", "option_id": ""},  # spdNo / sitmNo
    # "eleven11":   {"product_id": "", "option_id": ""},  # prdNo / stockNo
    # "smartstore": {"product_id": "", "option_id": ""},  # originProductNo / optionId
    # "auction":    {"product_id": "", "option_id": ""},  # goodsNo / optionId
    # "gmarket":    {"product_id": "", "option_id": ""},
}

# ── 호출배수 ─────────────────────────────────────────────────────
# 「1건 업로드」에 실제로 나가는 API 호출 수.
#   스스(edit_options)·ESM(update_stock) 은 현재값을 GET 한 뒤 전체를 PUT → 2콜.
#   근거: shared/platforms/smartstore/edit_product.py:49 · esm/inventory.py:57
#   ★ lemouton/uploader/throttle.py 의 _CALLS_PER_UPLOAD 와 값이 같아야 한다
#     (테스트 test_호출배수가_프로덕션_throttle_과_일치한다 가 고정).
_CALLS_PER_UPLOAD = {
    "coupang": 1,      # PUT .../vendor-items/{id}/quantities/{qty}
    "lotteon": 1,      # POST stock_change {itmStkLst:[...]}
    "eleven11": 1,     # update_stock_by_stock_no
    "smartstore": 2,   # GET 원상품 전체 → PUT 원상품 전체
    "auction": 2,      # GET recommended-options → PUT details 전체
    "gmarket": 2,
}


def assert_target_allowed(market: str, *, product_id: str, option_id: str) -> None:
    """이 상품·옵션을 건드려도 되는가. 아니면 ProbeForbidden."""
    t = TEST_TARGETS.get(market)
    if not t:
        raise ProbeForbidden(
            f"{market}: 테스트 상품 미등록 — 측정 불가(추정값 금지). "
            f"config.TEST_TARGETS 에 판매중지 상품을 등록하세요.")
    if str(product_id) != str(t["product_id"]) or str(option_id) != str(t["option_id"]):
        raise ProbeForbidden(
            f"{market}: 화이트리스트 밖 대상 product={product_id} option={option_id} "
            f"(허용: product={t['product_id']} option={t['option_id']})")


def calls_per_upload(market: str) -> int:
    """1건 업로드에 드는 API 호출 수."""
    if market not in _CALLS_PER_UPLOAD:
        raise ProbeForbidden(f"미등록 마켓: {market}")
    return _CALLS_PER_UPLOAD[market]


def safety_margin() -> float:
    """실측 상한에 곱할 안전계수.

    경계값을 그대로 제한장치에 넣으면 순간 지터로 429 가 난다.
    """
    return float(os.getenv("PROBE_SAFETY_MARGIN", "0.7"))


def budget_for(market: str) -> int:
    """이 마켓에 허용할 총 API 호출 수."""
    return int(os.getenv(f"PROBE_BUDGET_{market.upper()}", DEFAULT_BUDGET))


def stop_requested() -> bool:
    return STOP_FILE.exists()
