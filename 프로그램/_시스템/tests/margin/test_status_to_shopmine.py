# -*- coding: utf-8 -*-
"""API 주문상태 → 샵마인 정산 어휘 번역 + config 버킷 귀속 검증.

핵심: 롯데온 철회/회수확정이 정산O 로 새지 않고 취소/반품으로 떨어져야 한다.
"""
from lemouton.margin import sell_source as S
from lemouton.margin import classifier as CL


# ✅ 플랜 B 완료 — _bucket 은 이제 실제 classifier._determine_settlement_status 를 호출한다.
#   (이전의 config 근사 프록시를 폐기.) 샵마인 문자열 하나를 매칭된 행으로 감싸
#   실 정산 판정 → 취소/반품/O 로 환원. classifier 와 정확히 같은 축으로 검증된다.
_SETTLE_MAP = {"O": "O", "X_취소": "취소", "X_반품": "반품", "X_미매칭": "미매칭"}


def _bucket(shopmine_status: str) -> str:
    """실 classifier 로 샵마인 문자열이 어느 정산 버킷인지 판정."""
    row = {"샵마인_매칭": True, "샵마인_정상건존재": False, "샵마인_주문상태": shopmine_status}
    return _SETTLE_MAP[CL._determine_settlement_status(row)]


def test_lotteon_withdraw_is_cancel_not_settled():
    # raw 철회 는 config 상 정산O 로 샘 (이 remap 이 존재하는 이유)
    assert _bucket("철회") == "O"
    out = S.status_to_shopmine("롯데온", "철회")
    assert _bucket(out) == "취소", f"철회 → {out}"


def test_lotteon_collect_confirmed_is_return_not_settled():
    # 정밀 재검증(플랜 B): raw "회수확정" 은 실 classifier 에서 O(정산됨) 로 '샌다'.
    #   ("회수확정" 은 X_EXACT 에도 없고 RETURN 키워드("회수지시/완료/진행/중")와도
    #    부분매칭되지 않아 기본값 O 로 떨어진다.) → remap 이 반드시 필요한 이유.
    assert _bucket("회수확정") == "O", "raw 회수확정 이 O 로 새지 않으면 remap 전제가 바뀐 것"
    out = S.status_to_shopmine("롯데온", "회수확정")
    assert _bucket(out) == "반품", f"회수확정 → {out}"  # remap 후 반품으로 교정


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
