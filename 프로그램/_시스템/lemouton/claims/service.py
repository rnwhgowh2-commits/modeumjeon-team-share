"""CS 클레임 서비스 — 단계 파생 + 확인/메모 저장 + 목록 조인.

단계는 저장하지 않는다(스펙 §3). 종결(완료/철회)이면 항상 대응완료(확인 여부 무관 최우선).
"""
import datetime as _dt
import re as _re_cs

from shared.db import SessionLocal
from lemouton.claims.models import ClaimHandling
from lemouton.markets.order_export import status_change_rows

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
    if mk == "롯데온" and raw == "22":   # odPrgsStepCd 22=철회 (라이브 확인됨)
        return True
    # 11번가 철회 코드는 미확인 — 라이브 검증 필요(스펙 §4.1). 확인 전엔 미감지(요청 상태 유지).
    if mk == "쿠팡" and claim_type_of(row) == "교환" and raw == "CANCEL":   # exchangeStatus CANCEL=철회 (교환만)
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
    return "대응중" if acknowledged else "신규요청"


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


def _ymd(s):
    """'_change_date' 등 문자열에서 YYYY-MM-DD(구분자 유무 무관)를 뽑아 date로."""
    m = _re_cs.search(r"(\d{4})[-./]?(\d{2})[-./]?(\d{2})", str(s or ""))
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def dismiss_claim(claim_key, *, market="", order_no="", claim_type="", session=None):
    """수기 삭제 — dismissed_at 설정(upsert). 대응완료 목록서 숨김."""
    own = session is None
    session = session or SessionLocal()
    try:
        row = _get_or_create(session, claim_key, market=market, order_no=order_no, claim_type=claim_type)
        row.dismissed_at = _dt.datetime.now(_dt.timezone.utc)
        session.commit()
    finally:
        if own:
            session.close()


_STAGES = ("신규요청", "대응중", "대응완료")


def _claim_view(row, ack):
    return {
        "판매처": row.get("판매처", ""),
        "오픈마켓주문번호": row.get("오픈마켓주문번호", ""),
        "유형": claim_type_of(row),
        "상태": claim_state_of(row),
        "상품명": row.get("상품명", ""),
        "옵션": row.get("옵션", ""),
        "수량": row.get("수량", ""),
        "사유": row.get("배송메시지", ""),
        "변경일": row.get("_change_date", ""),
        # 구매자 정보(#4) — 마켓별로 채워지는 만큼 노출(없으면 빈칸 → 카드서 「정보 없음」).
        #  이름=구매자(없으면 수령자) / 연락처=수령자전화(없으면 구매자번호) / 주소=배송·회수지.
        "구매자": row.get("구매자") or row.get("수령자") or "",
        "연락처": row.get("수령자전화번호") or row.get("구매자번호") or "",
        "주소": row.get("주소") or "",
        "claim_key": claim_key_of(row),
        "메모": (ack.memo if ack else "") or "",
        "단계": derive_stage(row, acknowledged=bool(ack and ack.acknowledged_at)),
    }


_RETENTION_DAYS = 7


def list_claims(markets, *, since, until, now=None, session=None):
    """status_change_rows + ClaimHandling 조인 → {groups:3단계, market_counts}.

    대응완료(종결)는 완료일로부터 7일 이내 & 수기삭제(dismissed_at) 안 된 것만 노출.
    신규요청/대응중는 영향 없음.
    """
    own = session is None
    session = session or SessionLocal()
    try:
        warnings = []
        rows = status_change_rows(markets, since=since, until=until, warnings=warnings)
        keys = [claim_key_of(r) for r in rows]
        handled = {h.claim_key: h for h in
                   session.query(ClaimHandling).filter(ClaimHandling.claim_key.in_(keys or [""])).all()}
        groups = {s: [] for s in _STAGES}
        counts = {"전체": 0}
        today = (now or _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9)))).date()
        for r in rows:
            ack = handled.get(claim_key_of(r))
            v = _claim_view(r, ack)
            if v["단계"] == "대응완료":
                d = _ymd(r.get("_change_date"))
                if (ack and ack.dismissed_at) or (d is not None and (today - d).days > _RETENTION_DAYS):
                    continue
            groups[v["단계"]].append(v)
            counts["전체"] += 1
            counts[v["판매처"]] = counts.get(v["판매처"], 0) + 1
        return {"groups": groups, "market_counts": counts, "warnings": warnings}
    finally:
        if own:
            session.close()
