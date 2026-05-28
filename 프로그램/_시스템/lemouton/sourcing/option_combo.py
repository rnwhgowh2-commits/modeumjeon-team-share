"""단계형 옵션 — 조합 생성 (Phase 2).

ai-workflow cycle 20260521 · Phase 2 · Task 1

단계형 옵션:
  모음전마다 1~3단계. 각 단계 = 이름(자유: 색상·사이즈·모델·재질…) + 값 목록.

이 모듈은 단계 설계 → 옵션 조합을 만드는 **순수 함수**들 (DB 의존 ❌).
  · parse_comma_values  — 1축 쉼표 입력 파싱
  · generate_combinations — 1~3축 cartesian product
  · build_sku           — 모델코드 + 단계 값 → 식별 키 (옛 형식 — 내부 호환용)
  · gen_canonical_sku   — SKU-XXX 형식 (사용자 룰 — 영숫자 8자, 중복 회피)

[2026-05-28] 사용자 룰 (Phase 1):
  - canonical_sku 는 항상 'SKU-XXXXXXXX' 형식 (한글 X).
  - 옵션 중복 검사는 (model_code, axis_values_tuple) 기반.
  - build_sku 는 옵션 매트릭스 매핑 키 (내부 호환) 로만 사용.
"""
from __future__ import annotations

import itertools
import json
import secrets
import string


def parse_comma_values(text: str) -> list[str]:
    """쉼표로 구분된 입력 → 값 리스트.

    공백 trim · 빈 항목 제거 · 입력 순서 유지하며 중복 제거.
    "블랙, 화이트 , 블랙" → ["블랙", "화이트"]
    """
    result: list[str] = []
    for raw in (text or '').split(','):
        v = raw.strip()
        if v and v not in result:
            result.append(v)
    return result


def generate_combinations(steps: list[dict]) -> list[dict]:
    """단계 설계 → 옵션 조합 목록 (cartesian product).

    Args:
        steps: 1~3개. 각 항목 {"axis_name": str, "values": list[str]}.

    Returns:
        각 조합 = {"axes": {축이름: 값, ...}, "values": [값, ...]}.
        steps 가 비었거나 값 없는 단계가 있으면 빈 리스트.

    예: [{"axis_name":"색상","values":["블랙","화이트"]},
         {"axis_name":"사이즈","values":["250","260"]}]
        → 4개 조합 (블랙·250 / 블랙·260 / 화이트·250 / 화이트·260)
    """
    if not steps:
        return []

    names: list[str] = []
    value_lists: list[list[str]] = []
    for st in steps:
        vals = st.get('values') or []
        if not vals:
            return []          # 값 없는 단계 → 조합 불가
        names.append(st.get('axis_name') or '')
        value_lists.append(list(vals))

    combos: list[dict] = []
    for tup in itertools.product(*value_lists):
        combos.append({
            'axes': {names[i]: tup[i] for i in range(len(names))},
            'values': list(tup),
        })
    return combos


def build_sku(model_code: str, values: list[str]) -> str:
    """모델코드 + 단계 값들 → 옵션 식별 키 (내부 호환용).

    [2026-05-28] **canonical_sku 가 아닌 내부 식별 키**.
    옵션 매트릭스 매핑·테스트·기존 호출자 호환을 위해 유지.
    실제 DB canonical_sku 는 `gen_canonical_sku()` 가 생성.

    build_sku("AF", ["블랙", "260"]) → "AF-블랙-260"
    build_sku("AF", [])              → "AF"
    """
    parts = [str(model_code).strip()]
    parts += [str(v).strip() for v in (values or []) if str(v).strip()]
    return '-'.join(p for p in parts if p)


def gen_canonical_sku(existing: set[str]) -> str:
    """SKU-XXX 형식 (사용자 룰) — shared.sku_format.gen_sku 로 위임.

    [2026-05-28] Phase 1-4 — shared 모듈로 통합.
    이 함수는 호환을 위해 유지 (호출자가 점진적으로 shared 직접 사용).
    """
    from shared.sku_format import gen_sku
    return gen_sku(existing)


