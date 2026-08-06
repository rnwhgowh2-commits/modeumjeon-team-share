# -*- coding: utf-8 -*-
"""포장 스캔 출고 — 바코드를 찍어 「이 주문 줄이 나갔다」를 확정한다.

사장님 확정(2026-08-06)
────────────────────────────────
· 재고 차감은 **표시만으로 하지 않는다.** 포장하며 바코드를 찍는 그 순간에 한다
  — 실물 대조와 차감이 한 동작이어야 장부와 실물이 안 어긋난다.
· **사입으로 표시된 줄만** 재고를 깎는다. 무재고 줄은 소싱처에서 사서 보내는 것이라
  우리 창고에서 나가는 게 아니다(깎으면 없는 재고를 깎아 마이너스가 된다).
· 재고가 모자라면 **막지 않고 경고한다** — 사장님이 실재고에 맞춰 조정한다.

두 번 찍어도 두 번 안 깎는다
────────────────────────────────
`InventoryTx.order_line_uid` 가 열쇠다. 이미 그 줄로 만든 출고가 있으면 새로 안 만들고
「이미 처리됨」을 돌려준다. 포장 현장에서 같은 상자를 두 번 찍는 일은 흔하다.

재고 판정은 SSOT 로만
────────────────────────────────
`Option.boxhero_stock_total` 은 박스히어로 import 시점 스냅샷이라 라이브에서 대부분
0이다(실측). 그걸로 판정하면 멀쩡한 재고도 「부족」이 된다 — `shared.inventory_stock`
(InventoryTx 합산)만 본다. 같은 이유로 `inventory.inbound.create_outbound` 를 쓰지 않고
여기서 InventoryTx 를 만든다(그 함수의 가드가 스냅샷을 본다).
"""
from __future__ import annotations

import datetime as _dt
import logging

logger = logging.getLogger(__name__)

#: 응답 결과 코드
RESULT_DEDUCTED = "deducted"        # 사입 — 재고를 깎았다
RESULT_NO_DEDUCT = "no_deduct"      # 무재고 — 깎을 것이 없다(확인만)
RESULT_ALREADY = "already"          # 이미 처리된 줄(두 번 찍음)


def _now():
    return _dt.datetime.utcnow()


def already_shipped_uids(session, line_uids) -> set[str]:
    """이미 포장 스캔으로 출고 기록이 만들어진 주문 줄."""
    from lemouton.inventory.models import InventoryTx

    uids = [u for u in {str(u or "").strip() for u in (line_uids or [])} if u]
    if not uids:
        return set()
    out: set[str] = set()
    for i in range(0, len(uids), 900):
        chunk = uids[i:i + 900]
        rows = (session.query(InventoryTx.order_line_uid)
                .filter(InventoryTx.order_line_uid.in_(chunk))
                .filter(InventoryTx.status == "completed")
                .all())
        out |= {r[0] for r in rows if r[0]}
    return out


def pending_lines_for_sku(session, canonical_sku, *, days: int = 30,
                          limit: int = 50) -> list[dict]:
    """이 옵션(SKU)으로 최근 들어온 주문 줄 — 폰이 스캔 직후 고르게 보여 준다.

    · 주문 줄에는 우리 옵션을 가리키는 칼럼이 없다. 매칭은 `orders.price_diff` 의
      단일 원천(resolve_targets_verbose)을 그대로 쓴다 — 여기서 또 만들면 어긋난다.
    · 클레임 줄(_kind='change')은 뺀다. 취소·반품은 포장 대상이 아니다.
    · 이미 찍은 줄도 **숨기지 않고** `shipped: true` 로 내보낸다 — 안 보이면
      사장님은 「왜 없지」를 겪는다(조용히 사라지는 것이 가장 나쁘다).
    """
    from lemouton.markets import order_store as _os
    from lemouton.markets import supply_mode as _sm
    from lemouton.orders import price_diff as _pd

    sku = str(canonical_sku or "").strip()
    if not sku:
        return []

    until = _dt.date.today()
    since = until - _dt.timedelta(days=max(1, int(days)))
    rows = _os.load(since=since.isoformat(), until=until.isoformat(),
                    include_claims=False, session=session) or []
    rows = [r for r in rows if (r or {}).get("_kind") != "change"]
    if not rows:
        return []

    try:
        targets = _pd.resolve_targets_verbose(session, rows)
    except Exception:                       # noqa: BLE001
        logger.exception("주문→옵션 매칭 실패 — %d건", len(rows))
        return []

    mine = []
    for r in rows:
        t = targets.get(_pd.row_key(r)) or {}
        if t.get("sku") != sku:
            continue
        uid = str(r.get("_line_uid") or "").strip()
        if not uid:
            continue                        # 식별자 없는 줄은 찍어도 되돌릴 수 없다
        mine.append((uid, r))
        if len(mine) >= limit:
            break
    if not mine:
        return []

    uids = [u for u, _ in mine]
    shipped = already_shipped_uids(session, uids)
    modes = _sm.get_many_with_default(session, uids)
    return [{
        "line_uid": uid,
        "market": r.get("판매처") or r.get("market") or "",
        "order_no": r.get("오픈마켓주문번호") or r.get("주문번호") or "",
        "product": r.get("상품명") or "",
        "option": r.get("옵션") or "",
        "qty": r.get("수량") or 1,
        "status": r.get("주문상태") or "",
        "order_date": r.get("주문일") or "",
        "supply_mode": modes.get(uid, "dropship"),
        "shipped": uid in shipped,
    } for uid, r in mine]


