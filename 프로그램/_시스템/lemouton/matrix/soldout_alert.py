# -*- coding: utf-8 -*-
"""한 상품의 옵션이 전부 품절되면 알린다. 설계서 규칙 9.

사장님 확정 — **상품은 안 내린다.** 옵션 재고만 0이 되고 마켓이 알아서 품절로
보여준다. 다만 **살 게 하나도 없는 상품 페이지**가 걸려 있는 걸 아셔야 하므로
알림만 드린다.

🔴 알림 유형 「전체품절」은 예전부터 정의돼 있었지만 **부르는 곳이 0곳**이었다.
   즉 알림이 **한 번도 나간 적이 없다.** 정의만 있고 안 도는 거짓 기능이었다.

🔴 재고 0 과 **「확인 불가」(None)** 는 다르다 — 못 구한 것을 품절로 단정하면
   팔 수 있는 걸 품절이라고 알린다. 크롤링 가이드 §무결성 원칙 그대로.

🔴 같은 상품을 매번 다시 알리지 않는다 — 한 번 알리면 표시해 두고,
   다시 팔 수 있게 되면 표시를 지운다(다음에 또 품절되면 다시 알린다).
"""
from __future__ import annotations


def option_sellable(*, source_stocks, own_stock: int) -> bool:
    """이 옵션을 지금 팔 수 있나.

    · 소싱처 재고가 하나라도 1 이상 → 팔 수 있다
    · 사입 재고가 1 이상 → 팔 수 있다 (소싱처가 전부 품절이어도)
    · 🔴 **확인 불가(None)** 가 하나라도 있으면 품절로 단정하지 않는다
    · 🔴 연결된 소싱처가 아예 없으면 「아직 모름」이지 품절이 아니다
    """
    if int(own_stock or 0) > 0:
        return True
    stocks = list(source_stocks or [])
    if not stocks:
        return True                     # 주소를 아직 안 붙인 옵션 — 품절이 아니다
    for v in stocks:
        if v is None:
            return True                 # 확인 불가 — 단정하지 않는다
        if int(v) > 0:
            return True
    return False


def product_all_soldout(sellables) -> bool:
    """상품의 옵션이 전부 못 파는 상태인가.

    🔴 옵션이 하나도 없으면 품절이 아니다 — 아직 안 만든 상품이다.
    """
    vals = list(sellables or [])
    if not vals:
        return False
    return not any(vals)


def scan(session) -> dict:
    """전수 품절 상품을 찾는다(읽기 전용).

    Returns:
        {'checked': n, 'soldout': [{model_code, name, no, options}...],
         'new': [...], 'recovered': [...]}
        new       = 이번에 새로 품절된 것(알릴 대상)
        recovered = 다시 팔 수 있게 된 것(표시를 지울 대상)
    """
    from lemouton.sources.models import OptionSourceLink, SourceOption
    from lemouton.sourcing.models import Model, Option

    models = (session.query(Model)
              .filter(Model.is_option_box.is_(False)).all())
    if not models:
        return {'checked': 0, 'soldout': [], 'new': [], 'recovered': []}

    codes = [m.model_code for m in models]
    opts = (session.query(Option.canonical_sku, Option.model_code,
                          Option.boxhero_stock_total)
            .filter(Option.model_code.in_(codes)).all())
    skus = [o[0] for o in opts]

    stock_by_sku: dict[str, list] = {}
    if skus:
        for sku, st in (session.query(OptionSourceLink.canonical_sku,
                                      SourceOption.current_stock)
                        .join(SourceOption,
                              SourceOption.id == OptionSourceLink.source_option_id)
                        .filter(OptionSourceLink.canonical_sku.in_(skus)).all()):
            stock_by_sku.setdefault(sku, []).append(st)

    by_model: dict[str, list] = {}
    for sku, code, own in opts:
        by_model.setdefault(code, []).append(
            option_sellable(source_stocks=stock_by_sku.get(sku, []),
                            own_stock=own or 0))

    soldout, new, recovered = [], [], []
    for m in models:
        dead = product_all_soldout(by_model.get(m.model_code, []))
        row = {'model_code': m.model_code, 'no': m.display_no,
               'name': m.model_name_display or m.model_name_raw or m.model_code,
               'options': len(by_model.get(m.model_code, []))}
        if dead:
            soldout.append(row)
            if m.soldout_alerted_at is None:
                new.append(row)
        elif m.soldout_alerted_at is not None:
            recovered.append(row)
    return {'checked': len(models), 'soldout': soldout,
            'new': new, 'recovered': recovered}


