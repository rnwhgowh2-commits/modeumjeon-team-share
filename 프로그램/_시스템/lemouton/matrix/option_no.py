# -*- coding: utf-8 -*-
"""옵션마다 붙는 번호 — `U20260801-000003-01`.

노션 — 「옵션별 개별 1축형 옵션번호/옵션명 생성」.
설계서 확정 — **매트릭스 번호 + 순번**. 번호만 봐도 어느 묶음 소속인지 보인다.

🔴 속 열쇠(`canonical_sku`)는 **그대로 둔다.** 252파일 1,715곳이 그 열쇠로 돈다.
   이 번호는 소싱처 옵션에 번호를 붙인 것과 같은 방식으로 **옆에 붙는 표시용**이다.

🔴 순번은 묶음 안에서만 돈다. 중간에 지운 옵션이 있어도 **다시 쓰지 않는다** —
   지운 번호를 재사용하면 옛 기록과 새 옵션이 같은 번호를 갖는다.
"""
from __future__ import annotations

import re

_TAIL = re.compile(r'-(\d+)$')


def option_display_no(matrix_no: str, seq: int) -> str:
    """`U20260801-000003` + 1 → `U20260801-000003-01`.

    두 자리를 넘으면 자리를 늘린다 — 옵션은 126개까지 간다.
    """
    if seq < 1:
        raise ValueError(f'순번은 1부터입니다: {seq}')
    return f'{matrix_no}-{seq:02d}'


def next_seq(existing) -> int:
    """이미 쓴 번호들 다음 순번. 빈 목록이면 1."""
    top = 0
    for no in existing or []:
        if not no:
            continue
        m = _TAIL.search(str(no))
        if m:
            top = max(top, int(m.group(1)))
    return top + 1


def number_options(session, options) -> int:
    """주어진 옵션들에 번호를 붙인다 — **번호를 붙이는 규칙은 여기 하나뿐이다.**

    저장되는 순간(길목 장치)과 소급(창구) 둘 다 이 함수를 부른다.
    두 곳에 규칙을 적으면 반드시 갈린다.

    지어내지 않는다 — 주인(매트릭스)이 없거나 매트릭스에 번호가 없으면 **비워둔다.**
    """
    from lemouton.matrix.models import MatrixOption
    from lemouton.sourcing.models import Option

    todo = [o for o in options
            if not getattr(o, 'display_no', None)
            and getattr(o, 'matrix_option_id', None) is not None]
    if not todo:
        return 0

    mo_ids = {o.matrix_option_id for o in todo}
    with session.no_autoflush:
        base = dict(session.query(MatrixOption.id, MatrixOption.display_no)
                    .filter(MatrixOption.id.in_(mo_ids)).all())
        used: dict[int, list] = {}
        for mo_id, no in (session.query(Option.matrix_option_id, Option.display_no)
                          .filter(Option.matrix_option_id.in_(mo_ids),
                                  Option.display_no.isnot(None)).all()):
            used.setdefault(mo_id, []).append(no)

    seq = {mo_id: next_seq(used.get(mo_id, [])) for mo_id in mo_ids}
    n = 0
    for o in sorted(todo, key=lambda x: x.canonical_sku or ''):
        mx = base.get(o.matrix_option_id)
        if not mx:
            continue                      # 매트릭스에 번호가 아직 없다 — 비워둔다
        o.display_no = option_display_no(mx, seq[o.matrix_option_id])
        seq[o.matrix_option_id] += 1
        n += 1
    return n


def assign_numbers(session, *, limit: int | None = 1000) -> int:
    """이미 DB 에 있는 옵션에 번호를 소급한다. 멱등.

    🔴 라이브에서 잡은 것 — 길목 장치는 **저장되는 순간**의 옵션만 본다.
       이미 있던 955개는 세션에 올라오지도 않아 번호가 안 붙었다.
    """
    from lemouton.sourcing.models import Option
    q = (session.query(Option)
         .filter(Option.display_no.is_(None),
                 Option.matrix_option_id.isnot(None)))
    if limit:
        q = q.limit(limit)
    return number_options(session, q.all())
