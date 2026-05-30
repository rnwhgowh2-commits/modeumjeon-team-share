"""재고 단일 진실 원천 (Single Source of Truth) — InventoryTx 기반 실시간 계산.

원칙
- 모든 UI 의 재고 표시는 이 모듈의 함수만 사용
- Option.boxhero_stock_total = 박스히어로 import 시점 snapshot 이라 신뢰 X
- InventoryTx (status='completed') 합 = 실시간 재고 = 진실 원천

성능
- get_stock_batch(skus) 로 한 번에 N SKU 조회 (N+1 회피)
- get_stock_summary() 도 1 쿼리로 전체 통계 계산
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import case, func

from lemouton.inventory.models import InventoryTx


def _stock_expr():
    """tx_qty 에 부호 반영한 expression — DB 저장 부호 무관 (abs() 기반 일관 처리).

    저장 방식 불일치 (데스크탑 양수 / 모바일 음수) 대응:
      · in/adjust  → +abs(qty)
      · out        → -abs(qty)
      · move (출발지)→ -abs(qty), 도착지 +abs(qty) 는 별도 쿼리에서 더함
    """
    return case(
        (InventoryTx.tx_type == 'in', func.abs(InventoryTx.qty)),
        (InventoryTx.tx_type == 'out', -func.abs(InventoryTx.qty)),
        (InventoryTx.tx_type == 'adjust', InventoryTx.qty),  # adjust 는 delta 부호 그대로 (±)
        (InventoryTx.tx_type == 'move', -func.abs(InventoryTx.qty)),
        else_=0,
    )


def _product_sku_map(session, option_skus) -> dict[str, str]:
    """[제품 공유 v1] 옵션 SKU → 연결된 재고제품 SKU.

    OptionProductLink 가 없으면 자기 자신으로 fallback (마이그레이션 전 호환).
    ※ 재고(stock) 정확성 경로이므로 캐시하지 않음 — 항상 실시간 조회
      (데이터 무결성 절대 원칙: 재고 귀속 지연 금지).
    """
    from lemouton.inventory.models import OptionProductLink
    skus = list(set(s for s in option_skus if s))
    if not skus:
        return {}
    rows = session.query(
        OptionProductLink.option_canonical_sku,
        OptionProductLink.product_canonical_sku,
    ).filter(OptionProductLink.option_canonical_sku.in_(skus)).all()
    m = {o: p for o, p in rows}
    for sk in skus:
        m.setdefault(sk, sk)  # 링크 없으면 = 자기 자신
    return m


def get_stock_by_sku(session, sku: str, location_id: int | None = None) -> int:
    """1 옵션 SKU 의 실시간 재고 (연결된 재고제품 기준).

    [제품 공유 v1] get_stock_batch 에 위임 — 옵션→재고제품 해석을 한 곳으로 일원화.
    """
    if not sku:
        return 0
    return get_stock_batch(session, [sku], location_id).get(sku, 0)


def get_stock_batch(session, skus: Iterable[str], location_id: int | None = None) -> dict[str, int]:
    """N 옵션 SKU 의 재고 한 번에 조회. {option_sku: stock}.

    [제품 공유 v1] 옵션 → 연결된 재고제품의 재고를 반환.
    같은 재고제품을 공유하는 여러 모음전 옵션은 동일한 재고값을 받는다.
    location_id 지정 시 그 위치만.
    """
    option_skus = list(set(s for s in skus if s))
    if not option_skus:
        return {}
    # 옵션 → 재고제품 SKU 해석
    psku_map = _product_sku_map(session, option_skus)
    product_skus = list(set(psku_map.values()))

    # 1) in/out/adjust 합 + move 출발 차감 — 재고제품 SKU 단위 집계
    q = session.query(
        InventoryTx.option_canonical_sku,
        func.coalesce(func.sum(_stock_expr()), 0).label('s'),
    ).filter(
        InventoryTx.option_canonical_sku.in_(product_skus),
        InventoryTx.status == 'completed',
    )
    if location_id is not None:
        q = q.filter(InventoryTx.location_id == location_id)
    rows = q.group_by(InventoryTx.option_canonical_sku).all()
    prod_stock: dict[str, int] = {sk: int(s or 0) for sk, s in rows}

    # 2) move 도착지 추가 보정 (location_to_id)
    mq = session.query(
        InventoryTx.option_canonical_sku,
        func.coalesce(func.sum(InventoryTx.qty), 0).label('s'),
    ).filter(
        InventoryTx.option_canonical_sku.in_(product_skus),
        InventoryTx.tx_type == 'move',
        InventoryTx.status == 'completed',
    )
    if location_id is not None:
        mq = mq.filter(InventoryTx.location_to_id == location_id)
    for sk, s in mq.group_by(InventoryTx.option_canonical_sku).all():
        prod_stock[sk] = prod_stock.get(sk, 0) + int(s or 0)

    # 옵션 → (연결 재고제품) 재고 매핑
    return {opt: prod_stock.get(psku_map[opt], 0) for opt in option_skus}


def get_stock_by_location_batch(session, skus: Iterable[str]) -> dict[str, dict[int, int]]:
    """N SKU × 모든 위치 → {sku: {loc_id: stock}} 한 번에 (2 쿼리만).

    기존 `for loc in locs: get_stock_batch(skus, location_id=loc.id)` 패턴(위치당
    2 쿼리)을 한 번의 group-by 쿼리로 치환. 위치 N개 → 2N 쿼리 → 2 쿼리.
    """
    option_skus = list(set(s for s in skus if s))
    if not option_skus:
        return {}
    psku_map = _product_sku_map(session, option_skus)
    product_skus = list(set(psku_map.values()))

    # 1) in/out/adjust + move 출발지 (location_id 기준 group-by)
    rows = session.query(
        InventoryTx.option_canonical_sku,
        InventoryTx.location_id,
        func.coalesce(func.sum(_stock_expr()), 0).label('s'),
    ).filter(
        InventoryTx.option_canonical_sku.in_(product_skus),
        InventoryTx.status == 'completed',
    ).group_by(
        InventoryTx.option_canonical_sku,
        InventoryTx.location_id,
    ).all()

    prod_stock: dict[str, dict[int, int]] = {}
    for sk, loc_id, s in rows:
        if loc_id is None:
            continue
        prod_stock.setdefault(sk, {})[loc_id] = int(s or 0)

    # 2) move 도착지 보정 (location_to_id)
    mrows = session.query(
        InventoryTx.option_canonical_sku,
        InventoryTx.location_to_id,
        func.coalesce(func.sum(InventoryTx.qty), 0).label('s'),
    ).filter(
        InventoryTx.option_canonical_sku.in_(product_skus),
        InventoryTx.tx_type == 'move',
        InventoryTx.status == 'completed',
    ).group_by(
        InventoryTx.option_canonical_sku,
        InventoryTx.location_to_id,
    ).all()
    for sk, loc_id, s in mrows:
        if loc_id is None:
            continue
        cur = prod_stock.setdefault(sk, {})
        cur[loc_id] = cur.get(loc_id, 0) + int(s or 0)

    # 옵션 → 재고제품 매핑 (제품 공유 v1 대응)
    return {opt: dict(prod_stock.get(psku_map[opt], {})) for opt in option_skus}


def get_total_stock(session) -> int:
    """전체 옵션의 재고 수량 합 (InventoryTx 기반 실시간)."""
    base = session.query(func.coalesce(func.sum(_stock_expr()), 0)).filter(
        InventoryTx.status == 'completed',
    ).scalar() or 0
    # move 의 출발지 -qty 와 도착지 +qty 가 cancel — 전체 합산엔 net 0 영향
    # 위 _stock_expr 가 move 를 -qty 처리 했으므로 도착지 +qty 보정
    move_dest = session.query(func.coalesce(func.sum(InventoryTx.qty), 0)).filter(
        InventoryTx.tx_type == 'move',
        InventoryTx.status == 'completed',
    ).scalar() or 0
    return int(base) + int(move_dest)


def get_in_stock_skus(session, skus_filter: Iterable[str] | None = None) -> set[str]:
    """재고 > 0 인 SKU set. 옵션 전체에서 stock > 0 만 반환."""
    if skus_filter is not None:
        skus_list = list(set(s for s in skus_filter if s))
        if not skus_list:
            return set()
        stock_map = get_stock_batch(session, skus_list)
    else:
        # 전체 — InventoryTx 의 모든 distinct sku 합산
        rows = session.query(InventoryTx.option_canonical_sku).filter(
            InventoryTx.status == 'completed',
            InventoryTx.option_canonical_sku.isnot(None),
        ).distinct().all()
        all_skus = [r[0] for r in rows]
        stock_map = get_stock_batch(session, all_skus)
    return {sk for sk, st in stock_map.items() if st > 0}


def get_stock_summary(session, skus_filter: Iterable[str] | None = None) -> dict:
    """대시보드 통계 — 총 SKU·재고보유 SKU 수·총 재고 합 한 번에.

    skus_filter 가 주어지면 해당 SKU 만 (검색 필터 후 통계).

    Returns:
        {
          'total_skus': int,        # 옵션 총 갯수 (또는 filter 한 갯수)
          'in_stock_skus': int,     # stock > 0 SKU 수
          'total_stock': int,       # stock 합
          'zero_skus': int,         # stock = 0 SKU 수
        }
    """
    if skus_filter is None:
        # 전체 옵션
        from lemouton.sourcing.models import Option
        all_skus = [r[0] for r in session.query(Option.canonical_sku).all()]
    else:
        all_skus = list(set(s for s in skus_filter if s))

    if not all_skus:
        return {'total_skus': 0, 'in_stock_skus': 0, 'total_stock': 0, 'zero_skus': 0}

    stock_map = get_stock_batch(session, all_skus)
    in_stock = sum(1 for sk in all_skus if stock_map.get(sk, 0) > 0)
    # [제품 공유 v1] total_stock 은 재고제품 단위 distinct — 공유 제품 중복 합산 방지
    psku_map = _product_sku_map(session, all_skus)
    _seen: set[str] = set()
    total = 0
    for sk in all_skus:
        p = psku_map.get(sk, sk)
        if p in _seen:
            continue
        _seen.add(p)
        total += stock_map.get(sk, 0)
    return {
        'total_skus': len(all_skus),
        'in_stock_skus': in_stock,
        'total_stock': total,
        'zero_skus': len(all_skus) - in_stock,
    }


def get_stock_breakdown_batch(session, skus: Iterable[str]) -> dict[str, dict]:
    """N SKU 의 위치 카테고리별 재고 batch 조회.

    카테고리 — 기본 3종 + 사용자 추가 위치는 'gross' 로 집계 (그로스 외 임의 위치는 main 인지 gross 인지 판단 불가, 'main' 인 default 위치만 main 으로).

    Returns:
        {sku: {'gross': n, 'main': n, 'unsellable': n}}
    """
    from lemouton.inventory.models import InventoryLocation

    skus_list = list(set(s for s in skus if s))
    if not skus_list:
        return {}

    locs = session.query(InventoryLocation).filter(InventoryLocation.deleted_at.is_(None)).all()
    # 이름 매핑 — 박스히어로 표준 + 사용자 자유 위치는 'gross' 로 폴백
    def _bucket(loc: InventoryLocation) -> str:
        name = (loc.name or '').strip()
        if name == '기본 위치' or getattr(loc, 'is_default', False):
            return 'main'
        if name == '판매불가':
            return 'unsellable'
        return 'gross'  # '그로스' + 사용자 정의 위치 전부

    out: dict[str, dict] = {sk: {'gross': 0, 'main': 0, 'unsellable': 0} for sk in skus_list}
    for loc in locs:
        bucket = _bucket(loc)
        per_loc = get_stock_batch(session, skus_list, location_id=loc.id)
        for sk, qty in per_loc.items():
            out[sk][bucket] = out[sk].get(bucket, 0) + int(qty or 0)
    return out


def get_loc_stock_map(session, sku: str, locations: list) -> dict[int, dict]:
    """1 SKU 의 위치별 재고 + 위치 이름 dict. {loc_id: {name, stock}}.

    locations: InventoryLocation list (소유자가 미리 조회한 후 전달).
    """
    out: dict[int, dict] = {}
    for loc in locations:
        stock = get_stock_by_sku(session, sku, location_id=loc.id)
        out[loc.id] = {'name': loc.name, 'stock': stock}
    return out