def notify_new(session, found: dict) -> int:
    """새로 품절된 상품만 알린다. 이미 알린 것은 다시 안 알린다.

    ⚠️ 커밋은 부르는 쪽에서. 알림이 실패해도 표시는 남긴다 —
       실패했다고 매번 다시 보내면 알림이 폭주한다(로그에는 남는다).
    """
    from datetime import datetime, timezone
    from shared.notifier import AlertType, notify
    from lemouton.sourcing.models import Model

    now = datetime.now(timezone.utc)
    n = 0
    for row in found.get('new', []):
        label = f"{row['name']} ({row['no'] or row['model_code']})"
        try:
            notify(AlertType.전체품절, option=label)
        except Exception:                       # noqa: BLE001 — 알림 실패로 멈추지 않는다
            pass
        (session.query(Model).filter_by(model_code=row['model_code'])
         .update({'soldout_alerted_at': now}, synchronize_session=False))
        n += 1
    for row in found.get('recovered', []):
        (session.query(Model).filter_by(model_code=row['model_code'])
         .update({'soldout_alerted_at': None}, synchronize_session=False))
    return n


# ── 크롤이 끝날 때 그 상품만 본다 ─────────────────────────────────────────

def check_one(session, model_code: str) -> bool | None:
    """모음전 하나가 전수 품절인가.

    🔴 전체 스캔(173개)을 크롤마다 돌리면 안 된다 — 크롤은 자주 돈다.
       그래서 **그 상품 하나만** 본다.

    Returns:
        True 전수 품절 · False 팔 수 있음 · None 검사 대상 아님(없는 상품·옵션함)
    """
    from lemouton.sources.models import OptionSourceLink, SourceOption
    from lemouton.sourcing.models import Model, Option

    m = session.get(Model, model_code)
    if m is None or m.is_option_box:
        return None                     # 없는 상품이거나 아직 안 파는 묶음

    opts = (session.query(Option.canonical_sku, Option.boxhero_stock_total)
            .filter(Option.model_code == model_code).all())
    if not opts:
        return False                    # 옵션이 없으면 품절이 아니다
    skus = [o[0] for o in opts]

    stock_by_sku: dict[str, list] = {}
    for sku, st in (session.query(OptionSourceLink.canonical_sku,
                                  SourceOption.current_stock)
                    .join(SourceOption,
                          SourceOption.id == OptionSourceLink.source_option_id)
                    .filter(OptionSourceLink.canonical_sku.in_(skus)).all()):
        stock_by_sku.setdefault(sku, []).append(st)

    return product_all_soldout([
        option_sellable(source_stocks=stock_by_sku.get(sku, []), own_stock=own or 0)
        for sku, own in opts])


def notify_one(session, model_code: str) -> dict:
    """크롤이 끝난 모음전 하나를 보고, 새로 전수 품절이면 알린다.

    🔴 같은 상품을 매번 다시 알리지 않는다 — 크롤은 몇 분마다 돈다.
       다시 팔 수 있게 되면 표시를 비운다(다음에 또 품절되면 다시 알린다).
    ⚠️ 커밋은 부르는 쪽에서. 알림 자체가 실패해도 표시는 남긴다.
    """
    from datetime import datetime, timezone
    from lemouton.sourcing.models import Model

    dead = check_one(session, model_code)
    if dead is None:
        return {'soldout': False, 'sent': 0, 'skipped': True}

    m = session.get(Model, model_code)
    if dead:
        if m.soldout_alerted_at is not None:
            return {'soldout': True, 'sent': 0}      # 이미 알림
        label = f"{m.model_name_display or m.model_name_raw or model_code} " \
                f"({m.display_no or model_code})"
        try:
            from shared.notifier import AlertType, notify
            notify(AlertType.전체품절, option=label)
        except Exception:                # noqa: BLE001 — 알림 실패로 크롤을 깨뜨리지 않는다
            pass
        m.soldout_alerted_at = datetime.now(timezone.utc)
        return {'soldout': True, 'sent': 1}

    if m.soldout_alerted_at is not None:
        m.soldout_alerted_at = None      # 다시 팔 수 있게 됨 — 표시를 비운다
    return {'soldout': False, 'sent': 0}
