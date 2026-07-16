"""CS 클레임 서비스 — 단계 파생 + 확인/메모 저장 + 목록 조인.

단계는 저장하지 않는다(스펙 §3). 종결(완료/철회)이면 항상 대응완료(확인 여부 무관 최우선).
"""
_TYPES = ("취소", "교환", "반품")


def claim_type_of(row) -> str:
    st = str(row.get("주문상태") or "")
    for t in _TYPES:
        if st.startswith(t):
            return t
    return ""


def claim_key_of(row) -> str:
    return f'{row.get("판매처","")}:{row.get("오픈마켓주문번호","")}:{claim_type_of(row)}'


def is_terminal(row) -> bool:
    """종결 = 완료 또는 철회. 철회는 마켓별 원본코드로 감지(라벨 미부여이므로)."""
    st = str(row.get("주문상태") or "")
    if st.endswith("완료"):
        return True
    raw = str(row.get("주문상태원본") or "")
    mk = row.get("판매처")
    if mk in ("롯데온", "11번가") and raw == "22":   # odPrgsStepCd/ordPrdStat 22=철회
        return True
    if mk == "쿠팡" and raw == "CANCEL":             # exchangeStatus CANCEL=철회
        return True
    return False


def claim_state_of(row) -> str:
    if str(row.get("주문상태") or "").endswith("완료"):
        return "완료"
    if is_terminal(row):
        return "철회"
    return "요청"


def derive_stage(row, acknowledged: bool) -> str:
    if is_terminal(row):
        return "대응완료"
    return "대응필요" if acknowledged else "신규요청"
