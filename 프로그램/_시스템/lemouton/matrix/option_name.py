# -*- coding: utf-8 -*-
"""합친 옵션명 — 「메이트 블랙 265」.

노션 — 「2/3축 쪼개져도 **하나의 옵션번호**임(메이트(모델명) 블랙(색상) 265(사이즈))」.
설계서 확정 — **매트릭스 옵션명 + 축 값들을 축 순서대로 공백으로 이어 붙임.**

🔴 저장하지 않고 그때그때 만든다 — 이름이나 축이 바뀌면 저장본은 곧 옛것이 된다.
🔴 축 값은 기존 `option_combo.option_axis_values` 를 그대로 쓴다.
   새로 만들면 2축/3축 폴백 규칙이 두 곳으로 갈린다.
"""
from __future__ import annotations


def split_model_names(text: str | None) -> list[str]:
    """「메이트, 스위트, 버디」 → `['메이트', '스위트', '버디']`.

    [2026-08-14 사장님 확정] 모델 모음전은 만들기 창에서 모델명을 **쉼표로 나열**해
    받는다. 그 한 줄을 **「모델」 축의 값**으로 바꾸는 곳이 여기 하나다.

    규칙 — 앞뒤 공백 제거 · 빈 값 버리기 · **중복 제거**(먼저 나온 순서 유지).

    🔴 중복을 안 지우면 같은 모델이 축 값에 두 번 들어가고, 조합 생성이 같은 짝을
       두 번 만들어 **SKU 가 중복**된다. 그러면 한 옵션에 가격·재고가 두 벌 생겨
       어느 쪽이 맞는지 알 수 없게 된다 — 에러 없이 돈이 갈리는 자리다.

    🔴 나누는 규칙을 화면(JS)에도 또 적으면 안 된다. 한쪽만 고쳐지면
       사장님이 보는 미리보기와 실제로 저장되는 값이 갈린다.

    >>> split_model_names(' 메이트, 스위트 ,, 버디 , 메이트 ')
    ['메이트', '스위트', '버디']
    >>> split_model_names(None)
    []
    """
    out: list[str] = []
    for part in (text or '').split(','):
        v = part.strip()
        if v and v not in out:
            out.append(v)
    return out


def bundle_model_names(axis_model_values, bundle_model_name: str | None = None
                       ) -> list[str]:
    """묶음 하나가 가진 **모델명 목록** — 목록 화면 오른쪽 판이 쓴다.

    아래 `model_name_of` 와 **같은 순서**로 답한다:
      ① 「모델」 축의 값들이 있으면 → 그 값들
      ② 없고 묶음에 따로 적어 뒀으면 → 그 이름 하나
      ③ 둘 다 없으면 → **빈 목록**

    🔴 ③에서 매트릭스 이름으로 채우지 않는다. 화면은 여기서 「따로 안 짬 —
       이름 그대로 씁니다」라고 말해야 하는데, 채워 버리면 **따로 정한 것**과
       **안 정해서 이름을 쓰는 것**이 화면에서 같아 보인다.

    🔴 왜 `model_name_of` 옆에 두나 — 판정 순서를 목록 화면 파일에 또 적으면,
       순서를 바꾸는 날 한쪽만 바뀌어 **오른쪽 판이 「따로 안 짬」이라 하는데
       마켓엔 적어 둔 모델명이 나가는** 어긋남이 생긴다.

    >>> bundle_model_names(['메이트', '스위트'], '버디')
    ['메이트', '스위트']
    >>> bundle_model_names([], '  메이트  ')
    ['메이트']
    >>> bundle_model_names([], None)
    []
    """
    vals = [str(v).strip() for v in (axis_model_values or []) if str(v).strip()]
    if vals:
        return vals                                  # ① 축의 값 (옵션 단위 사실)
    picked = (bundle_model_name or '').strip()
    return [picked] if picked else []                # ② 묶음 단위 사실 / ③ 없음


