# -*- coding: utf-8 -*-
"""옵션생성 & 상품생성 — 허브 + 「직접 만들기」.

설계서: docs/superpowers/specs/2026-08-01-옵션생성-상품생성-탭-design.md
배치 확정: A2 (가로탭 2개 + 옵션 생성 안에서 카드 2장) — 노션 원문 그대로.
화면 확정: E1 — 지금 쓰는 「옵션 조합 생성 및 수정 + 소싱처 URL 매핑」 창을 그대로 쓴다.

★ 창은 `base.html` 이 모든 화면에 싣고 있다(`option_url_modal.js`).
  옵션함의 `model_code` 가 곧 `U…` 번호라, 그 코드를 넘기면 **기존 창이 그대로 열린다.**
  창을 새로 만들지 않는다 — 다시 만들면 반드시 갈린다.
"""
from flask import (Blueprint, abort, jsonify, redirect, render_template,
                   request, url_for)

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

#: 상단 가로탭 = 노션 「상품 생성 (옵션 생성 & 상품 생성)」 하위탭 3개 그대로.
#  ⚠️ 여기 없는 탭은 화면에 아예 안 뜬다(catalog·bulk 와 같은 함정).
#  ⚠️ 상단 메뉴 펼침에도 같은 3개가 떠야 한다 — 그쪽 원천은 `api_sidebar._STAGE_SPEC`
#     의 `s_collect`. **두 곳을 같이 고치지 않으면 메뉴만 옛것으로 남는다.**
SUBTABS = [
    {'key': 'direct', 'label': '모음전 옵션 생성 (직접)',
     'desc': '색상·사이즈를 직접 적어 옵션을 만듭니다'},
    {'key': 'market', 'label': '모음전 옵션 생성 (내마켓 불러오기)',
     'desc': '이미 마켓에서 팔고 있는 상품에서 이름·브랜드를 가져옵니다'},
    {'key': 'product', 'label': '모음전 상품 생성',
     'desc': '만들어 둔 옵션을 담아 파는 단위를 만듭니다'},
]

#: 옛 주소 → 지금 탭. 저장해 둔 바로가기·옛 링크가 조용히 빈 화면으로 가지 않게 한다.
_TAB_ALIAS = {'option': 'direct', 'import': 'market'}


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
    # [2026-08-04] brand 추가 — 왕쪽 서럍(브랜드로 추리기)이 상품 탭에서도 돌아야 한다.
    rows = (session.query(MatrixOption.id, MatrixOption.display_no,
                          MatrixOption.name, MatrixOption.kind,
                          Model.is_option_box, Model.brand,
                          func.count(Option.canonical_sku),
                          MatrixOption.model_code)
            .outerjoin(Model, Model.model_code == MatrixOption.model_code)
            .outerjoin(Option, Option.model_code == MatrixOption.model_code)
            .filter(MatrixOption.deleted_at.is_(None))
            .group_by(MatrixOption.id, MatrixOption.display_no, MatrixOption.name,
                      MatrixOption.kind, Model.is_option_box, Model.brand,
                      MatrixOption.model_code)
            .order_by(MatrixOption.id.desc()).limit(limit).all())
    out = [{'id': i, 'no': no or '—', 'name': display_name(nm, mc), 'kind': k,
            'box': bool(box), 'brand': br, 'options': n, 'code': mc}
           for i, no, nm, k, box, br, n, mc in rows if n]
    _attach_stage(session, out)
    _attach_made(session, out)
    return out


#: 코드 앞글자 「단독_」 — 옛날에 「재고관리에만 두는 물건」을 문자열로 흉내 낸 흔적.
#: 지금은 정식 상태(is_option_box)가 그 뜻을 맡는다. 코드는 그대로 두되(8곳이 이걸로
#: 걸러낸다 — 건드리면 창고 물건이 판매 목록에 다시 섞인다) **화면에서는 감춘다**.
_LEGACY_PREFIX = '단독_'


