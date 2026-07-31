# -*- coding: utf-8 -*-
"""옵션 주인 이관 — 새 주인 칸(`Option.matrix_option_id`) 채우기.

설계서: docs/superpowers/specs/2026-08-01-옵션생성-상품생성-탭-design.md §9
규칙 1 — **옵션의 주인은 원본 매트릭스 하나뿐이다.** 상품이 아니다.

이관을 두 걸음으로 나눈다.

  **2a (이 파일)** — 칸을 만들고 채우기만 한다. 읽는 곳이 아직 없으므로
    화면·크롤·마켓전송·주문매칭은 하나도 안 바뀐다.
    → 기준 지문(`owner_snapshot.collect`)이 **그대로여야 한다.**
      이게 이 걸음의 안전 보증이고, 다르면 즉시 멈춘다.

  **2b (다음)** — 읽는 곳을 새 칸으로 옮기고 `model_code` 를 비워도 되게 푼다.

🔴 옛 칸(`Option.model_code`)을 **지우지 않는다.** 되돌릴 수 있어야 한다.
🔴 원본 매트릭스가 없는 모델은 **조용히 넘기지 않는다.** 넘기면 그 옵션만 주인이
   없는 채 남아 나중에 전송에서 조용히 빠진다.
"""
from __future__ import annotations


def plan_backfill(options, origin_by_model: dict[str, int]):
    """무엇을 붙일지만 정한다(DB 안 건드림). 테스트가 쉬워지고 판단이 한곳에 모인다.

    Args:
        options: `.canonical_sku` · `.model_code` · `.matrix_option_id` 를 가진 행들
        origin_by_model: {model_code: 원본 매트릭스 id}

    Returns:
        (todo, skipped, missing)
        · todo    — [(canonical_sku, matrix_option_id), ...] 새로 붙일 것
        · skipped — 이미 붙어 있어 건드리지 않은 수
        · missing — 원본 매트릭스가 없는 model_code 목록(중복 없음, 정렬)
    """
    todo: list[tuple[str, int]] = []
    skipped = 0
    missing: set[str] = set()
    for o in options:
        if o.matrix_option_id is not None:
            # 이미 붙어 있으면 값이 달라도 덮어쓰지 않는다 —
            # 사장님이 손으로 옮겨둔 것을 멋대로 갈아끼우면 안 된다.
            skipped += 1
            continue
        mo_id = origin_by_model.get(o.model_code)
        if mo_id is None:
            missing.add(o.model_code)
            continue
        todo.append((o.canonical_sku, mo_id))
    return todo, skipped, sorted(missing)


def backfill(session, *, limit: int | None = 1000) -> dict:
    """새 주인 칸을 채운다. 멱등 — 이미 붙은 것은 건드리지 않는다.

    ⚠️ 커밋은 부르는 쪽에서 한다(창구가 지문 대조까지 한 트랜잭션에서 보게).
    """
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.sourcing.models import Option

    origins = dict(session.query(MatrixOption.model_code, MatrixOption.id)
                   .filter(MatrixOption.kind == KIND_ORIGIN,
                           MatrixOption.deleted_at.is_(None),
                           MatrixOption.model_code.isnot(None)).all())

    q = session.query(Option).filter(Option.matrix_option_id.is_(None))
    if limit:
        q = q.limit(limit)
    rows = q.all()

    todo, skipped, missing = plan_backfill(rows, origins)
    by_sku = {sku: mo_id for sku, mo_id in todo}
    for o in rows:
        mo_id = by_sku.get(o.canonical_sku)
        if mo_id is not None:
            o.matrix_option_id = mo_id

    # 번호도 같이 붙인다 — 규칙은 option_no.number_options 한 곳뿐이다.
    #   🔴 길목 장치는 «저장되는 순간»의 옵션만 본다. 이미 DB 에 있던 것은
    #      세션에 올라오지도 않아 번호가 안 붙는다(라이브에서 955개 전부 빈 채였다).
    #      그래서 소급은 따로 부른다.
    session.flush()
    from lemouton.matrix.option_no import assign_numbers
    numbered = assign_numbers(session, limit=limit)
    session.flush()

    left = (session.query(Option)
            .filter(Option.matrix_option_id.is_(None)).count())
    no_number = (session.query(Option)
                 .filter(Option.matrix_option_id.isnot(None),
                         Option.display_no.is_(None)).count())
    return {'attached': len(todo), 'skipped': skipped, 'numbered': numbered,
            'missing_origin': missing, 'remaining': max(0, left),
            'without_number': no_number}
