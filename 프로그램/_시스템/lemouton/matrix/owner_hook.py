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
    """저장되는 순간의 옵션에 번호를 붙인다 — 규칙은 option_no.number_options 하나뿐."""
    from lemouton.matrix.option_no import number_options
    from lemouton.sourcing.models import Option
    number_options(session, [o for o in list(session.new) + list(session.dirty)
                             if isinstance(o, Option)])


def install() -> None:
    """한 번만 건다. 두 번 걸면 같은 일을 두 번 한다."""
    if getattr(install, '_done', False):
        return
    event.listen(Session, 'before_flush', _fill)
    install._done = True