def ship_order_line(session, *, line_uid, canonical_sku, location_id,
                    qty: int = 1, actor: str = "", unit_sale_price: int = 0) -> dict:
    """포장 스캔 1건 처리.

    Returns dict:
      {result, supply_mode, deducted_qty, stock_after, warning}
        · result = deducted | no_deduct | already
        · warning = 재고가 모자란데 그대로 기록했을 때의 안내(막지 않는다)
    """
    from lemouton.inventory.models import InventoryTx
    from lemouton.markets import supply_mode as _sm
    from shared.inventory_stock import get_stock_batch

    uid = str(line_uid or "").strip()
    sku = str(canonical_sku or "").strip()
    if not uid:
        raise ValueError("주문 줄 식별자(line_uid)가 없어요.")
    if not sku:
        raise ValueError("어느 옵션인지(canonical_sku) 알 수 없어요.")
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise ValueError("수량은 숫자여야 해요.")
    if qty <= 0:
        raise ValueError("수량은 1 이상이어야 해요.")

    mode = _sm.get_many_with_default(session, [uid])[uid]

    # 이미 찍은 줄이면 아무것도 더 하지 않는다 (두 번 깎기 방지)
    if already_shipped_uids(session, [uid]):
        return {"result": RESULT_ALREADY, "supply_mode": mode,
                "deducted_qty": 0,
                "stock_after": int(get_stock_batch(session, [sku]).get(sku, 0)),
                "warning": None}

    # 무재고 = 소싱처에서 사서 보낸다 → 우리 창고에서 나가는 게 아니다
    if mode != "stock":
        return {"result": RESULT_NO_DEDUCT, "supply_mode": mode, "deducted_qty": 0,
                "stock_after": int(get_stock_batch(session, [sku]).get(sku, 0)),
                "warning": None}

    before = int(get_stock_batch(session, [sku]).get(sku, 0))
    warning = None
    if before < qty:
        # 🔴 막지 않는다(사장님 확정) — 장부가 실물과 다르다는 신호를 남기고 진행한다.
        warning = (f"창고 재고가 모자랍니다 — 장부 {before}개, 내보낸 수량 {qty}개. "
                   f"재고 조사로 실재고에 맞춰 주세요.")

    tx = InventoryTx(
        tx_type="out",
        location_id=location_id,
        option_canonical_sku=sku,
        qty=qty,                      # 저장은 양수, 부호는 tx_type 이 결정(SSOT 규약)
        unit_sale_price=unit_sale_price or 0,
        order_line_uid=uid,
        memo=f"[포장 스캔 출고] 주문 {uid}",
        created_by=actor or "",
        created_at=_now(),
        status="completed",
        source="local",
    )
    session.add(tx)
    session.commit()

    after = int(get_stock_batch(session, [sku]).get(sku, 0))
    logger.info("[scan-ship] %s sku=%s qty=%d %d→%d%s",
                uid, sku, qty, before, after, " (재고부족)" if warning else "")
    return {"result": RESULT_DEDUCTED, "supply_mode": mode, "deducted_qty": qty,
            "stock_after": after, "warning": warning, "tx_id": tx.id}