def display_name(name: str, code: str | None) -> str:
    """화면에 보일 이름 — 뜻이 안 통하는 코드 앞글자를 떼어 준다.

    이름을 따로 안 지은 옛 물건은 이름이 코드와 같아서 `단독_SKU-…` 로 보였다.
    사장님이 창고에서 쓰시는 번호(SKU-…)만 남기는 편이 오히려 찾기 쉽다.
    뜻(아직 상품 안 만듦)은 옆 「상태」 칸이 이미 말한다.
    """
    nm = (name or '').strip() or (code or '')
    return nm[len(_LEGACY_PREFIX):] if nm.startswith(_LEGACY_PREFIX) else nm


def _attach_made(session, mats):
    """이 묶음으로 **이미 상품을 만들었는지** 붙인다.

    🔴 안 붙이면 화면이 거짓말을 한다 — 상품을 만들어도 그 줄은 계속
       「아직 상품 생성 안 함」이라고 말한다. 기록(BundleMatrixLink)은 이미 있는데
       화면이 안 볼 뿐이다. 그대로 두면 같은 묶음으로 상품을 두 번 만들게 된다.
    """
    from lemouton.matrix.models import BundleMatrixLink
    from lemouton.sourcing.models import Model

    ids = [m['id'] for m in mats if m.get('id')]
    if not ids:
        return
    made: dict[int, list] = {}
    for mo_id, code, name, no in (
            session.query(BundleMatrixLink.matrix_option_id, Model.model_code,
                          Model.model_name_display, Model.display_no)
            .join(Model, Model.model_code == BundleMatrixLink.model_code)
            .filter(BundleMatrixLink.matrix_option_id.in_(ids))
            .order_by(BundleMatrixLink.created_at.desc()).all()):
        made.setdefault(mo_id, []).append(
            {'code': code, 'name': display_name(name, code), 'no': no})
    for m in mats:
        m['made'] = made.get(m['id'], [])


def _attach_shown(mats):
    """줄마다 **화면에 실제로 보일 상태**를 한 번만 정한다.

    🔴 2026-08-07 라이브에서 잡힌 거짓말 — 판은 `stage` 로 세는데 표는 「옵션함인가·
       상품을 만들었나」로 글자를 골랐다. 세는 기준과 보여주는 기준이 갈리니
       판에는 「아직 상품 생성 안 함 0」인데 표에는 그 글자가 **52줄**이었고,
       판의 「상품 생성 적용 81」은 표에 30줄뿐이었다.
       더 나쁜 건 옵션함인데 `stage=4`(마켓 등록·판매중)로 세어져,
       **상품관리에는 없는 물건이 「판매중」 칸에 잡혔다**(라이브 2줄 실측:
       르무통 스위트 메리제인 · SKU-484B2862 — 둘 다 상품관리에 없음).

    그래서 규칙을 여기 한 곳에 두고 표·판·거르기가 이 값을 같이 쓴다.
    """
    for m in mats:
        if m.get('kind') == 'derived':
            m['show'] = 'derived'                             # 갈라진 묶음 — 4상태 밖
        elif m.get('box') or not m.get('code'):
            m['show'] = 'made' if m.get('made') else 'none'   # 옵션함: 상품을 만들었나
        else:
            m['show'] = str(m.get('stage') or '')             # 상품이 된 묶음: 4상태


def _attach_stage(session, mats):
    """묶음마다 「어디까지 왔나」 4가지 상태를 붙인다.

    🔴 판정·말은 상품관리(bundles_tower)의 **단일 원천을 그대로 호출**한다.
       예전엔 여기서 `옵션함이 아니면 판매 중`이라고 따로 정했는데, 그러면
       마켓에 하나도 안 올라간 묶음까지 「판매 중」으로 나온다(상품관리와 같은 오표기).
    """
    from webapp.routes.bundles_tower import (
        STAGE_CLS, STAGE_LABEL_MATRIX, _registered_markets, policy_models, stage_of,
    )

    codes = [m['code'] for m in mats if m.get('code')]
    if not codes:
        return
    policies = policy_models(session, codes)      # 상품 ∪ 구성 — 상품관리와 같은 판정
    markets = _registered_markets(session, codes)
    for m in mats:
        c = m.get('code')
        if not c:
            continue
        st = stage_of(c in policies, bool(markets.get(c)))
        m['stage'] = st
        m['stage_label'] = STAGE_LABEL_MATRIX[st]
        m['stage_cls'] = STAGE_CLS[st]


