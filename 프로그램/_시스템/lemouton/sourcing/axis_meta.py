# -*- coding: utf-8 -*-
"""모음전 옵션 축(axis) 메타 — 이름·값 목록의 단일 진실 원천.

배경: 옵션은 이미 최대 3축(색상·사이즈·재질/안감 등, 이름 자유)을 지원하고
      값도 Option.axis_values_json 에 그대로 저장된다. 그런데 축 메타(축 이름·순서)를
      내려보내는 코드가 `/bundles/<code>/source-urls` 에만 있어서,
      가격 매트릭스(option-matrix)는 색상·사이즈 2축으로 하드코딩돼 있었다.
      → 3축 모음전은 화면에 그릴 재료 자체가 안 왔다.

이 모듈은 그 조립 로직 하나만 담아 여러 라우트가 같은 축 정보를 쓰게 한다.
(원본 구현: webapp/routes/bundles.py 의 axis_steps_payload 조립 — 그대로 옮김)
"""
from __future__ import annotations

import json as _json
from collections import OrderedDict


def axis_values_of(option) -> list[str]:
    """옵션 하나의 축 값 리스트. 레거시 2축은 color/size 로 폴백."""
    raw = getattr(option, 'axis_values_json', None)
    if raw:
        try:
            v = _json.loads(raw)
            if isinstance(v, list) and v:
                return [str(x) for x in v]
        except (ValueError, TypeError):
            pass
    legacy = [getattr(option, 'color_display', None) or getattr(option, 'color_code', None),
              getattr(option, 'size_display', None) or getattr(option, 'size_code', None)]
    return [str(x) for x in legacy if x]


def build_axis_steps(session, model_code, options=None) -> list[dict]:
    """모음전의 축 목록 → [{step_no, axis_name, values[]}, ...].

    BundleOptionStep 이 있으면 그것이 진실 원천.
    없으면(레거시 모음전) 옵션들의 색상·사이즈에서 2축을 추정한다 — read-only,
    DB 에 새로 만들지 않는다.
    """
    steps_payload: list[dict] = []
    try:
        from lemouton.sourcing.models import BundleOptionStep
        rows = (session.query(BundleOptionStep)
                .filter_by(model_code=model_code)
                .order_by(BundleOptionStep.step_no)
                .all())
        for st in rows:
            try:
                vals = _json.loads(st.values_json or '[]')
                if not isinstance(vals, list):
                    vals = []
            except Exception:   # noqa: BLE001
                vals = []
            steps_payload.append({
                'step_no': st.step_no,
                'axis_name': st.axis_name or '',
                'values': [str(v) for v in vals],
            })
    except Exception:   # noqa: BLE001 — 축 조회 실패가 매트릭스 전체를 죽이면 안 된다
        steps_payload = []

    if steps_payload or not options:
        return steps_payload

    # 레거시 폴백 — 색상·사이즈 2축 추정
    colors = list(OrderedDict.fromkeys(
        (getattr(o, 'color_display', None) or getattr(o, 'color_code', None) or '')
        for o in options))
    colors = [c for c in colors if c]
    sizes = list(OrderedDict.fromkeys(
        (getattr(o, 'size_display', None) or getattr(o, 'size_code', None) or '')
        for o in options))
    sizes = [z for z in sizes if z]
    auto = []
    if colors:
        auto.append({'step_no': len(auto) + 1, 'axis_name': '색상', 'values': colors})
    if sizes:
        auto.append({'step_no': len(auto) + 1, 'axis_name': '사이즈', 'values': sizes})
    return auto
