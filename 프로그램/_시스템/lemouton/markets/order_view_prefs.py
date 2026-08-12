# -*- coding: utf-8 -*-
"""주문 내역 화면 설정 — 열 순서·너비, 빠른 기간 버튼, 엑셀 양식 (팀 공유).

사장님(2026-08-12): "기간 직접 만들었는데 자꾸 사라져. 프로그램 재배포 때문인건지?
아니면 탭 옮겼다 오면 사라지는건지 모르겠어."

🔴 원인은 **재배포가 아니었다.** 이 설정들이 전부 브라우저 안(localStorage)에만
   있었다 — 라이브에서 확인하니 빠른 기간·열 구성·엑셀 양식이 셋 다 「없음」이었다.
   그래서 브라우저를 바꾸거나 다른 기기에서 보면 사라진다. 탭 이동과는 무관하다.

🔴 그렇다고 서버 `data/` 에 두면 **그때는 진짜로 배포마다 날아간다**(CLAUDE.md:
   앱 컨테이너 안 data/ 는 배포마다 사라진다). 그래서 `state_store.state_path()` —
   호스트에 마운트돼 배포를 견디는 자리 — 에 둔다.

🔴 팀 전체가 같이 쓴다(사장님 확정). 이 프로젝트는 per-user 분리를 하지 않는다
   (CLAUDE.md: 팀 전체가 같은 데이터 공유). 한 사람이 열 너비를 고치면 모두 같은
   화면을 본다 — 「제 화면이랑 다른데요」가 안 생긴다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from shared.state_store import state_path

logger = logging.getLogger(__name__)

_FILENAME = "order_view_prefs.json"

#: 저장을 허용하는 칸 — 모르는 키는 **버린다**(화면이 아무거나 밀어 넣지 못하게).
_KEYS = ("cols", "widths", "quick", "presets")

#: 한 칸당 상한. 브라우저가 실수로 큰 덩어리를 보내도 상태 파일이 붓지 않게.
_MAX_BYTES = 200_000


def _path() -> Path:
    # 🔴 state_path() 는 **문자열**을 돌려준다 — Path 로 감싸야 exists()/write_text() 가 된다.
    return Path(state_path(_FILENAME))


def load() -> dict:
    """저장된 설정. 없으면 빈 dict — **기본값을 여기서 만들지 않는다**.

    기본값은 화면이 안다(빠른 기간 9개 등). 여기서 또 만들면 두 곳이 갈려서
    「기본값이 왜 다르지」가 생긴다.
    """
    p = _path()
    try:
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("주문 화면 설정을 읽지 못했습니다 — 빈 값으로 시작합니다")
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in _KEYS}


def save(patch: dict) -> dict:
    """보낸 칸만 덮어쓴다(부분 저장). 반환 = 저장 뒤 전체.

    🔴 **덮어쓰기가 아니라 부분 갱신**이다. 화면이 열 너비만 보냈는데 빠른 기간이
      같이 지워지면, 사장님은 「고쳤더니 딴 게 사라졌다」를 겪는다.
    """
    cur = load()
    for k, v in (patch or {}).items():
        if k not in _KEYS:
            continue                      # 모르는 키는 조용히 버린다(저장은 화이트리스트)
        if v is None:
            cur.pop(k, None)              # None = 「기본값으로 되돌리기」
            continue
        try:
            if len(json.dumps(v, ensure_ascii=False)) > _MAX_BYTES:
                raise ValueError(f"{k} 가 너무 큽니다")
        except (TypeError, ValueError) as e:
            raise ValueError(f"저장할 수 없는 값입니다({k}): {e}") from e
        cur[k] = v
    p = _path()
    try:
        p.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        # 조용히 성공한 척하지 않는다 — 사장님이 다시 고치는 헛수고를 하게 된다.
        raise RuntimeError(f"설정을 저장하지 못했습니다: {e}") from e
    return cur
