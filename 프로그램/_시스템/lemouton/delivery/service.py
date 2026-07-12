"""배송검사 도메인 서비스 — 매핑 시드, upsert, 배송방식 판정, 검사 2종."""
from datetime import datetime, timezone

from lemouton.delivery.models import MangoOrder, MangoStatusMap

# (status_value, meaning, default_method, is_flow_check_target, sort_order)
# 사용자 실워크플로 반영(2026-07-12):
#  · 해외현지배송중 = 까대기 주문완료(주문내역만, 송장 전)
#  · 현지배송완료   = 까대기 송장 미리 입력·출력한 상태 → 배송흐름 검사 핵심 대상
#  · 배송대기중/국내배송중 = 직배 / 배송완료 = 도착(검사 제외) / 반품·취소 = 미지정
_DEFAULT_MAP = [
    ("결제완료",             "배송전",     "미지정", False, 10),
    ("배송대기중",           "배송전",     "직배",   False, 20),
    ("해외현지배송중",       "해외배송중", "까대기", False, 30),
    ("현지배송완료",         "국내배송중", "까대기", True,  35),
    ("국내배송중",           "국내배송중", "직배",   True,  40),
    ("배송완료",             "배송완료",   "미지정", False, 50),
    ("반품/교환/취소진행중", "취소반품교환", "미지정", False, 60),
    ("반품/교환/취소완료",   "취소반품교환", "미지정", False, 70),
]

# 이전 기본값 → 사용자가 모달에서 안 바꿨으면(값이 옛 기본과 동일하면) 새 기본값으로 1회 갱신.
# 사용자가 손수 바꾼 값은 옛 기본과 달라 매칭되지 않아 보존된다. (status, old_method, old_flow)
_RECONCILE_FROM_OLD = [
    ("배송대기중", "미지정", False),
    ("국내배송중", "미지정", True),
    ("배송완료",   "미지정", True),
]


def _now():
    return datetime.now(timezone.utc)


def seed_default_status_map(session):
    """기본 매핑 보강. 없는 값은 삽입 + 옛 기본값 그대로인 행은 새 기본값으로 갱신(수정본 보존). idempotent."""
    by_value = {r.status_value: r for r in session.query(MangoStatusMap).all()}
    canonical = {v: (mean, method, flow, order)
                 for (v, mean, method, flow, order) in _DEFAULT_MAP}
    changed = False
    # 1) 없는 매핑 삽입
    for value, (mean, method, flow, order) in canonical.items():
        if value not in by_value:
            session.add(MangoStatusMap(status_value=value, meaning=mean,
                                       default_method=method, is_flow_check_target=flow,
                                       sort_order=order))
            changed = True
    # 2) 옛 기본값 그대로인 행만 새 기본값으로 갱신(사용자 수정 보존)
    for value, old_method, old_flow in _RECONCILE_FROM_OLD:
        r = by_value.get(value)
        if r and r.default_method == old_method and bool(r.is_flow_check_target) == old_flow:
            mean, method, flow, order = canonical[value]
            r.meaning, r.default_method, r.is_flow_check_target = mean, method, flow
            changed = True
    if changed:
        session.commit()


def get_status_map(session) -> dict:
    """status_value -> MangoStatusMap."""
    return {r.status_value: r for r in session.query(MangoStatusMap).all()}


def _auto_method(status_value, status_map) -> str:
    m = status_map.get(status_value)
    return m.default_method if m else "미지정"


def upsert_orders(session, rows, bulk_method=None, replace_stale=False) -> dict:
    """파싱된 rows(dict 리스트)를 mango_uid 기준 upsert.

    bulk_method: '까대기'/'직배' 이면 이번 업로드 전체를 그 방식으로(source='일괄'),
                 None 또는 '자동판정' 이면 L매핑 자동(source='자동').
    수기(source=='수기') 행의 배송방식은 절대 덮지 않는다.
    replace_stale: True(실제 업로드 라우트에서만) 면 '최신 스냅샷' — 이번 업로드에 없는 옛
                   주문은 삭제(더망고 전체 목록 = 항상 이번 업로드분만). 이어지는 주문은
                   upsert 로 유지(수기 배송방식 보존). 더망고는 현재 주문 전체 스냅샷이라,
                   목록에서 빠진 건 발송완료 등으로 빠진 것 → 배송검사 대상 아님.
                   기본 False = 누적(테스트·부분 업로드가 옛 데이터를 지우지 않게).
    """
    status_map = get_status_map(session)
    # 처음 보는 구분자값은 매핑행 자동 생성(모달에서 편집 가능하게). 기본=미지정·검사 제외.
    new_status = False
    for r in rows:
        sv = r.get("mango_status")
        if sv and sv not in status_map:
            m = MangoStatusMap(status_value=sv, meaning="기타",
                               default_method="미지정", is_flow_check_target=False,
                               sort_order=900)
            session.add(m)
            status_map[sv] = m
            new_status = True
    if new_status:
        session.commit()
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

    # 최신 스냅샷: 이번 업로드에 없는 옛 주문 삭제(누적 방지). 이어지는 주문은 위 upsert 로
    # 이미 갱신됐고 수기 배송방식도 보존됨 — 여기선 '이번 목록에 없는' 것만 지운다.
    deleted = 0
    uploaded_uids = {r["mango_uid"] for r in rows}
    if replace_stale and uploaded_uids:
        deleted = (session.query(MangoOrder)
                   .filter(~MangoOrder.mango_uid.in_(uploaded_uids))
                   .delete(synchronize_session=False))
        session.commit()
    return {"inserted": inserted, "updated": updated, "deleted": deleted}


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


# ── v2 검사 (마켓 API 실데이터 기준) ──
from datetime import datetime as _dt, timezone as _tz  # noqa: E402
from lemouton.markets.order_export import _SHIPPED_STATES  # noqa: E402


def find_double_invoice_risk(session):
    """더망고는 아직 해외현지배송중(재출력 대상)인데 마켓엔 이미 송장/배송중 → 이중송장 위험."""
    out = []
    for o in (session.query(MangoOrder)
              .filter(MangoOrder.mango_status == "해외현지배송중").all()):
        if o.market_check_error:            # 확인불가 제외
            continue
        if (o.market_api_invoice or "") or (o.market_api_status in _SHIPPED_STATES):
            out.append(o)
    return out


def _stall_base_time(o):
    """정체 24h 기준시각 — 마켓 발송처리일 우선, 없으면 송장 첫 관측시각."""
    hist0 = (o.invoice_history or [{}])[0].get("at") if o.invoice_history else None
    for cand in (o.market_shipped_at, hist0):
        if cand:
            try:
                return _dt.fromisoformat(cand)
            except (ValueError, TypeError):
                continue
    return None


def find_flow_stalled(session, now=None):
    """송장 있음 + 마켓상태 배송중 미만 + 24h 경과 → 배송흐름 정체."""
    now = now or _dt.now(_tz.utc)
    out = []
    for o in session.query(MangoOrder).all():
        if o.market_check_error:
            continue
        if not o.market_api_status:            # 마켓 상태 미확인 → 판정 보류
            continue
        has_inv = bool((o.market_api_invoice or "") or (o.invoice_no or ""))
        if not has_inv:
            continue
        if o.market_api_status in _SHIPPED_STATES:   # 이미 흐름 시작 → 정상
            continue
        base = _stall_base_time(o)
        if base is None:
            continue
        if base.tzinfo is None:
            base = base.replace(tzinfo=_tz.utc)
        if (now - base).total_seconds() > 24 * 3600:
            out.append(o)
    return out
