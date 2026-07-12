"""배송검사 도메인 서비스 — 매핑 시드, upsert, 배송방식 판정, 검사 2종."""
from datetime import datetime, timezone

from lemouton.delivery.models import MangoOrder, MangoStatusMap

# (status_value, meaning, default_method, is_flow_check_target, sort_order)
_DEFAULT_MAP = [
    ("결제완료",             "배송전",     "미지정", False, 10),
    ("배송대기중",           "배송전",     "미지정", False, 20),
    ("해외현지배송중",       "해외배송중", "까대기", False, 30),
    ("국내배송중",           "국내배송중", "미지정", True,  40),
    ("배송완료",             "배송완료",   "미지정", True,  50),
    ("반품/교환/취소진행중", "취소반품교환", "미지정", False, 60),
    ("반품/교환/취소완료",   "취소반품교환", "미지정", False, 70),
]


def _now():
    return datetime.now(timezone.utc)


def seed_default_status_map(session):
    """기본 매핑을 없는 것만 삽입 (idempotent)."""
    existing = {r.status_value for r in session.query(MangoStatusMap.status_value).all()}
    for value, meaning, method, flow, order in _DEFAULT_MAP:
        if value in existing:
            continue
        session.add(MangoStatusMap(status_value=value, meaning=meaning,
                                   default_method=method, is_flow_check_target=flow,
                                   sort_order=order))
    session.commit()


def get_status_map(session) -> dict:
    """status_value -> MangoStatusMap."""
    return {r.status_value: r for r in session.query(MangoStatusMap).all()}


def _auto_method(status_value, status_map) -> str:
    m = status_map.get(status_value)
    return m.default_method if m else "미지정"


def upsert_orders(session, rows, bulk_method=None) -> dict:
    """파싱된 rows(dict 리스트)를 mango_uid 기준 upsert.

    bulk_method: '까대기'/'직배' 이면 이번 업로드 전체를 그 방식으로(source='일괄'),
                 None 또는 '자동판정' 이면 L매핑 자동(source='자동').
    수기(source=='수기') 행의 배송방식은 절대 덮지 않는다.
    """
    status_map = get_status_map(session)
    inserted = updated = 0
    for r in rows:
        uid = r["mango_uid"]
        o = session.query(MangoOrder).filter_by(mango_uid=uid).one_or_none()
        invoice = r.get("invoice_no") or ""
        if o is None:
            o = MangoOrder(mango_uid=uid, first_uploaded_at=_now(), invoice_history=[])
            session.add(o)
            inserted += 1
        else:
            updated += 1

        # 공통 필드 갱신
        o.market_name = r.get("market_name")
        o.market_order_no = r.get("market_order_no")
        o.ordered_at = r.get("ordered_at")
        o.recipient = r.get("recipient")
        o.product_name = r.get("product_name")
        o.option1 = r.get("option1")
        o.phone = r.get("phone")
        o.courier = r.get("courier")
        o.mango_status = r.get("mango_status")
        o.market_status = r.get("market_status")
        o.memo = r.get("memo")
        o.raw = r
        o.last_uploaded_at = _now()

        # 송장 이력 누적 (직전 값과 다른 새 송장이면 추가)
        hist = list(o.invoice_history or [])
        if invoice and (not hist or hist[-1].get("invoice") != invoice):
            hist.append({"invoice": invoice, "at": _now().isoformat()})
        o.invoice_history = hist
        o.invoice_no = invoice or o.invoice_no
        distinct = {h["invoice"] for h in hist if h.get("invoice")}
        o.is_duplicate_invoice = len(distinct) >= 2

        # 배송방식 판정 (수기는 보존)
        if o.delivery_method_source != "수기":
            if bulk_method in ("까대기", "직배"):
                o.delivery_method = bulk_method
                o.delivery_method_source = "일괄"
            else:
                o.delivery_method = _auto_method(o.mango_status, status_map)
                o.delivery_method_source = "자동"

    session.commit()
    return {"inserted": inserted, "updated": updated}


def find_duplicate_invoices(session):
    """같은 주문(mango_uid)에 서로 다른 송장이 2회 이상 = 중복송장."""
    return session.query(MangoOrder).filter(MangoOrder.is_duplicate_invoice.is_(True)).all()


def find_flow_missing(session):
    """구분자가 배송흐름 검사대상인데 배송흐름이 안 뜨는 주문.

    신호: 마켓상태 '송장전송실패' 또는 송장번호 없음.
    """
    status_map = get_status_map(session)
    targets = {v for v, m in status_map.items() if m.is_flow_check_target}
    out = []
    if not targets:
        return out
    for o in session.query(MangoOrder).filter(MangoOrder.mango_status.in_(targets)).all():
        if (o.market_status == "송장전송실패") or not (o.invoice_no or ""):
            out.append(o)
    return out


def apply_bulk_method(session, method) -> int:
    """수기가 아닌 모든 주문의 배송방식을 method 로 일괄 변경. 변경 건수 반환."""
    assert method in ("까대기", "직배", "미지정")
    n = 0
    for o in session.query(MangoOrder).filter(MangoOrder.delivery_method_source != "수기").all():
        o.delivery_method = method
        o.delivery_method_source = "일괄"
        n += 1
    session.commit()
    return n


def set_method_manual(session, mango_uid, method) -> bool:
    """행별 수기 배송방식 지정 (최우선·재업로드로도 보존)."""
    assert method in ("까대기", "직배", "미지정")
    o = session.query(MangoOrder).filter_by(mango_uid=mango_uid).one_or_none()
    if not o:
        return False
    o.delivery_method = method
    o.delivery_method_source = "수기"
    session.commit()
    return True
