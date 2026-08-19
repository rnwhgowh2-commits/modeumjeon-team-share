"""「주문 관리」 상태 — 항목 관리(추가·이름·색·순서·기본·삭제) + 줄마다 지정.

저장소 정의·설계 근거는 `models_order_status.py` 머리말에 있다(여긴 규칙만).

## 이 모듈이 지키는 것

1. **처음엔 빈 목록** — 기본 항목을 심는 코드가 없다(사장님 확정 a).
2. **이름 중복 금지** — 드롭다운에서 어느 쪽인지 구분이 안 되기 때문.
3. **쓰는 중인 항목은 그냥 안 지운다** — 몇 건이 쓰는지 세어 알리고(`InUseError`),
   `force=True` 일 때만 지운다. 그때 그 주문들은 「지정 안 함」으로 돌아간다.
4. **기본 항목은 전체에서 하나** — 새로 지정하면 기존 것을 같은 트랜잭션에서 내린다.
5. **기본 항목은 저장이 아니라 표시** — `resolve` 가 저장 안 된 줄에 얹어 주되
   `is_fallback: True` 로 밝힌다. 행은 만들지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from lemouton.markets.models_order_status import (COLOR_GRAY, NAME_MAX,
                                                  STATUS_COLORS,
                                                  OrderLineStatus,
                                                  OrderStatusOption)


class InUseError(Exception):
    """쓰는 중인 항목을 `force` 없이 지우려 할 때. 몇 건이 쓰는지 함께 전한다."""

    def __init__(self, count: int, name: str = ""):
        self.count = int(count)
        self.name = name
        super().__init__(f"이 항목을 {self.count}건이 쓰는 중이에요.")


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def _norm_color(v) -> str:
    c = _clean(v).lower()
    if not c:
        return COLOR_GRAY
    if c not in STATUS_COLORS:
        raise ValueError(
            f"색은 {', '.join(STATUS_COLORS)} 중 하나여야 해요 (받은 값: {v!r}).")
    return c


def _norm_name(v) -> str:
    n = _clean(v)
    if not n:
        raise ValueError("항목 이름을 적어 주세요.")
    if len(n) > NAME_MAX:
        raise ValueError(f"항목 이름은 {NAME_MAX}자까지예요.")
    return n


def as_dict(opt: OrderStatusOption) -> dict:
    return {"id": int(opt.id), "name": opt.name, "color": opt.color,
            "sort_no": int(opt.sort_no or 0), "is_default": bool(opt.is_default)}


# ── 항목 목록 ──────────────────────────────────────────────────────────

def usage_counts(session) -> dict:
    """option_id → 그 항목을 쓰는 주문 줄 수. 한 번에 센다(항목마다 세지 않는다)."""
    from sqlalchemy import func

    rows = (session.query(OrderLineStatus.option_id,
                          func.count(OrderLineStatus.line_uid))
            .group_by(OrderLineStatus.option_id).all())
    return {int(oid): int(n) for oid, n in rows}


def list_options(session) -> list:
    """정한 순서대로 + 각 항목을 몇 건이 쓰는지(`used`).

    **처음엔 빈 목록이다** — 기본 항목을 만들어 주지 않는다(사장님 확정 a).
    `used` 를 같이 주는 이유: 삭제 확인창이 「128건이 쓰는 중」인지 「쓰는 주문이
    없어요」인지를 **묻기 전에** 알아야 한다(서버는 그래도 409 로 한 번 더 막는다).
    """
    rows = (session.query(OrderStatusOption)
            .order_by(OrderStatusOption.sort_no, OrderStatusOption.id).all())
    used = usage_counts(session)
    out = []
    for o in rows:
        d = as_dict(o)
        d["used"] = int(used.get(int(o.id), 0))
        out.append(d)
    return out


def get_default(session):
    """기본 항목(없으면 None). 둘 이상이면 순서상 첫 것 — 그런 상태가 나오면 안 되지만
    화면이 죽지는 않게 한다(`set_default` 가 원자적으로 하나만 남긴다)."""
    return (session.query(OrderStatusOption)
            .filter(OrderStatusOption.is_default.is_(True))
            .order_by(OrderStatusOption.sort_no, OrderStatusOption.id).first())


def _name_taken(session, name: str, *, exclude_id=None) -> bool:
    q = session.query(OrderStatusOption).filter(OrderStatusOption.name == name)
    if exclude_id is not None:
        q = q.filter(OrderStatusOption.id != int(exclude_id))
    return session.query(q.exists()).scalar()


def create_option(session, *, name, color=COLOR_GRAY, sort_no=None,
                  is_default=False) -> dict:
    """항목 추가. 이름이 겹치면 `ValueError`(조용히 두 번째를 만들지 않는다)."""
    nm = _norm_name(name)
    cl = _norm_color(color)
    if _name_taken(session, nm):
        raise ValueError(f"「{nm}」 항목이 이미 있어요 — 이름은 겹칠 수 없습니다.")
    if sort_no is None:
        last = (session.query(OrderStatusOption)
                .order_by(OrderStatusOption.sort_no.desc()).first())
        sort_no = (int(last.sort_no or 0) + 1) if last else 0
    obj = OrderStatusOption(name=nm, color=cl, sort_no=int(sort_no),
                            is_default=False)
    session.add(obj)
    session.commit()
    if is_default:
        return set_default(session, obj.id)
    return as_dict(obj)


def set_default(session, option_id) -> dict:
    """기본 항목 지정 — **기존 기본은 자동으로 내린다**(둘 다 True 인 상태가 안 생긴다).

    한 트랜잭션에서 내리고 올린다. 중간에 실패하면 둘 다 안 바뀐다.
    """
    obj = session.get(OrderStatusOption, int(option_id))
    if obj is None:
        raise ValueError("그 항목을 찾을 수 없어요.")
    (session.query(OrderStatusOption)
     .filter(OrderStatusOption.id != obj.id,
             OrderStatusOption.is_default.is_(True))
     .update({OrderStatusOption.is_default: False}, synchronize_session=False))
    obj.is_default = True
    obj.updated_at = datetime.now(timezone.utc)
    session.commit()
    return as_dict(obj)


def clear_default(session) -> None:
    """기본 항목 없음으로. (지정 안 하면 빈 「고르기」 알약이 뜬다)"""
    (session.query(OrderStatusOption)
     .filter(OrderStatusOption.is_default.is_(True))
     .update({OrderStatusOption.is_default: False}, synchronize_session=False))
    session.commit()


def update_option(session, option_id, *, name=None, color=None, sort_no=None,
                  is_default=None) -> dict:
    """이름·색·순서·기본 수정. 준 것만 바꾼다(빈 값으로 덮어쓰지 않는다)."""
    obj = session.get(OrderStatusOption, int(option_id))
    if obj is None:
        raise ValueError("그 항목을 찾을 수 없어요.")
    if name is not None:
        nm = _norm_name(name)
        if _name_taken(session, nm, exclude_id=obj.id):
            raise ValueError(f"「{nm}」 항목이 이미 있어요 — 이름은 겹칠 수 없습니다.")
        obj.name = nm
    if color is not None:
        obj.color = _norm_color(color)
    if sort_no is not None:
        try:
            obj.sort_no = int(sort_no)
        except (TypeError, ValueError):
            raise ValueError("순서는 숫자여야 해요.")
    obj.updated_at = datetime.now(timezone.utc)
    session.commit()
    if is_default is True:
        return set_default(session, obj.id)
    if is_default is False and obj.is_default:
        clear_default(session)
        session.refresh(obj)
    return as_dict(obj)


def reorder(session, ordered_ids) -> list:
    """끌어 놓은 순서 그대로 저장. 목록에 없는 id 는 조용히 무시한다."""
    known = {int(o.id): o for o in session.query(OrderStatusOption).all()}
    n = 0
    for oid in (ordered_ids or []):
        try:
            obj = known.get(int(oid))
        except (TypeError, ValueError):
            continue
        if obj is None:
            continue
        obj.sort_no = n
        n += 1
    session.commit()
    return list_options(session)


def usage_count(session, option_id) -> int:
    """이 항목을 쓰는 주문 줄 수 — 삭제 확인창이 「3건이 쓰는 중」이라 말하는 근거."""
    return int(session.query(OrderLineStatus)
               .filter(OrderLineStatus.option_id == int(option_id)).count())


def delete_option(session, option_id, *, force=False) -> dict:
    """항목 삭제. 쓰는 중이면 `force` 없이는 거절한다(`InUseError`).

    force 로 지우면 그 주문 줄들은 **「지정 안 함」으로 돌아간다** — 이 저장소는
    「값 없음 = 행 없음」이라 딸린 행을 지우는 것이 곧 비우는 것이다.
    """
    obj = session.get(OrderStatusOption, int(option_id))
    if obj is None:
        raise ValueError("그 항목을 찾을 수 없어요.")
    used = usage_count(session, obj.id)
    if used and not force:
        raise InUseError(used, obj.name)
    # 지운 뒤에는 객체를 못 읽는다(detached) — 알려 줄 값을 먼저 챙긴다.
    was_default, name = bool(obj.is_default), obj.name
    (session.query(OrderLineStatus)
     .filter(OrderLineStatus.option_id == obj.id)
     .delete(synchronize_session=False))
    session.delete(obj)
    session.commit()
    return {"deleted": True, "cleared": used, "was_default": was_default,
            "name": name}


# ── 줄마다 지정 ────────────────────────────────────────────────────────

def set_line_status(session, *, line_uid, option_id, updated_by=None):
    """한 줄의 상태 저장. `option_id` 가 None/빈 값이면 **행을 지운다**(= 지정 안 함).

    Returns: 저장된 행 / 지웠거나 애초에 없으면 None.
    """
    uid = _clean(line_uid)
    if not uid:
        raise ValueError("line_uid 가 비었어요 — 어느 주문 줄인지 알 수 없습니다.")
    if option_id in (None, "", 0, "0"):
        obj = session.get(OrderLineStatus, uid)
        if obj is not None:
            session.delete(obj)
            session.commit()
        return None
    try:
        oid = int(option_id)
    except (TypeError, ValueError):
        raise ValueError("항목 번호가 숫자가 아니에요.")
    if session.get(OrderStatusOption, oid) is None:
        raise ValueError("그 항목을 찾을 수 없어요 — 지워졌을 수 있습니다.")
    obj = session.get(OrderLineStatus, uid)
    if obj is None:
        obj = OrderLineStatus(line_uid=uid, option_id=oid, updated_by=updated_by)
        session.add(obj)
    else:
        obj.option_id = oid
        obj.updated_at = datetime.now(timezone.utc)
        if updated_by is not None:
            obj.updated_by = updated_by
    session.commit()
    return obj


def set_many(session, *, line_uids, option_id, updated_by=None) -> dict:
    """고른 여러 줄을 한꺼번에. 열쇠는 반드시 line_uid(주문번호로 묶으면 형제 줄까지 바뀐다)."""
    saved, failed = 0, []
    for uid in (line_uids or []):
        try:
            set_line_status(session, line_uid=uid, option_id=option_id,
                            updated_by=updated_by)
            saved += 1
        except ValueError as e:
            failed.append({"line_uid": _clean(uid), "error": str(e)})
    return {"saved": saved, "failed": failed}


def get_many(session, line_uids) -> dict:
    """line_uid → OrderLineStatus. 없는 것은 키를 안 만든다."""
    uids = [u for u in {_clean(u) for u in (line_uids or [])} if u]
    if not uids:
        return {}
    out = {}
    # 🔴 [2026-08-14] 여기 적혀 있던 「SQLite IN 한도(999) 회피」는 **틀린 근거**였다.
    #    999 는 SQLite 3.32 **이전**의 기본값이다. 진짜 한도의 실측값과 「그런데도 왜
    #    그보다 훨씬 작게 자르는가」는 `lemouton/matrix/readiness._CHUNK` 옆에 적어 뒀다
    #    — 여기 옮겨 적지 않는다(같은 사실이 두 곳에 살면 한쪽만 고쳐진다).
    #    자르는 것 자체는 그대로 둔다: 안 자르면 주문 줄이 쌓인 날에만 조회가 통째로
    #    실패한다(개발할 땐 영영 멀쩡하고 라이브에서만 어느 날 갑자기 터진다).
    for i in range(0, len(uids), 900):
        chunk = uids[i:i + 900]
        for row in (session.query(OrderLineStatus)
                    .filter(OrderLineStatus.line_uid.in_(chunk)).all()):
            out[row.line_uid] = row
    return out


def resolve(session, line_uids) -> dict:
    """line_uid → {option_id, name, color, is_fallback}. 실매입가 `resolve` 와 같은 규약.

    · 저장된 줄     → 그 항목. `is_fallback: False`.
    · 저장 안 된 줄 → **기본 항목이 있으면** 그것을 얹되 `is_fallback: True`
      (화면이 흐리게 보여 준다 — 아직 손대지 않았다는 뜻).
      🔴 여기서 행을 만들지 않는다. 사장님이 고르는 순간에야 진짜 저장된다.
    · 기본 항목이 없으면 그 줄은 응답에 아예 안 담긴다(= 빈 「고르기」 알약).
    """
    want = [u for u in {_clean(x) for x in (line_uids or [])} if u]
    out = {}
    if not want:
        return out
    saved = get_many(session, want)
    opts = {int(o.id): o for o in session.query(OrderStatusOption).all()}
    for uid, row in saved.items():
        o = opts.get(int(row.option_id))
        if o is None:                 # 항목이 지워졌는데 행이 남은 경우 — 지정 안 함으로 본다
            continue
        out[uid] = {"option_id": int(o.id), "name": o.name, "color": o.color,
                    "is_fallback": False}
    dflt = get_default(session)
    if dflt is not None:
        for uid in want:
            if uid in out:
                continue
            out[uid] = {"option_id": int(dflt.id), "name": dflt.name,
                        "color": dflt.color, "is_fallback": True}
    return out
