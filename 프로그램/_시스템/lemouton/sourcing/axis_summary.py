# -*- coding: utf-8 -*-
"""옵션 매트릭스 목록 — 줄마다 보여줄 「축 요약」을 **한 번의 조회로** 만든다.

무엇을 만드나 (목록 화면이 줄마다 쓰는 세 가지)
  ① 축 구성    — 「모델 × 색상 × 사이즈」
  ② 모음전 종류 — 「모델 모음전」 / 「색상 모음전」
  ③ 모델명 목록 — 모델 축이 있으면 그 축의 값 전부

🔴 종류는 **저장돼 있지 않다 — 축에서 파생한다.**
   근거는 `webapp/routes/optgen.py` 의 `AXIS_PRESETS` 주석 그대로다:
   「종류는 저장하지 않는다. 축에 「모델」이 있으면 모델모음전이다.
     같은 사실을 두 곳에 두면 언젠가 갈린다.」
   그래서 여기서 「모델」이라는 **글자를 다시 비교하지 않는다** —
   판정은 `axis_slot.is_model_axis` 하나뿐이다. 그 함수는 '모델명'·'model' 도
   같이 알아보므로, 여기서 따로 비교하면 그 목록이 늘어날 때 이 화면만 뒤처진다.
   (같은 부류로 이미 겪은 것: 축 값을 「몇 번째 축인가」로 집어 색상 칸에 모델명이
    들어갔던 사고 — `axis_slot.py` 독스트링)

🔴 왜 배치인가 — 줄마다 조회하면 목록 100줄에 조회가 100번이다. 목록 화면은
   상품이 늘수록 느려지다 어느 날 그냥 안 열린다(에러도 안 난다).
   이 함수는 **줄 수와 무관하게 조회가 1개**이고, 그 사실을 시험이 지킨다.

읽기 전용이다 — 여기서 아무것도 만들지도 고치지도 않는다.
"""
from __future__ import annotations

import json as _json

#: 축 구성 라벨을 잇는 글자 — 「모델 × 색상 × 사이즈」
_JOIN = ' × '

#: 한 번의 IN 절에 넣을 코드 수는 `lemouton/matrix/readiness._CHUNK` 한 곳에서 정한다
#: (거기에 「진짜 한도가 얼마인지」와 「그런데 왜 그보다 훨씬 작게 자르는지」를 실측과
#:  함께 적어 뒀다). 여기 숫자를 또 적으면 안 된다 — 예전에 여기 있던
#:  「SQLite 는 999개가 한도」는 **틀린 근거**였고(999 는 SQLite 3.32 이전 기본값),
#:  같은 숫자가 두 곳에 살면 한쪽만 고쳐졌을 때 그쪽 화면만 계속 안 열린다.
#: 🔴 값은 `axis_batch` **안에서** 읽는다(모듈 맨 위에서 당겨 오면 그 순간 값이 굳어
#:    저쪽을 고쳐도 안 따라온다).


def _values_of(raw) -> list[str]:
    """`values_json`(TEXT 에 담긴 JSON 리스트) → 빈 값을 뺀 문자열 목록.

    🔴 **깨진 JSON 하나에 목록 화면이 통째로 죽으면 안 된다.** 한 줄의 축 값이
       깨졌다고 나머지 99줄까지 못 보면 사고 대응이 막힌다. 그래서 빈 목록으로
       떨어진다 — 다만 **조용히 삼키지는 않는다.** 값이 없는 축은 `empty_axes` 로
       세어 화면에 드러나므로, 「축은 있는데 값이 없다」를 사장님이 볼 수 있다.

    `None` 은 건너뛴다 — 그대로 문자열로 바꾸면 화면에 'None' 이라는
    있지도 않은 값이 찍힌다(없는 것을 지어내지 않는다).
    """
    try:
        parsed = _json.loads(raw or '[]')
    except (ValueError, TypeError):     # 깨진 JSON · TEXT 가 아닌 것
        return []
    if not isinstance(parsed, list):    # 숫자·객체가 들어 있어도 값 목록은 아니다
        return []
    out: list[str] = []
    for v in parsed:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            out.append(s)
    return out


def _blank() -> dict:
    """축이 하나도 없는 줄의 답 — 화면은 이걸 「—」로 그린다.

    부를 때마다 새로 만든다. 상수 하나를 돌려쓰면 호출자가 한 줄을 고칠 때
    다른 줄까지 같이 바뀐다(리스트·딕트는 같은 물건을 가리킨다).
    """
    return {'axis_names': [], 'axis_label': None, 'kind': None,
            'kind_label': None, 'model_names': [], 'empty_axes': 0,
            'axis_counts': []}


