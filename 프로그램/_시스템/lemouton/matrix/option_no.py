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
