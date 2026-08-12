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


def model_name_of(matrix_name: str | None, option, axis_names=None) -> str:
    """이 옵션의 **모델명**. 노션 옵션 b★ 「옵션별 모델 누락 없을지」의 답.

    · 모델 축이 있으면(모델모음전) — 그 축의 값. 옵션마다 다르다.
    · 모델 축이 없으면(색상모음전) — **매트릭스 이름**이 곧 모델명이다.
      노션 「색상모음전의 경우 모델명 별도 표기 필요」 = 축에 없으니 따로 보여 달라는 뜻.

    🔴 이 함수 덕에 **모델명이 비는 옵션이 구조적으로 없다.**
       매트릭스 이름은 만들 때 필수라 항상 있고, 모델 축이 있으면 그 값이 있다.
       새 칸을 만들지 않는다 — 같은 사실을 두 곳에 저장하면 언젠가 갈린다.
    """
    from lemouton.sourcing.axis_slot import is_model_axis
    from lemouton.sourcing.option_combo import option_axis_values

    vals = [str(v).strip() for v in option_axis_values(option)]
    for i, nm in enumerate(axis_names or []):
        if is_model_axis(nm) and i < len(vals) and vals[i]:
            return vals[i]
    return (matrix_name or '').strip()
