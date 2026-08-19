# -*- coding: utf-8 -*-
"""공급방식(무재고/사입) 저장소 서비스 — 주문 라인 단위.

`purchase_price.py`(실매입가)와 같은 규약을 따른다: line_uid 열쇠, 900개씩 끊어 조회,
기본값은 **행 없음**으로 표현(무재고로 되돌리면 행을 지운다).

재고는 여기서 건드리지 않는다 — 차감은 포장 스캔 시점(사장님 확정).
"""
from __future__ import annotations

from datetime import datetime, timezone

from lemouton.markets.models_supply import (
    DEFAULT_SUPPLY_MODE, SUPPLY_LABELS, SUPPLY_MODES, OrderLineSupply,
)


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def normalize_mode(v) -> str:
    """화면·API 입력을 저장 코드로. 한글 라벨도 받는다. 모르는 값은 ValueError."""
    s = _clean(v).lower()
    if s in ("무재고", "dropship", "drop", "nostock"):
        return "dropship"
    if s in ("사입", "stock", "purchase"):
        return "stock"
    raise ValueError(f"공급방식은 무재고/사입 중 하나여야 해요 (받은 값: {v!r}).")


def label_of(mode) -> str:
    return SUPPLY_LABELS.get(mode, SUPPLY_LABELS[DEFAULT_SUPPLY_MODE])


# ── 저장소 ────────────────────────────────────────────────────────────────

def get_many(session, line_uids) -> dict[str, str]:
    """line_uid → mode. **행이 없으면 키를 안 만든다**(호출부가 기본값을 적용).

    화면은 `get_many_with_default` 를 쓰는 게 편하다.
    """
    uids = [u for u in {_clean(u) for u in (line_uids or [])} if u]
    if not uids:
        return {}
    out: dict[str, str] = {}
    # 🔴 [2026-08-14] 여기 적혀 있던 「SQLite IN 한도(999)」는 **틀린 근거**였다
    #    (999 는 SQLite 3.32 이전 기본값). 실측 한도와 자르는 진짜 이유는
    #    `lemouton/matrix/readiness._CHUNK` 옆 한 곳에만 적어 뒀다. 자르는 것 자체는
    #    그대로 둔다 — 안 자르면 주문 줄이 쌓인 날에만 조회가 통째로 실패한다.
    for i in range(0, len(uids), 900):
        chunk = uids[i:i + 900]
        for row in (session.query(OrderLineSupply)
                    .filter(OrderLineSupply.line_uid.in_(chunk)).all()):
            out[row.line_uid] = row.supply_mode
    return out


def get_many_with_default(session, line_uids) -> dict[str, str]:
    """line_uid → mode. 지정 안 한 줄은 **기본값(무재고)** 으로 채워 돌려준다."""
    uids = [u for u in {_clean(u) for u in (line_uids or [])} if u]
    saved = get_many(session, uids)
    return {u: saved.get(u, DEFAULT_SUPPLY_MODE) for u in uids}


def set_mode(session, *, line_uid, mode, input_by=None, commit: bool = True):
    """한 줄의 공급방식 저장.

    **기본값(무재고)으로 되돌리면 행을 지운다** — 기본값을 행으로 남기지 않는다.
    Returns: 저장된 행 / 지웠거나 애초에 없으면 None.
    """
    uid = _clean(line_uid)
    if not uid:
        raise ValueError("line_uid 가 비었어요 — 어느 주문 줄인지 알 수 없습니다.")
    m = normalize_mode(mode)
    if m not in SUPPLY_MODES:                    # 방어 (normalize 가 이미 걸러냄)
        raise ValueError(f"알 수 없는 공급방식: {mode!r}")

    obj = session.get(OrderLineSupply, uid)
    if m == DEFAULT_SUPPLY_MODE:
        if obj is not None:
            session.delete(obj)
            if commit:
                session.commit()
        return None

    if obj is None:
        obj = OrderLineSupply(line_uid=uid, supply_mode=m, input_by=input_by)
        session.add(obj)
    else:
        obj.supply_mode = m
        if input_by is not None:
            obj.input_by = input_by
        obj.updated_at = datetime.now(timezone.utc)
    if commit:
        session.commit()
    return obj


def set_many(session, *, line_uids, mode, input_by=None) -> dict:
    """여러 줄 일괄 지정 (체크박스 선택 → 「선택 항목을 사입/무재고로」).

    Returns: {'saved': 처리한 수, 'failed': [{line_uid, error}]}
      ※ 키 이름이 'ok' 가 아니다 — API 응답의 성공 플래그(ok)와 겹쳐 덮어썼던 실수를 막는다.
    """
    m = normalize_mode(mode)
    saved, failed = 0, []
    for uid in (line_uids or []):
        try:
            set_mode(session, line_uid=uid, mode=m, input_by=input_by, commit=False)
            saved += 1
        except ValueError as e:
            failed.append({"line_uid": _clean(uid), "error": str(e)})
    session.commit()
    return {"saved": saved, "failed": failed}
