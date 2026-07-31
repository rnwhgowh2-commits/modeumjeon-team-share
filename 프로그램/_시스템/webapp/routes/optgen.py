# -*- coding: utf-8 -*-
"""옵션생성 & 상품생성 — 허브 + 「직접 만들기」.

설계서: docs/superpowers/specs/2026-08-01-옵션생성-상품생성-탭-design.md
배치 확정: A2 (가로탭 2개 + 옵션 생성 안에서 카드 2장) — 노션 원문 그대로.
화면 확정: E1 — 지금 쓰는 「옵션 조합 생성 및 수정 + 소싱처 URL 매핑」 창을 그대로 쓴다.

★ 창은 `base.html` 이 모든 화면에 싣고 있다(`option_url_modal.js`).
  옵션함의 `model_code` 가 곧 `U…` 번호라, 그 코드를 넘기면 **기존 창이 그대로 열린다.**
  창을 새로 만들지 않는다 — 다시 만들면 반드시 갈린다.
"""
from flask import Blueprint, abort, jsonify, render_template, request

from shared.db import SessionLocal

bp = Blueprint('optgen', __name__, url_prefix='/optgen')

#: 상단 가로탭. ⚠️ 여기 없는 탭은 화면에 아예 안 뜬다(catalog·bulk 와 같은 함정).
SUBTABS = [
    {'key': 'option', 'label': '모음전 옵션 생성',
     'desc': '색상·사이즈를 정해 옵션을 만듭니다'},
    {'key': 'product', 'label': '모음전 상품 생성',
     'desc': '만들어 둔 옵션을 담아 파는 단위를 만듭니다'},
]


def _boxes(session, limit: int = 50):
    """만들어 둔 옵션함 목록 — 만들어 놓고 못 찾으면 만든 의미가 없다.

    판매용 모음전은 섞지 않는다. 섞이면 어느 게 아직 안 파는 건지 알 수 없다.
    """
    from sqlalchemy import func
    from lemouton.sourcing.models import Model, Option
    rows = (session.query(Model.model_code, Model.model_name_display,
                          Model.model_name_raw, Model.brand,
                          func.count(Option.canonical_sku))
            .outerjoin(Option, Option.model_code == Model.model_code)
            .filter(Model.is_option_box.is_(True))
            .group_by(Model.model_code, Model.model_name_display,
                      Model.model_name_raw, Model.brand)
            .order_by(Model.model_code.desc())
            .limit(limit).all())
    return [{'code': c, 'name': (d or r or c), 'brand': b, 'options': n}
            for c, d, r, b, n in rows]


@bp.get('/')
def index():
    tab = request.args.get('tab', 'option')
    if tab not in {t['key'] for t in SUBTABS}:
        tab = 'option'                      # 모르는 값은 조용히 빈 화면 대신 기본 탭
    s = SessionLocal()
    try:
        boxes = _boxes(s) if tab == 'option' else []
    finally:
        s.close()
    return render_template('optgen/index.html',
                           active_app='bundles', active='optgen',
                           subtabs=SUBTABS, tab=tab, boxes=boxes)


@bp.post('/api/option-box')
def api_create_option_box():
    """옵션함을 만든다 — 상품 없이 옵션만 만들기 위한 그릇.

    겉: 매트릭스 옵션 하나 + `U…` 번호 / 속: 모델 1 + 매트릭스 1 (`M…` 없음).
    """
    from lemouton.matrix.service import create_option_box
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        mo = create_option_box(s, name=body.get('name') or '',
                               brand=(body.get('brand') or '르무통').strip(),
                               category=(body.get('category') or None))
        s.commit()
        out = {'ok': True, 'code': mo.model_code,
               'display_no': mo.display_no, 'name': mo.name}
    except ValueError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
    return jsonify(out)


@bp.get('/box/<path:code>')
def box(code: str):
    """옵션함 하나 — 들어오면 색상·사이즈 창이 바로 열린다."""
    from lemouton.sourcing.models import Model, Option
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code, is_option_box=True).first()
        if m is None:
            abort(404)
        info = {'code': m.model_code,
                'name': m.model_name_display or m.model_name_raw or m.model_code,
                'brand': m.brand,
                'options': s.query(Option).filter_by(model_code=code).count()}
    finally:
        s.close()
    return render_template('optgen/box.html',
                           active_app='bundles', active='optgen', box=info)