def full_name(matrix_name: str | None, option) -> str:
    """`메이트` + (블랙, 265) → `메이트 블랙 265`.

    둘 다 없으면 빈 문자열 — 없는 이름을 지어내지 않는다.
    """
    from lemouton.sourcing.option_combo import option_axis_values
    parts = [(matrix_name or '').strip()]
    parts += [str(v).strip() for v in option_axis_values(option)]
    return ' '.join(p for p in parts if p)


def model_name_of(matrix_name: str | None, option, axis_names=None, *,
                  bundle_model_name: str | None = None) -> str:
    """이 옵션의 **모델명**. 노션 옵션 b★ 「옵션별 모델 누락 없을지」의 답.

    판정 순서 — 구체적인 사실이 먼저다:
      ① 모델 축이 있고 값이 자리에 맞으면 → **그 축의 값** (옵션 하나하나의 사실)
      ② 묶음에 모델명을 따로 적어 뒀으면 → **그 값** (묶음 단위의 사실)
      ③ 아무것도 없으면 → **매트릭스 이름** (예전부터의 동작 · 폴백)

    🔴 ①과 ②의 순서를 뒤집으면 안 된다. 모델모음전은 옵션마다 모델이 다른데
       ②가 먼저 이기면 **전 옵션의 모델명이 하나로 뭉개져 그대로 마켓에 나간다.**
       구매자 드롭다운이 「메이트/스위트」에서 「메이트/메이트」가 되는 사고다.

    🔴 [2026-08-13 사장님 확인 → 새 칸을 만든 이유]
       예전 이 독스트링엔 「새 칸을 만들지 않는다 — 매트릭스 이름이 곧 모델명이다」
       라고 적혀 있었다. 그 전제가 **깨졌다.** 사장님 확인:
         「매트릭스명은 사용자가 지정하기 나름임. 다만, 대부분
          **브랜드 + 모델명 + (사용자 추가)** 이렇게 구성 많이함.」
       즉 이름이 「르무통 메이트 24FW」면 모델명도 통째로 그렇게 저장돼
       마켓 전송 payload 의 `model` 로 나가고 있었다(`policy/to_payload.py`).
       그래서 `Model.bundle_model_name` 칸을 만들고 ②를 끼워 넣었다.
       같은 사실을 두 곳에 두는 게 아니다 — **매트릭스 이름과 모델명은 다른 사실**이다.
       ★ 안 적었으면(NULL) 오늘과 완전히 똑같이 ③으로 떨어진다. 회귀 0.

    🔴 [2026-08-13 감사] 축 번호로 값을 집을 때는 **값의 개수가 축 개수와 같을 때만**
       믿는다. `option_axis_values` 는 `axis_values_json` 이 없으면 (색상,사이즈)로
       떨어지는데, 그 상태에서 축 이름이 ['모델','색상','사이즈'] 면 0번째가 모델로
       잡혀 **색상 값이 모델명으로 찍혔다**(옛 옵션에서 실제로 재현됨).
       개수가 다르면 자리를 못 믿으므로 ②·③으로 떨어진다 — 틀린 값을
       내놓느니 덜 구체적인 값을 내놓는 쪽이 낫다.

    Args:
        matrix_name: 매트릭스(묶음) 이름. 마지막 폴백.
        option: 옵션 행. 축 값을 여기서 읽는다.
        axis_names: 축 이름들 (`BundleOptionStep.axis_name` 을 step 순서대로).
        bundle_model_name: 묶음에 따로 적어 둔 모델명. **None = 「따로 안 정함」**.
    """
    from lemouton.sourcing.axis_slot import is_model_axis
    from lemouton.sourcing.option_combo import option_axis_values

    names = list(axis_names or [])
    vals = [str(v).strip() for v in option_axis_values(option)]
    if len(vals) == len(names):
        for i, nm in enumerate(names):
            if is_model_axis(nm) and vals[i]:
                return vals[i]                       # ① 옵션 단위 사실
    picked = (bundle_model_name or '').strip()
    if picked:
        return picked                                # ② 묶음 단위 사실
    return (matrix_name or '').strip()               # ③ 오늘 동작 · 폴백