def _kind_labels() -> dict[str, str]:
    """종류 → 화면 이름. 이름은 `AXIS_PRESETS` 것을 **그대로 빌려 쓴다.**

    여기에 '모델 모음전' 이라고 다시 적으면, 만들기 화면에서 이름을 바꿨을 때
    목록만 옛 이름으로 남는다 — 같은 사실이 두 곳에 있으면 언젠가 갈린다.

    늦게(함수 안에서) 들여온다 — 옵션생성 화면이 이 모듈을 쓰게 되면
    서로 물어 import 가 막히기 때문이다.

    프리셋에 없는 종류면 이름이 **없다(None)** — 지어내지 않는다.
    """
    from webapp.routes.optgen import AXIS_PRESETS
    return {p['kind']: p['label'] for p in AXIS_PRESETS if p.get('kind')}


def axis_batch(session, codes: list[str]) -> dict[str, dict]:
    """상품코드 여러 개 → 코드마다 축 요약. **조회는 1개**(코드 500개마다 1개).

    코드 하나가 받는 값:
        axis_names  : ['모델','색상','사이즈']  — `step_no` 순
        axis_label  : '모델 × 색상 × 사이즈'    — 축이 없으면 None
        kind        : 'model' | 'color' | None
        kind_label  : '모델 모음전' | '색상 모음전' | None
        model_names : ['메이트','스위트']       — 모델 축이 없으면 []
        empty_axes  : 값이 하나도 없는 축의 수 (축은 만들었는데 값을 안 채운 것)
        axis_counts : [1,4,3]  — `axis_names` 와 같은 순서·같은 길이.
            축마다 서로 다른 값이 몇 개인지(옵션생성 목록의 「모델 1개 × 색상 4개 ×
            사이즈 3개」 표시가 이 숫자를 그대로 쓴다). 값이 빈 축은 0.

    🔴 **물어본 코드는 전부 돌려준다** — 축이 없는 상품도 빈 답으로 들어 있다.
       화면이 「없으면 이렇게」 폴백을 따로 짜면 그 폴백이 여기와 갈린다.

    🔴 축 순서는 반드시 `step_no` 순이다. 정렬을 빠뜨리면 「모델 × 색상」이
       어느 날 「색상 × 모델」로 보인다 — 에러 없이 화면만 틀리는 종류다.

    종류 판정 — 모델 축이 하나라도 있으면 'model', 아니면 'color'.
      축 이름은 자유(재질·패턴 등)지만 만들기 화면이 `AXIS_PRESETS` 조합만
      허용하므로 종류는 이 둘뿐이다. 축이 아예 없으면 **None** 이다 —
      「색상 모음전인데 축이 없다」가 아니라 **아직 모른다**가 사실이다.
    """
    # 같은 코드를 두 번 물어도 한 번만 조회한다(먼저 나온 순서를 지킨다).
    uniq = [c for c in dict.fromkeys(codes or []) if c]
    out: dict[str, dict] = {c: _blank() for c in uniq}
    if not uniq:
        return out

    from lemouton.matrix.readiness import _CHUNK      # 자르는 크기의 단일 진실 원천

    from .axis_slot import is_model_axis
    from .models import BundleOptionStep

    rows = []
    for i in range(0, len(uniq), _CHUNK):
        rows += (session.query(BundleOptionStep.model_code,
                               BundleOptionStep.step_no,
                               BundleOptionStep.axis_name,
                               BundleOptionStep.values_json)
                 .filter(BundleOptionStep.model_code.in_(uniq[i:i + _CHUNK]))
                 .order_by(BundleOptionStep.model_code,
                           BundleOptionStep.step_no)
                 .all())

    for code, _step_no, axis_name, values_json in rows:
        entry = out.get(code)
        if entry is None:               # 안 물어본 코드 — 있을 수 없지만 넘긴다
            continue
        name = (axis_name or '').strip()
        values = _values_of(values_json)
        entry['axis_names'].append(name)
        entry['axis_counts'].append(len(values))   # 축마다 「서로 다른 값이 몇 개」
        if not values:
            entry['empty_axes'] += 1
        if is_model_axis(name):
            entry['model_names'] += values

    labels = None
    for entry in out.values():
        if not entry['axis_names']:
            continue                    # 축 0개 — 빈 답 그대로
        entry['axis_label'] = _JOIN.join(entry['axis_names'])
        entry['kind'] = ('model' if any(is_model_axis(n) for n in entry['axis_names'])
                         else 'color')
        if labels is None:              # 축이 있는 줄이 하나라도 있을 때만 들여온다
            labels = _kind_labels()
        entry['kind_label'] = labels.get(entry['kind'])
    return out
