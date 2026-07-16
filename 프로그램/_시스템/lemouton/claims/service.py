"""CS 클레임 서비스 — 단계 파생 + 확인/메모 저장 + 목록 조인.

단계는 저장하지 않는다(스펙 §3). 종결(완료/철회)이면 항상 대응완료(확인 여부 무관 최우선).
"""
import datetime as _dt

from shared.db import SessionLocal
from lemouton.claims.models import ClaimHandling

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


def _get_or_create(session, claim_key, **defaults):
    row = session.query(ClaimHandling).filter_by(claim_key=claim_key).one_or_none()
    if row is None:
        row = ClaimHandling(claim_key=claim_key, **defaults)
        session.add(row)
    return row


def acknowledge(claim_key, *, market="", order_no="", claim_type="", session=None):
    """「확인」 처리 — acknowledged_at 설정(upsert). 이미 있으면 유지."""
    own = session is None
    session = session or SessionLocal()
    try:
        row = _get_or_create(session, claim_key, market=market, order_no=order_no, claim_type=claim_type)
        if row.acknowledged_at is None:
            row.acknowledged_at = _dt.datetime.now(_dt.timezone.utc)
        session.commit()
    finally:
        if own:
            session.close()


def save_memo(claim_key, memo, *, market="", order_no="", claim_type="", session=None):
    own = session is None
    session = session or SessionLocal()
    try:
        row = _get_or_create(session, claim_key, market=market, order_no=order_no, claim_type=claim_type)
        row.memo = memo
        session.commit()
    finally:
        if own:
            session.close()
