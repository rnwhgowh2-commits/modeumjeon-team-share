# -*- coding: utf-8 -*-
"""API 주문상태 → 샵마인 정산 어휘 번역 + config 버킷 귀속 검증.

핵심: 롯데온 철회/회수확정이 정산O 로 새지 않고 취소/반품으로 떨어져야 한다.
"""
from lemouton.margin import sell_source as S
from lemouton.margin import config as C


def _bucket(shopmine_status: str) -> str:
    """config 규칙으로 샵마인 문자열이 어느 정산 버킷인지 (테스트용 축약 판정)."""
    s = shopmine_status
    if s in C.SETTLEMENT_O_EXACT or s in C.SETTLEMENT_X_EXCEPT_TO_O:
        return "O"
    if any(k in s for k in C.SETTLEMENT_EXCHANGE_KEYWORDS):
        return "O"
    if any(tok in s for tok in ("반품", "회수", "환불", "수거")):
        return "반품"
    if any(k in s for k in C.SETTLEMENT_CANCEL_KEYWORDS) or "취소" in s:
        return "취소"
    if s in C.SETTLEMENT_X_EXACT:
        return "반품" if any(t in s for t in ("반품", "회수", "환불", "수거", "교환")) else "취소"
    return "O"


def test_lotteon_withdraw_is_cancel_not_settled():
    out = S.status_to_shopmine("롯데온", "철회")
    assert _bucket(out) == "취소", f"철회 → {out} (정산O 로 새면 안 됨)"


def test_lotteon_collect_confirmed_is_return_not_settled():
    out = S.status_to_shopmine("롯데온", "회수확정")
    assert _bucket(out) == "반품", f"회수확정 → {out} (정산O 로 새면 안 됨)"


def test_pinned_values_land_in_settled():
    assert _bucket(S.status_to_shopmine("롯데온", "발송완료")) == "O"
    assert _bucket(S.status_to_shopmine("옥션", "구매결정")) == "O"
    assert _bucket(S.status_to_shopmine("쿠팡", "업체직접배송")) == "O"


def test_identity_values_keep_correct_bucket():
    assert _bucket(S.status_to_shopmine("스마트스토어", "배송완료")) == "O"
    assert _bucket(S.status_to_shopmine("쿠팡", "결제완료")) == "O"
    assert _bucket(S.status_to_shopmine("11번가", "취소완료")) == "취소"
    assert _bucket(S.status_to_shopmine("스마트스토어", "반품완료")) == "반품"
    assert _bucket(S.status_to_shopmine("롯데온", "회수지시")) == "반품"


def test_exchange_stays_settled_like_original():
    assert _bucket(S.status_to_shopmine("스마트스토어", "교환완료")) == "O"
    assert _bucket(S.status_to_shopmine("11번가", "교환요청")) == "O"


def test_unknown_passes_through():
    assert S.status_to_shopmine("스마트스토어", "듣도보도못한상태") == "듣도보도못한상태"
    assert S.status_to_shopmine("스마트스토어", "") == ""
    assert S.status_to_shopmine("", "배송완료") == "배송완료"


def test_all_known_values_return_string():
    vocab = ["결제대기","결제완료","상품준비중","상품준비","출고지시","배송준비중",
             "배송지시","배송중","발송완료","배송완료","업체직접배송","구매확정",
             "구매결정","수취완료","취소요청","취소완료","철회","회수지시","회수진행",
             "회수완료","회수확정","반품요청","반품완료","교환요청","교환완료"]
    for mk in ("스마트스토어","쿠팡","롯데온","11번가","옥션","G마켓"):
        for v in vocab:
            out = S.status_to_shopmine(mk, v)
            assert isinstance(out, str) and out
