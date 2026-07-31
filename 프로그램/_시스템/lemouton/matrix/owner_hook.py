# -*- coding: utf-8 -*-
"""옵션을 저장할 때 주인(원본 매트릭스)을 저절로 채운다.

🔴 왜 길목 한 곳인가 — 옵션을 만드는 곳이 **11곳**이다(api.py 7 · inventory 2 ·
   boxhero_import · build_service). 한 곳씩 고치면 다음에 새 경로가 생길 때 또 빠지고,
   빠져도 아무도 모른다. 주인 없는 옵션은 조용히 남았다가 나중에 전송에서 빠진다.

   라이브에서 실제로 겪었다 — 옵션함을 만들고 창에서 색상·사이즈를 짜 저장했더니
   옵션 6개가 전부 주인 없이 저장됐다. 창의 저장 경로가 새 칸을 몰랐기 때문.

지어내지 않는다 — 원본 매트릭스가 없으면 **비워둔다.**
그러면 붙이기 창구(`/api/admin/option-owner/backfill`)가 나중에 잡아낸다.
"""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session


def _fill(session, _flush_context=None, _instances=None):
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.sourcing.models import Option

    todo = [o for o in list(session.new) + list(session.dirty)
            if isinstance(o, Option)
            and getattr(o, 'matrix_option_id', None) is None
            and getattr(o, 'model_code', None)]
    if not todo:
        return

    codes = {o.model_code for o in todo}
    # ⚠️ no_autoflush — 안 감싸면 이 조회가 다시 flush 를 부르고 무한히 돈다.
    with session.no_autoflush:
        origins = dict(
            session.query(MatrixOption.model_code, MatrixOption.id)
            .filter(MatrixOption.kind == KIND_ORIGIN,
                    MatrixOption.deleted_at.is_(None),
                    MatrixOption.model_code.in_(codes)).all())
    for o in todo:
        mo_id = origins.get(o.model_code)
        if mo_id is not None:
            o.matrix_option_id = mo_id

    _number(session)


def _number(session):
    """주인이 정해진 옵션에 번호를 붙인다 — `U20260801-000003-01`.

    지어내지 않는다 — 주인(매트릭스)이 없으면 어느 묶음인지 모르니 **비워둔다.**
    """
    from lemouton.matrix.models import MatrixOption
    from lemouton.matrix.option_no import next_seq, option_display_no
    from lemouton.sourcing.models import Option

    todo = [o for o in list(session.new) + list(session.dirty)
            if isinstance(o, Option)
            and not getattr(o, 'display_no', None)
            and getattr(o, 'matrix_option_id', None) is not None]
    if not todo:
        return

    mo_ids = {o.matrix_option_id for o in todo}
    with session.no_autoflush:
        base = dict(session.query(MatrixOption.id, MatrixOption.display_no)
                    .filter(MatrixOption.id.in_(mo_ids)).all())
        # 이미 쓴 번호 — 중간에 지운 것이 있어도 다시 쓰지 않는다.
        used: dict[int, list] = {}
        for mo_id, no in (session.query(Option.matrix_option_id, Option.display_no)
                          .filter(Option.matrix_option_id.in_(mo_ids),
                                  Option.display_no.isnot(None)).all()):
            used.setdefault(mo_id, []).append(no)

    seq = {mo_id: next_seq(used.get(mo_id, [])) for mo_id in mo_ids}
    for o in sorted(todo, key=lambda x: x.canonical_sku or ''):
        mx = base.get(o.matrix_option_id)
        if not mx:
            continue                      # 매트릭스에 번호가 아직 없다 — 비워둔다
        o.display_no = option_display_no(mx, seq[o.matrix_option_id])
        seq[o.matrix_option_id] += 1


def install() -> None:
    """한 번만 건다. 두 번 걸면 같은 일을 두 번 한다."""
    if getattr(install, '_done', False):
        return
    event.listen(Session, 'before_flush', _fill)
    install._done = True