def steps_from_rows(rows) -> list[dict]:
    """BundleOptionStep ORM 행들 → generate_combinations 입력 형식.

    step_no 오름차순 정렬, values_json 파싱.
    JSON 파싱 실패 시 해당 단계 값은 빈 리스트.

    Args:
        rows: BundleOptionStep 행 (step_no · axis_name · values_json 속성 필요).

    Returns:
        [{"axis_name": str, "values": list[str]}, ...] — step_no 순.
    """
    out: list[dict] = []
    for r in sorted(rows or [], key=lambda x: x.step_no):
        try:
            vals = json.loads(r.values_json or '[]')
        except (ValueError, TypeError):
            vals = []
        if not isinstance(vals, list):
            vals = []
        out.append({'axis_name': r.axis_name, 'values': vals})
    return out


def option_axis_values(option) -> list[str]:
    """옵션의 단계 값 리스트.

    [Phase 2] N축 옵션은 axis_values_json (step 순서 JSON list) 사용.
    레거시 2축 옵션은 color_code / size_code 로 폴백.
    """
    raw = getattr(option, 'axis_values_json', None)
    if raw:
        try:
            v = json.loads(raw)
            if isinstance(v, list) and v:
                return [str(x) for x in v]
        except (ValueError, TypeError):
            pass
    legacy = [getattr(option, 'color_code', None),
              getattr(option, 'size_code', None)]
    return [str(x) for x in legacy if x]


def option_sku(option) -> str:
    """옵션 → canonical_sku (모델코드 + 단계 값 조합)."""
    return build_sku(getattr(option, 'model_code', '') or '',
                     option_axis_values(option))


def build_options_from_steps(
    model_code: str,
    steps: list[dict],
    existing_skus: set[str] | None = None,
    selected: list[list[str]] | None = None,
    existing_axes: set[tuple] | None = None,
) -> list[dict]:
    """단계 설계 → 생성할 Option 사양 목록 (순수 — DB 의존 ❌).

    [2026-05-28] Phase 1-1 변경:
      - canonical_sku 는 SKU-XXX 형식 (사용자 룰).
      - 중복 검사 = (model_code, axis_values_tuple) 기반 (existing_axes).
      - 호환: existing_skus 도 받아 SKU 중복 회피에만 사용 (기존 호출자 깨지지 않게).

    Args:
        model_code: 모음전 코드.
        steps: [{"axis_name","values"}] — generate_combinations 입력.
        existing_skus: 기존 canonical_sku set (SKU-XXX 중복 회피용).
        selected: 일부 조합만. None 이면 전체 cartesian.
        existing_axes: 기존 옵션의 (model_code, tuple(axis_values)) set —
                       중복 옵션 회피. 미전달 시 빈 set (모두 신규로 처리).

    Returns:
        [{"canonical_sku","model_code","axis_values","axis_values_json"}, ...]
    """
    seen_skus: set[str] = set(existing_skus or set())
    seen_axes: set[tuple] = set(existing_axes or set())
    specs: list[dict] = []
    for combo in generate_combinations(steps):
        values = combo['values']
        if selected is not None and values not in selected:
            continue
        axis_key = (model_code, tuple(values))
        if axis_key in seen_axes:
            continue
        seen_axes.add(axis_key)
        # canonical_sku — SKU-XXX 형식 (사용자 룰, 중복 회피)
        sku = gen_canonical_sku(seen_skus)
        specs.append({
            'canonical_sku': sku,
            'model_code': model_code,
            'axis_values': values,
            'axis_values_json': json.dumps(values, ensure_ascii=False),
        })
    return specs


def option_is_offline(option) -> bool:
    """오프라인 전용 옵션인지 — 소싱처 URL 없이 사입 재고만 사용 (Phase 3)."""
    return bool(getattr(option, 'offline_only', False))
