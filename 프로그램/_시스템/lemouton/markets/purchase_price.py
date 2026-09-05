"""실매입가 — 저장·조회 + 매입가 우선순위 3단계.

설계서 `docs/superpowers/specs/2026-08-06-실매입가-주문통합-design.md` §3·§4.

## 우선순위 (§4) — 2026-08-06 사장님 재확정 「싼 쪽」

| 순위 | tier | 값 | 원천 |
|---|---|---|---|
| 1 | `real` | 실매입가 | `order_line_purchases.purchase_price` (사람이 적은 값) |
| 2 | `stock` / `estimate` | **사입가·소싱가 중 싼 쪽** | `pricing.cost_basis.resolve_cost_basis` 판정 |
| — | `None` | 없음 | 「확인 불가」 — **0 으로 채우지 않는다** |

2순위에서 사입 쪽이 뽑히면 tier=`stock`(사입가), 소싱 쪽이 뽑히면 tier=`estimate`
(최종매입가)다. **어느 쪽 값인지 화면이 늘 구분해 보여 준다.**

🔴 이건 「폴백 금지」 위반이 아니다. 금지되는 폴백은 *크롤 실패 시 대표가(평균·최저)로
메우는 것*이고, 여기는 **성격이 다른 값들에 규칙을 준 뒤 출처(tier)를 반드시 밝히는 것**이다.

## 재계산 금지 — 원가 규칙의 단일 원천은 `cost_basis` 하나

사입 vs 소싱 판정은 **`pricing.cost_basis.resolve_cost_basis` 를 호출만** 한다.
여기에 같은 규칙을 다시 쓰지 않는다 — 판매가·마진 계산(`api_pricing`·`uploader.preview`·
`uploader.reconcile`)이 이미 그 함수를 쓰고 있어서, 여기서 따로 판정하면
**같은 상품 원가가 화면마다 갈린다**(실제로 갈려 있던 것을 이 커밋에서 합쳤다).
3순위 값 자체는 `orders.price_diff._current_purchase`(소싱처 최종매입가 계산 경로)에서 온다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SOURCE_MANUAL = "manual"
SOURCE_MANGO = "mango"
_SOURCES = (SOURCE_MANUAL, SOURCE_MANGO)

TIER_REAL = "real"
TIER_STOCK = "stock"
TIER_ESTIMATE = "estimate"

TIER_LABEL = {
    TIER_REAL: "실매입가",
    TIER_STOCK: "사입가",
    TIER_ESTIMATE: "최종매입가",
}
LABEL_UNKNOWN = "확인 불가"


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def _to_price(v):
    """가격을 정수로. 못 읽거나 0 이하면 None(= 「입력 안 함」). 0 으로 채우지 않는다."""
    if v is None or v == "":
        return None
    try:
        n = int(round(float(str(v).replace(",", "").strip())))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


# ── 저장소 ────────────────────────────────────────────────────────────────

def get_many(session, line_uids) -> dict:
    """line_uid → OrderLinePurchase. 없는 것은 키를 안 만든다."""
    from lemouton.markets.models_purchase import OrderLinePurchase

    uids = [u for u in {_clean(u) for u in (line_uids or [])} if u]
    if not uids:
        return {}
    out = {}
    # 🔴 [2026-08-14] 여기 적혀 있던 「SQLite IN 한도(999)」는 **틀린 근거**였다
    #    (999 는 SQLite 3.32 이전 기본값). 실측 한도와 자르는 진짜 이유는
    #    `lemouton/matrix/readiness._CHUNK` 옆 한 곳에만 적어 뒀다. 자르는 것 자체는
    #    그대로 둔다 — 안 자르면 주문 줄이 쌓인 날에만 조회가 통째로 실패한다.
    for i in range(0, len(uids), 900):
        chunk = uids[i:i + 900]
        for row in (session.query(OrderLinePurchase)
                    .filter(OrderLinePurchase.line_uid.in_(chunk)).all()):
            out[row.line_uid] = row
    return out


def _record_history(session, *, line_uid, old_price, new_price,
                    old_source=None, new_source=None, reason=None,
                    ref=None, changed_by=None, commit=True) -> None:
    """변경 이력 한 줄 덧붙이기 (`models_purchase_history` 머리말의 규율).

    · **바뀐 때만** 적는다 — 값도 출처도 그대로면 아무것도 안 남긴다(잡음 방지).
    · 🔴 여기서 터져도 저장을 되돌리지 않는다. 돈 값을 못 적는 것보다 이력 한 줄이
      비는 편이 낫다. 다만 **조용히 넘어가지는 않는다** — 로그에 남긴다.
    · `commit=False` — 대량 업로드(`purchase_mango.apply`)가 행마다 커밋·플러시하면
      원격 DB 왕복이 N배가 돼 3,900+행에서 타임아웃 난다(issue #1139). 호출부가
      여러 줄을 모아 한 번만 커밋할 때 쓴다 — 이때는 그냥 `session.add` 만 하고
      커밋도 조용한-실패 처리도 하지 않는다(같은 배치 트랜잭션에 얹혀 호출부의
      한 번뿐인 커밋에서 함께 저장되거나 함께 실패한다 — 실패 범위는 호출부의
      청크 크기로 제한된다).
    """
    if old_price == new_price and (old_source or None) == (new_source or None):
        return
    from lemouton.markets.models_purchase_history import \
        OrderLinePurchaseHistory

    entry = OrderLinePurchaseHistory(
        line_uid=line_uid, old_price=old_price, new_price=new_price,
        old_source=old_source, new_source=new_source,
        reason=(reason or None), ref=(str(ref)[:255] if ref else None),
        changed_by=changed_by)

    if not commit:
        session.add(entry)
        return

    try:
        session.add(entry)
        session.commit()
    except Exception:                       # noqa: BLE001
        logger.exception(
            "실매입가 변경 이력 적기 실패 uid=%s (%s→%s) — 저장 자체는 됐습니다",
            line_uid, old_price, new_price)
        try:
            session.rollback()
        except Exception:                   # noqa: BLE001
            pass


def upsert(session, *, line_uid, price, source=SOURCE_MANUAL,
           mango_ref=None, memo=None, input_by=None, reason=None, commit=True,
           _existing=None):
    """실매입가 저장. **가격이 0 또는 None 이면 삭제**(= 「입력 안 함」으로 되돌림).

    `reason` 은 변경 이력에 남길 「무엇이 이 변경을 일으켰나」다(기본값 = `source`).
    마진 계산기 업로드처럼 출처는 mango 지만 경로가 다른 경우를 구분하려고 받는다.

    `commit=False` — 호출부가 여러 줄을 모아 한 번만 커밋할 때(대량 업로드,
    issue #1139). 이때는 flush 도 안 한다 — 호출부가 청크 경계에서 commit=True 로
    부르면 그때 한꺼번에 반영된다. 기본값은 그대로 즉시 커밋(단건 저장 호출부는
    동작이 안 바뀐다).

    `_existing` — {line_uid: OrderLinePurchase | None} 미리 읽어 둔 맵(대량
    호출부가 `get_many` 로 한 번에 읽어서 넘긴다). 있으면 `session.get()` 을
    생략한다 — 수천 줄을 저장할 때 행마다 SELECT 왕복이 나가는 걸 막는다
    (issue #1139). 안 주면(기본값) 원래대로 그때그때 조회한다.

    Returns: 저장된 행 / 삭제됐거나 애초에 없으면 None.
    """
    from lemouton.markets.models_purchase import OrderLinePurchase

    uid = _clean(line_uid)
    if not uid:
        raise ValueError("line_uid 가 비었어요 — 어느 주문 줄인지 알 수 없습니다.")
    if source not in _SOURCES:
        raise ValueError(f"source 는 {_SOURCES} 중 하나여야 해요 (받은 값: {source!r}).")

    n = _to_price(price)
    if n is None:
        delete(session, uid, reason=(reason or source), ref=mango_ref,
               changed_by=input_by, commit=commit, _existing=_existing)
        return None

    obj = _existing.get(uid) if _existing is not None else session.get(OrderLinePurchase, uid)
    # 🔴 바꾸기 **전에** 옛 값을 챙긴다 — 고친 뒤에는 무엇이었는지 알 길이 없다.
    old_price = int(obj.purchase_price) if obj is not None else None
    old_source = obj.source if obj is not None else None
    if obj is None:
        obj = OrderLinePurchase(line_uid=uid, purchase_price=n, source=source,
                                mango_ref=mango_ref, memo=memo, input_by=input_by)
        session.add(obj)
        if _existing is not None:
            _existing[uid] = obj
    else:
        obj.purchase_price = n
        obj.source = source
        # 🔴 빈 값으로 덮어쓰지 않는다 — 엑셀 재업로드가 사장님 메모를 지우면 안 된다.
        if mango_ref is not None:
            obj.mango_ref = mango_ref
        if memo is not None:
            obj.memo = memo
        if input_by is not None:
            obj.input_by = input_by
        obj.updated_at = datetime.now(timezone.utc)
    if commit:
        session.commit()
    _record_history(session, line_uid=uid, old_price=old_price, new_price=n,
                    old_source=old_source, new_source=source,
                    reason=(reason or source), ref=mango_ref,
                    changed_by=input_by, commit=commit)
    return obj


def delete(session, line_uid, *, reason=None, ref=None, changed_by=None,
           commit=True, _existing=None) -> bool:
    """행 삭제. 지운 게 있으면 True. **지움도 이력에 남는다**(new_price=None).

    `_existing` — `upsert` 와 같은 미리 읽어 둔 맵. 대량 호출부에서 넘긴다.
    """
    from lemouton.markets.models_purchase import OrderLinePurchase

    uid = _clean(line_uid)
    if not uid:
        return False
    obj = _existing.get(uid) if _existing is not None else session.get(OrderLinePurchase, uid)
    if obj is None:
        return False
    old_price, old_source = int(obj.purchase_price), obj.source
    session.delete(obj)
    if _existing is not None:
        _existing[uid] = None
    if commit:
        session.commit()
    _record_history(session, line_uid=uid, old_price=old_price, new_price=None,
                    old_source=old_source, new_source=None,
                    reason=(reason or SOURCE_MANUAL), ref=ref, commit=commit,
                    changed_by=changed_by)
    return True


def history(session, line_uid, *, limit=50) -> list:
    """한 주문 줄의 변경 이력 — 최신이 먼저. 화면이 그대로 그릴 수 있는 dict 목록."""
    from lemouton.markets.models_purchase_history import \
        OrderLinePurchaseHistory

    uid = _clean(line_uid)
    if not uid:
        return []
    rows = (session.query(OrderLinePurchaseHistory)
            .filter(OrderLinePurchaseHistory.line_uid == uid)
            .order_by(OrderLinePurchaseHistory.changed_at.desc(),
                      OrderLinePurchaseHistory.id.desc())
            .limit(int(limit)).all())
    out = []
    for r in rows:
        out.append({
            "id": int(r.id),
            "old_price": (int(r.old_price) if r.old_price is not None else None),
            "new_price": (int(r.new_price) if r.new_price is not None else None),
            "old_source": r.old_source, "new_source": r.new_source,
            "reason": r.reason, "ref": r.ref, "changed_by": r.changed_by,
            "changed_at": (r.changed_at.isoformat() if r.changed_at else None),
        })
    return out


# ── 우선순위 3단계 ────────────────────────────────────────────────────────

def _rows_by_uid(session, line_uids, rows=None) -> dict:
    """line_uid → 주문 행(dict). rows 를 주면 그대로 쓰고, 없으면 적재분에서 읽는다."""
    want = {u for u in (_clean(x) for x in (line_uids or [])) if u}
    if rows is not None:
        return {u: r for r in rows
                for u in [_clean((r or {}).get("_line_uid"))] if u and u in want}
    if not want:
        return {}
    from lemouton.markets.models_orders import MarketOrderLine

    out = {}
    uids = list(want)
    for i in range(0, len(uids), 900):
        for o in (session.query(MarketOrderLine)
                  .filter(MarketOrderLine.line_uid.in_(uids[i:i + 900])).all()):
            row = dict(o.row or {})
            row["_line_uid"] = o.line_uid
            out[o.line_uid] = row
    return out


def _purchase_inputs(session, skus) -> dict:
    """sku → (실측 사입 매입가, 사입 재고). **판정은 여기서 안 한다** — cost_basis 몫.

    `PriceTemplate.boxhero_purchase_price` 는 사람이 손으로 적은 한 숫자라 전 옵션에
    똑같이 깔린다 — 그 모듈 주석대로 **후보로 넣지 않는다**(실측 이동평균만).
    """
    from lemouton.sourcing.models import Option

    want = [s for s in {_clean(s) for s in (skus or [])} if s]
    if not want:
        return {}
    avg_by_sku = {o.canonical_sku: (o.boxhero_avg_purchase_price or 0)
                  for o in session.query(Option)
                  .filter(Option.canonical_sku.in_(want)).all()}
    if not avg_by_sku:
        return {}
    try:
        from shared.inventory_stock import get_stock_batch
        stock = get_stock_batch(session, list(avg_by_sku)) or {}
    except Exception:                       # noqa: BLE001 — 재고 조회 실패가 화면을 죽이면 안 된다
        logger.exception("사입 재고 조회 실패 — 사입가 후보는 건너뜁니다")
        return {}
    return {sku: (avg, stock.get(sku, 0)) for sku, avg in avg_by_sku.items()}


def resolve_purchase_price(session, line_uids, *, rows=None,
                           matrix_loader=None) -> dict:
    """line_uid → {'price': int|None, 'tier': 'real'|'stock'|'estimate'|None, 'label': str}.

    `rows`(화면이 이미 들고 있는 주문 행)를 주면 그걸 쓰고, 안 주면 적재분에서 읽는다.
    실매입가가 없으면 **사입가·소싱가 중 싼 쪽**(`cost_basis.resolve_cost_basis` 판정)이고,
    그것도 주문 행을 우리 옵션(SKU)에 붙일 수 있어야 구한다 —
    못 붙이면 값이 없는 것이고, 그때는 price=None·tier=None(「확인 불가」)이다.
    """
    want = [u for u in {_clean(x) for x in (line_uids or [])} if u]
    out = {u: {"price": None, "tier": None, "label": LABEL_UNKNOWN} for u in want}
    if not want:
        return out

    # ── 1순위 실매입가 ────────────────────────────────────────────────
    real = get_many(session, want)
    for uid, row in real.items():
        out[uid] = {"price": int(row.purchase_price), "tier": TIER_REAL,
                    "label": TIER_LABEL[TIER_REAL]}
    rest = [u for u in want if u not in real]
    if not rest:
        return out

    row_by_uid = _rows_by_uid(session, rest, rows=rows)
    if not row_by_uid:
        return out

    # 주문 행 → canonical_sku (판정은 price_diff 하나 — 여기서 다시 만들지 않는다)
    from lemouton.orders import price_diff as _pd

    order_rows = list(row_by_uid.values())
    try:
        targets = _pd.resolve_targets_verbose(session, order_rows)
    except Exception:                       # noqa: BLE001
        logger.exception("주문 → 옵션(SKU) 연결 실패 — 매입가는 확인 불가로 남깁니다")
        return out
    sku_by_uid = {}
    for uid, r in row_by_uid.items():
        t = targets.get(_pd.row_key(r)) or {}
        if t.get("sku"):
            sku_by_uid[uid] = t["sku"]
    if not sku_by_uid:
        return out
    skus = set(sku_by_uid.values())

    # ── 2순위 「싼 쪽」 — 사입가 vs 소싱가 (판정은 cost_basis 하나) ────
    #   🔴 두 값을 **둘 다** 구해야 한다. 예전처럼 사입이 있다고 소싱을 건너뛰면
    #     비교 자체가 안 되고, 판매가·마진 화면(같은 cost_basis 를 쓰는 곳)과
    #     같은 상품 원가가 갈린다.
    from lemouton.pricing.cost_basis import resolve_cost_basis

    buy = _purchase_inputs(session, skus)
    try:
        finals, _errors = _pd._current_purchase(session, skus,
                                                matrix_loader=matrix_loader)
    except Exception:                       # noqa: BLE001
        logger.exception("소싱처 최종매입가 조회 실패 — 사입가만 두고 판정합니다")
        finals = {}

    for uid, sku in sku_by_uid.items():
        avg, stk = buy.get(sku, (None, 0))
        basis = resolve_cost_basis(finals.get(sku), avg, stk)
        if basis.cost is None:
            continue                        # 「확인 불가」 — 0 으로 채우지 않는다
        tier = TIER_STOCK if basis.side == "purchase" else TIER_ESTIMATE
        out[uid] = {"price": int(basis.cost), "tier": tier,
                    "label": TIER_LABEL[tier]}
    return out