@bp.get('/')
def index():
    tab = request.args.get('tab', 'direct')
    tab = _TAB_ALIAS.get(tab, tab)
    if tab not in {t['key'] for t in SUBTABS}:
        tab = 'direct'                      # 모르는 값은 조용히 빈 화면 대신 기본 탭
    s = SessionLocal()
    try:
        # 옵션 매트릭스 목록은 **옵션 탭 두 곳 모두**에 깔린다(사장님 확정 B2).
        # 어느 쪽으로 만들었든 이어서 할 자리를 한 군데서 찾게 한다.
        boxes = _boxes(s) if tab in ('direct', 'market') else []
        mats = _matrices(s) if tab == 'product' else []
    finally:
        s.close()
    # [2026-08-06 사장님 확정 2번] 상품을 만들면 이 초기화면으로 돌아온다 —
    #   방금 만든 것(made)을 배너로 알리고 다음 단계(상품 가공)를 가리킨다.
    made = None
    if tab == 'product' and request.args.get('made'):
        made = {'no': request.args.get('made'),
                'code': request.args.get('code') or '',
                'options': request.args.get('opts') or ''}
    # 「어디까지 왔나」 판 — 상품관리와 같은 4상태(사장님 첫 지시 「사이드바에도 구분하자」)
    from webapp.routes.bundles_tower import STAGES, STAGE_CLS, STAGE_LABEL_MATRIX
    _attach_shown(mats)
    mat_counts = {'all': len(mats)}
    for st in STAGES:
        mat_counts['s%d' % st] = sum(1 for m in mats if m.get('show') == str(st))
    for k in ('none', 'made', 'derived'):
        mat_counts[k] = sum(1 for m in mats if m.get('show') == k)
    return render_template('optgen/index.html',
                           active_app='bundles', active='optgen_' + tab,
                           subtabs=SUBTABS, tab=tab, boxes=boxes, mats=mats,
                           made=made, markets=IMPORT_MARKETS,
                           stages=STAGES, stage_label=STAGE_LABEL_MATRIX,
                           stage_cls=STAGE_CLS, mat_counts=mat_counts)


@bp.get('/product/by-code/<path:code>')
def product_assembly_by_code(code: str):
    """상품코드로 조립대에 들어가는 문 — 화면이 매트릭스 id 를 몰라도 된다.

    🔴 [2026-08-12 노션] 왜 만들었나 — 상품관리 목록의 「편집」이 `matrix_id` 가
       있으면 `/optgen/product/<id>`, 없으면 `/bundles/<code>`(다른 메뉴의 다른
       화면)로 **갈라져** 있었다. 단추 이름은 둘 다 「편집 (생성 탭)」인데 한쪽은
       생성 탭이 아니다. 사장님은 이걸 「상태에 따라 결과가 다르다」로 보셨다
       (라이브 실측 2026-08-12: 92개 중 2개가 딴 데로 샜고, 그 2개가 마침 전부
        「정책 적용」 상태라 상태 탓으로 보였다).

    원본이 없으면 **만들어서** 보낸다 — 없다는 이유로 딴 화면으로 새지 않는 것이
    「항상 같아야 함」의 마지막 자물쇠다. 원본 보장 규칙은 `ensure_origin` 하나뿐이니
    여기서 다시 만들지 않는다.
    """
    from lemouton.matrix.service import ensure_origin
    from lemouton.sourcing.models import Model

    s = SessionLocal()
    try:
        m = s.query(Model).filter(Model.model_code == code).one_or_none()
        if m is None:
            return render_template('errors/option_not_found.html',
                                   active='optgen_product',
                                   requested_code=code, requested_sku=''), 404
        mo = ensure_origin(s, m)
        s.commit()
        mo_id = mo.id
    finally:
        s.close()
    return redirect(url_for('optgen.product_assembly', mo_id=mo_id))


