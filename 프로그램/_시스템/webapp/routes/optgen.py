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


def _model_code_children():
    """`models.model_code` 를 가리키는 표들 — **표 정의에서 뽑는다.**

    🔴 손으로 나열하면 반드시 빠진다. 실제로 라이브에서 `bundle_option_steps` 를
       빠뜨려 PostgreSQL 이 삭제를 거부했다. 로컬 SQLite 는 이 제약을 강제하지
       않아 테스트로도 안 잡힌다 — 그래서 목록을 사람이 적지 않게 한다.
    """
    from shared.db import Base
    return [t for t in Base.metadata.sorted_tables
            if any(fk.target_fullname == 'models.model_code'
                   for c in t.columns for fk in c.foreign_keys)]

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


def _matrices(session, limit: int = 100):
    """상품으로 만들 수 있는 옵션 묶음 — 원본·파생 모두.

    옵션이 하나도 없는 묶음은 안 보여준다. 담을 게 없어 눌러도 할 일이 없다.
    """
    from sqlalchemy import func
    from lemouton.matrix.models import MatrixOption
    from lemouton.sourcing.models import Model, Option
    rows = (session.query(MatrixOption.id, MatrixOption.display_no,
                          MatrixOption.name, MatrixOption.kind,
                          Model.is_option_box, func.count(Option.canonical_sku))
            .outerjoin(Model, Model.model_code == MatrixOption.model_code)
            .outerjoin(Option, Option.model_code == MatrixOption.model_code)
            .filter(MatrixOption.deleted_at.is_(None))
            .group_by(MatrixOption.id, MatrixOption.display_no, MatrixOption.name,
                      MatrixOption.kind, Model.is_option_box)
            .order_by(MatrixOption.id.desc()).limit(limit).all())
    return [{'id': i, 'no': no or '—', 'name': nm, 'kind': k,
             'box': bool(box), 'options': n}
            for i, no, nm, k, box, n in rows if n]


@bp.get('/')
def index():
    tab = request.args.get('tab', 'option')
    if tab not in {t['key'] for t in SUBTABS}:
        tab = 'option'                      # 모르는 값은 조용히 빈 화면 대신 기본 탭
    s = SessionLocal()
    try:
        boxes = _boxes(s) if tab == 'option' else []
        mats = _matrices(s) if tab == 'product' else []
    finally:
        s.close()
    return render_template('optgen/index.html',
                           active_app='bundles', active='optgen',
                           subtabs=SUBTABS, tab=tab, boxes=boxes, mats=mats)


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
        nm = m.model_name_display or m.model_name_raw or m.model_code
        opts = (s.query(Option).filter_by(model_code=code)
                .order_by(Option.display_no, Option.canonical_sku).all())
        from lemouton.matrix.option_name import full_name
        rows = [{'no': o.display_no, 'name': full_name(nm, o),
                 'color': o.color_display or o.color_code,
                 'size': o.size_display or o.size_code,
                 'active': bool(o.is_active),
                 'stock_on': bool(o.use_purchase_inventory),
                 'stock': int(o.boxhero_stock_total or 0)}
                for o in opts]
        info = {'code': m.model_code, 'name': nm, 'brand': m.brand,
                'options': len(rows), 'rows': rows}
    finally:
        s.close()
    return render_template('optgen/box.html',
                           active_app='bundles', active='optgen', box=info)


@bp.delete('/api/option-box/<path:code>')
def api_delete_option_box(code: str):
    """옵션함을 지운다 — 잘못 만든 묶음을 되돌린다.

    🔴 지우는 건 되돌릴 수 없다. 막을 것을 확실히 막는다.
       · **판매용 모음전은 절대 못 지운다** — 뚫리면 팔고 있는 상품이 통째로 날아간다
       · 그 묶음으로 만든 상품이 있으면 못 지운다 — 상품이 옵션을 잃는다
       · 파생 묶음이 딸려 있으면 못 지운다 — 파생이 가리킬 원본이 사라진다
    """
    from lemouton.matrix.models import BundleMatrixLink, MatrixOption
    from lemouton.sourcing.models import (BundleSourceUrl, Model, Option,
                                          OptionSourceUrlLink)
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return jsonify({'ok': False, 'error': f'그런 묶음이 없습니다: {code}'}), 404
        if not m.is_option_box:
            return jsonify({'ok': False,
                            'error': '판매용 모음전은 여기서 지울 수 없습니다. '
                                     '옵션함(아직 판매 안 함)만 지울 수 있습니다.'}), 400

        mo = s.query(MatrixOption).filter_by(model_code=code).first()
        if mo is not None:
            made = s.query(BundleMatrixLink).filter_by(
                matrix_option_id=mo.id).count()
            if made:
                return jsonify({'ok': False,
                                'error': f'이 묶음으로 만든 상품이 {made}개 있어 지울 수 없습니다. '
                                         '먼저 그 상품을 정리하세요.'}), 400
            derived = s.query(MatrixOption).filter_by(origin_id=mo.id).count()
            if derived:
                return jsonify({'ok': False,
                                'error': f'이 묶음에서 갈라진 묶음이 {derived}개 있어 지울 수 없습니다.'}), 400

        n_opt = s.query(Option).filter_by(model_code=code).count()
        n_url = s.query(BundleSourceUrl).filter_by(model_code=code).count()

        skus = [r[0] for r in s.query(Option.canonical_sku)
                .filter_by(model_code=code).all()]
        if skus:
            (s.query(OptionSourceUrlLink)
             .filter(OptionSourceUrlLink.option_canonical_sku.in_(skus))
             .delete(synchronize_session=False))

        # 🔴 이 묶음을 가리키는 표를 **표 정의에서 찾아** 전부 지운다.
        #   손으로 나열하면 반드시 빠진다 — 라이브에서 실제로 걸렸다
        #   (bundle_option_steps 를 빠뜨려 PostgreSQL 이 삭제를 거부).
        #   로컬 SQLite 는 이 제약을 강제하지 않아 테스트로도 안 잡힌다.
        #   자식 표부터 지우려고 sorted_tables 를 뒤집어 돈다.
        for t in reversed(_model_code_children()):
            for c in t.columns:
                if any(fk.target_fullname == 'models.model_code'
                       for fk in c.foreign_keys):
                    s.execute(t.delete().where(c == code))

        s.query(Model).filter_by(model_code=code).delete(
            synchronize_session=False)
        s.commit()
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()
    return jsonify({'ok': True, 'code': code,
                    'deleted_options': n_opt, 'deleted_urls': n_url})
