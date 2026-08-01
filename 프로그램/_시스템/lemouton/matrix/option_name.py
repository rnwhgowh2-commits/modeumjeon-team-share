# -*- coding: utf-8 -*-
"""합친 옵션명 — 「메이트 블랙 265」.

노션 — 「2/3축 쪼개져도 **하나의 옵션번호**임(메이트(모델명) 블랙(색상) 265(사이즈))」.
설계서 확정 — **매트릭스 옵션명 + 축 값들을 축 순서대로 공백으로 이어 붙임.**

🔴 저장하지 않고 그때그때 만든다 — 이름이나 축이 바뀌면 저장본은 곧 옛것이 된다.
🔴 축 값은 기존 `option_combo.option_axis_values` 를 그대로 쓴다.
   새로 만들면 2축/3축 폴백 규칙이 두 곳으로 갈린다.
"""
from __future__ import annotations


def full_name(matrix_name: str | None, option) -> str:
    """`메이트` + (블랙, 265) → `메이트 블랙 265`.

    둘 다 없으면 빈 문자열 — 없는 이름을 지어내지 않는다.
    """
    from lemouton.sourcing.option_combo import option_axis_values
    parts = [(matrix_name or '').strip()]
    parts += [str(v).strip() for v in option_axis_values(option)]
    return ' '.join(p for p in parts if p)