@bp.get('/product/<int:mo_id>')
def product_assembly(mo_id: int):
    """조립대 — 하위탭③의 실제 작업 화면 (설계서 §4 「조립대 승격」).

    🔴 여기 오기 전엔 줄을 누르면 `/matrix/<id>`(상품관리 소속)로 가서,
       「생성 탭에서 시작했는데 상품관리에서 작업」하는 어긋남이 있었다
       (2026-08-06 사장님 확정 1번a). 화면 재료는 matrix 쪽 함수를 그대로
       나눠 쓴다 — 두 벌이 되면 반드시 갈린다.
    """
    from webapp.routes.matrix import detail_context
    ctx = detail_context(mo_id)
    if ctx is None:
        return render_template('errors/option_not_found.html',
                               active='optgen_product',
                               requested_code='매트릭스 옵션',
                               requested_sku=str(mo_id)), 404
    return render_template('matrix/detail.html',
                           active_app='bundles', active='optgen_product',
                           assembly=True, detail_base='/optgen/product/', **ctx)


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
                               category=(body.get('category') or None),
                               memo=(body.get('memo') or None))
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
        # [2026-08-01] 옵션함뿐 아니라 **기존 모음전도** 받는다.
        #   🔴 라이브에서 드러난 구멍 — 옵션함만 열려 기존 172개는 404 였고,
        #      그래서 「같은 기능의 입구는 하나」(설계서 규칙 12)를 적용할 수 없었다.
        #   파는 것과 안 파는 것은 화면에서 갈라 보여준다(아래 sellable).
        m = s.query(Model).filter_by(model_code=code).first()
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
                'options': len(rows), 'rows': rows,
                'is_box': bool(m.is_option_box), 'no': m.display_no}
    finally:
        s.close()
    return render_template('optgen/box.html',
                           active_app='bundles', active='optgen_direct', box=info)


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

        # [2026-08-04] 내마켓 가져오기 되돌리기 — 지우기 = 가져오기 취소.
        #   🔴 이걸 안 지우면 두 가지가 영영 남는다:
        #     ① 옵션별 마켓 옵션번호 기록(MarketRegistration) — 죽은 SKU 의 유령 행
        #     ② 캐시 상품의 「이미 가져옴」 잠금(group_id) — 그 마켓 상품을
        #        다시는 못 가져온다(같은 상품 두 번 방지 가드가 이번엔 거꾸로 문다)
        #   옵션함(is_option_box)만 이 길로 오므로 판매 이력이 있는 기록이 아니다.
        from lemouton.catalog.models import MarketProduct, MarketProductGroup
        from lemouton.uploader.models import MarketRegistration
        if skus:
            (s.query(MarketRegistration)
             .filter(MarketRegistration.canonical_sku.in_(skus))
             .delete(synchronize_session=False))
        for g in s.query(MarketProductGroup).filter_by(model_code=code).all():
            (s.query(MarketProduct).filter_by(group_id=g.id)
             .update({'group_id': None}, synchronize_session=False))
            s.delete(g)

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


#: 검색으로 고를 수 있는 마켓 — 화면 라벨. 캐시에 있는 것만 고를 수 있다.
IMPORT_MARKETS = [
    ('smartstore', '스마트스토어'), ('coupang', '쿠팡'), ('lotteon', '롯데온'),
    ('eleven11', '11번가'), ('auction', '옥션'), ('gmarket', 'G마켓'),
]


@bp.post('/api/import-from-market')
def api_import_from_market():
    """마켓 상품에서 옵션함이 태어난다 — 축·옵션번호까지 (지금은 스마트스토어만).

    🔴 실패하면 아무것도 안 만든다(rollback) — 반쪽짜리 옵션함 금지.
    """
    from lemouton.matrix.import_from_market import import_market_product
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        out = import_market_product(
            s, market=body.get('market') or '',
            account_key=body.get('account_key') or '',
            market_product_id=body.get('market_product_id') or '')
        s.commit()
    except ValueError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)[:300]}), 500
    finally:
        s.close()
    return jsonify({'ok': True, **out})


@bp.get('/import')
def import_from_market():
    """내마켓 불러오기 — 이제 하위탭 ②(`/optgen?tab=market`) 안에 있다.

    🔴 화면을 여기 남겨 두면 **같은 기능의 입구가 둘**이 된다(설계서 규칙 12).
       옛 주소·저장해 둔 바로가기가 죽지 않게 탭으로 보내기만 한다.
    """
    return redirect('/optgen?tab=market', code=302)
