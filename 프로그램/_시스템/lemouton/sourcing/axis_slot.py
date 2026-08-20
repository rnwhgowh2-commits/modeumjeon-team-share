# -*- coding: utf-8 -*-
"""축 이름 → 「색상 칸 / 사이즈 칸」 배정 — **한 곳에서만 정한다.**

왜 생겼나 (2026-08-12 · 노션 「모델모음전」 지시)
  사장님이 모델모음전의 축 순서를 **모델 · 색상 · 사이즈**로 확정하셨다.
  그런데 지금까지 프로그램은 「몇 번째 축인가」로 칸을 정하고 있었다:

      color_code = 축값[0] · size_code = 축값[1]        (option_service)
      _AXIS_SLOTS = ('color', 'size') → slot = 슬롯[i]   (축 맞추기)

  그대로 두면 모델을 1축에 놓는 순간 **`color_code` 에 모델명이 들어간다.**
  그 칸은 마켓 전송 formatter·재고·마진·화면이 수백 곳에서 읽는다 —
  경고 없이 값이 틀리는, 이 프로젝트가 가장 조심하는 종류의 사고다.
  (같은 부류의 실사고: 주소 라벨을 소싱처 사실처럼 써서 「자동 4·전부 초록」이었는데
   실제로는 하나도 안 맞았던 건 — webapp/routes/bundles.py 의 `_DAN_REASON` 주석)

두 가지 물음은 **다른 물음**이다
  ① 저장(storage) — 이 축 값을 옛 칸(color_code/size_code) 중 어디에 넣나
     · 옛 칸은 「이름표」가 아니라 **자리**다. 비워 두면 격자가 한 칸으로 뭉개진다.
     · 그래서 이름으로 못 정한 축은 **남은 자리**를 차례로 쓴다(오늘과 같은 결과).
  ② 대조(semantic) — 이 축이 소싱처의 어느 값(색/사이즈)과 짝인가
     · 소싱처는 색·사이즈만 회수한다. 모델은 **짝이 없다** → None.
     · 여기서 억지로 짝지으면 엉뚱한 색의 가격·재고를 가져온다.

원칙
  · 이름을 아는 축이 **먼저** 자리를 잡는다. 모르는 이름은 남은 자리를 채운다.
  · 한 자리에 두 축이 들어가는 일은 없다 — 겹치면 뒤엣것이 None 이 된다.
  · 이름을 하나도 못 알아보면(옛 「단계1·단계2」 같은 것) **오늘 그대로** 위치로 정한다.
    기존 데이터의 동작을 바꾸지 않는 것이 이 모듈의 첫 번째 의무다.
"""
from __future__ import annotations

COLOR = 'color'
SIZE = 'size'

#: 자리 순서 — 옛 칸이 딱 둘뿐이라 이 순서가 곧 「남은 자리」 차례다.
SLOTS: tuple[str, ...] = (COLOR, SIZE)

#: 사장님·화면이 쓰는 축 이름들. 띄어쓰기·대소문자는 아래에서 지운다.
_NAME_SLOT = {
    '색상': COLOR, '색': COLOR, '컬러': COLOR, 'color': COLOR,
    '사이즈': SIZE, '크기': SIZE, 'size': SIZE,
}

#: 모델 축 — **소싱처가 회수하지 않는다.** 대조에서는 짝이 없다(None).
#: 저장에서는 남은 자리를 쓴다(1축짜리 모델 매트릭스가 통째로 빈 칸이 되면 안 되므로).
_MODEL_NAMES = {'모델', '모델명', 'model'}


def _key(name: str | None) -> str:
    return (name or '').strip().lower().replace(' ', '')


def is_model_axis(name: str | None) -> bool:
    """모델 축인가 — 「소싱처에 없다」와 「아직 안 한다」를 화면이 갈라 말하려고 쓴다."""
    return _key(name) in _MODEL_NAMES


def _named(axis_names) -> dict[int, str]:
    """이름으로 자리가 정해지는 축만 {번호: 자리}."""
    out: dict[int, str] = {}
    taken: set[str] = set()
    for i, nm in enumerate(axis_names or []):
        slot = _NAME_SLOT.get(_key(nm))
        if slot and slot not in taken:      # 같은 이름이 두 번 나오면 먼저 것이 이긴다
            out[i] = slot
            taken.add(slot)
    return out


def storage_slots(axis_names) -> list[str | None]:
    """① 저장용 — 축마다 `color_code`/`size_code` 중 어디에 넣을지.

    이름을 아는 축이 먼저 자리를 잡고, 나머지는 **남은 자리**를 차례로 쓴다.

    >>> storage_slots(['색상', '사이즈'])
    ['color', 'size']
    >>> storage_slots(['모델', '색상', '사이즈'])      # 노션 모델모음전
    [None, 'color', 'size']
    >>> storage_slots(['모델', '색상'])
    ['size', 'color']
    >>> storage_slots(['단계1', '단계2'])              # 옛 데이터 — 오늘 그대로
    ['color', 'size']
    """
    names = list(axis_names or [])
    named = _named(names)
    free = [s for s in SLOTS if s not in named.values()]
    out: list[str | None] = []
    for i in range(len(names)):
        if i in named:
            out.append(named[i])
        else:
            out.append(free.pop(0) if free else None)
    return out


def semantic_slots(axis_names) -> list[str | None]:
    """② 대조용 — 축마다 소싱처의 어느 값(색/사이즈)과 짝인지. 없으면 None.

    · 이름을 알면 그 자리.
    · **모델 축은 언제나 None** — 소싱처는 모델을 회수하지 않는다.
    · 그 밖의 모르는 이름은 **오늘 그대로 위치로** 정한다. 단, 이름으로 이미
      임자가 정해진 자리는 넘보지 않는다(한 자리 두 축 금지).

    >>> semantic_slots(['색상', '사이즈'])
    ['color', 'size']
    >>> semantic_slots(['모델', '색상', '사이즈'])
    [None, 'color', 'size']
    >>> semantic_slots(['단계1', '단계2'])             # 옛 데이터 — 오늘 그대로
    ['color', 'size']
    >>> semantic_slots(['색상', '재질'])
    ['color', 'size']
    """
    names = list(axis_names or [])
    named = _named(names)
    used = set(named.values())
    out: list[str | None] = []
    for i, nm in enumerate(names):
        if i in named:
            out.append(named[i])
        elif _key(nm) in _MODEL_NAMES:
            out.append(None)                       # 소싱처에 짝이 없다 — 정해진 사실
        elif i < len(SLOTS) and SLOTS[i] not in used:
            out.append(SLOTS[i])                   # 오늘 그대로(위치)
            used.add(SLOTS[i])
        else:
            out.append(None)
    return out


def legacy_pair(axis_names, values) -> tuple[str, str]:
    """축 값들 → (color_code, size_code). 없으면 빈 문자열.

    `option_service` 두 곳(신규 생성·이름 바꾸기)이 **이 함수 하나만** 쓴다.
    두 곳이 각자 계산하면 언젠가 갈린다 — 실제로 갈려 있던 것을 합친 것이다.

    🔴 축 이름을 못 받으면 **오늘 그대로 위치로** 채운다. 여기서 빈 값을 돌려주면
       이름 바꾸기 한 번에 두 칸이 통째로 비어 격자가 무너진다.
    """
    slots = storage_slots(axis_names or [None] * len(values))
    got = {COLOR: '', SIZE: ''}
    for i, slot in enumerate(slots):
        if slot and i < len(values):
            got[slot] = str(values[i] or '')
    return got[COLOR], got[SIZE]
