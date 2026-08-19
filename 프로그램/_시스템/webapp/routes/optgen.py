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


def _option_children():
    """`options.canonical_sku` 를 가리키는 표들 — **표 정의에서 뽑는다.**

    🔴 손으로 나열하면 반드시 빠진다(모델 쪽에서 이미 겪은 실수와 같은 부류).
       이 표들을 먼저 안 치우면 PostgreSQL 이 옵션 삭제를 거부한다.
    """
    from shared.db import Base
    return [t for t in Base.metadata.sorted_tables
            if any(fk.target_fullname == 'options.canonical_sku'
                   for c in t.columns for fk in c.foreign_keys)]


def _purge_option_traces(session, skus: list[str]) -> dict:
    """옵션을 지우기 전에 그 옵션을 가리키는 것들을 치운다.

    🔴 재고 이력(`inventory_txs`)은 옵션과 **정식으로 묶여 있지 않다**(그냥 문자열 칸).
       그래서 옵션만 지우면 이력이 **유령으로 남고**, 나중에 같은 SKU 가 다시 발급되면
       (`gen_sku` 는 지금 있는 옵션만 피한다) **없던 재고가 되살아난다.**
       사장님이 「재고는 다시 채운다」고 확정하셨으므로 여기서 같이 치운다.
    """
    from lemouton.inventory.models import InventoryTx
    out = {}
    if not skus:
        return out
    for t in reversed(_option_children()):
        for c in t.columns:
            if any(fk.target_fullname == 'options.canonical_sku'
                   for fk in c.foreign_keys):
                n = session.execute(t.delete().where(c.in_(skus))).rowcount or 0
                if n:
                    out[t.name] = out.get(t.name, 0) + n
    n = (session.query(InventoryTx)
         .filter(InventoryTx.option_canonical_sku.in_(skus))
         .delete(synchronize_session=False))
    if n:
        out['inventory_txs'] = n
    return out


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
#  [2026-08-12 노션 하위탭 a · 사장님 A1 확정] 위상을 2단으로 나눈다.
#    위 = 옵션 생성 / 상품 생성   아래 = 직접 / 내마켓 불러오기
#    🔴 `label`·`key`·순서는 **한 글자도 안 바꾼다** — 상단 메뉴(api_sidebar)와
#       같은 3개인지 tests/test_optgen_subtabs3.py 가 label 로 대조한다.
#       `group`·`short` 는 화면이 2단으로 그리기 위해 옆에 붙이는 값이다.
SUBTABS = [
    {'key': 'direct', 'label': '모음전 옵션 생성 (직접)',
     'group': 'option', 'short': '직접',
     'desc': '색상·사이즈를 직접 적어 옵션을 만듭니다'},
    {'key': 'market', 'label': '모음전 옵션 생성 (내마켓 불러오기)',
     'group': 'option', 'short': '내마켓 불러오기',
     'desc': '이미 마켓에서 팔고 있는 상품에서 이름·브랜드를 가져옵니다'},
    {'key': 'product', 'label': '모음전 상품 생성',
     'group': 'product', 'short': '모음전 상품 생성',
     'desc': '만들어 둔 옵션을 담아 파는 단위를 만듭니다'},
]

#: 위 단 — 순서는 SUBTABS 에 나온 순서 그대로(따로 적어 두면 갈린다).
GROUP_LABEL = {'option': '옵션 생성', 'product': '상품 생성'}


def subtab_groups():
    """[(그룹키, 그룹이름, [그 그룹의 하위탭…]), …] — 화면이 2단으로 그릴 재료."""
    out: list = []
    for t in SUBTABS:
        g = t.get('group') or t['key']
        if not out or out[-1][0] != g:
            out.append((g, GROUP_LABEL.get(g, g), []))
        out[-1][2].append(t)
    return out

#: 옛 주소 → 지금 탭. 저장해 둔 바로가기·옛 링크가 조용히 빈 화면으로 가지 않게 한다.
_TAB_ALIAS = {'option': 'direct', 'import': 'market'}


def _boxes(session):
    """만들어 둔 옵션함 목록 — 만들어 놓고 못 찾으면 만든 의미가 없다.

    판매용 모음전은 섞지 않는다. 섞이면 어느 게 아직 안 파는 건지 알 수 없다.

    🔴 [2026-08-12 노션 옵션 e] 예전엔 `model_code` 내림차순 **상위 50개**만 봤다.
       한글 「단」이 영문 「U」보다 뒤라 내림차순 맨 앞을 `단독_…` 이 전부 차지했고,
       라이브에서 **50줄이 전부 재고관리 낱개 제품**이라 사장님이 직접 만드신
       옵션 매트릭스가 **하나도 안 보였다**. 머리줄 숫자 「50」도 전체가 아니라
       상한값이라 화면이 거짓말을 하고 있었다.
       → 상한을 없애고 **최근 만든 순**으로 세우며, 평소 볼 일 없는 것은 `hid` 로
         표시해 화면이 기본으로 감춘다(`/matrix` 가 이미 쓰는 그 규칙 그대로).
    """
    from sqlalchemy import func
    from lemouton.sourcing.models import Model, Option
    rows = (session.query(Model.model_code, Model.model_name_display,
                          Model.model_name_raw, Model.brand, Model.created_at,
                          func.count(Option.canonical_sku))
            .outerjoin(Option, Option.model_code == Model.model_code)
            .filter(Model.is_option_box.is_(True))
            .group_by(Model.model_code, Model.model_name_display,
                      Model.model_name_raw, Model.brand, Model.created_at)
            # 만든 날짜가 없는 옛 줄은 뒤로 — `NULLS LAST` 는 SQLite 에 없어
            # 「비었나」를 첫 정렬 키로 쓴다(False=0 이 먼저).
            .order_by(Model.created_at.is_(None),
                      Model.created_at.desc(), Model.model_code.desc())
            .all())
    # 🔴 [2026-08-12 사장님] 「단독_」 이라는 말을 **화면에서 완전히 없앤다.**
    #   이 글자는 사장님이 알 필요가 없는 프로그램 내부 표시다 — 재고관리에서
    #   「모음전으로도 판다」를 체크 안 했을 때, 옵션을 담을 상자가 필요해서
    #   프로그램이 그 SKU 앞에 붙여 만든 상자 이름일 뿐이다.
    #   `display_name()` 이 그 앞글자를 떼는 일을 이미 하고 있었는데 **이 목록만
    #   안 쓰고 있었다** — 그래서 「단독_SKU-…」 가 이름·번호에 그대로 찍혔다.
    #   속(model_code)은 그대로 둔다. 8곳이 그 앞글자로 창고 물건을 가려내고 있어
    #   건드리면 창고 물건이 판매 목록에 다시 섞인다.
    return [{'code': c, 'shown_code': display_name(None, c),
             'name': display_name(d or r or c, c), 'brand': b, 'options': n,
             # 숨김 = 창고에만 있는 물건 + 빈 묶음(옵션 0) — `/matrix` 와 같은 규칙
             'hid': bool((c or '').startswith(_LEGACY_PREFIX) or n == 0)}
            for c, d, r, b, _ts, n in rows]


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
    # 이름을 안 주면 코드에서 앞글자만 떼어 준다(번호 칸에 쓴다).
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
    rows = (session.query(BundleMatrixLink.matrix_option_id, Model.model_code,
                          Model.model_name_display, Model.display_no)
            .join(Model, Model.model_code == BundleMatrixLink.model_code)
            .filter(BundleMatrixLink.matrix_option_id.in_(ids))
            .order_by(BundleMatrixLink.created_at.desc()).all())
    # [2026-08-12 노션 상품 c-1] 정책이 붙었나 — 바로가기 목적지가 갈린다.
    #   붙었으면 그 상품의 정책·가격 화면으로, 아니면 붙이는 화면으로.
    #   「없는데 보러 가기」는 눌러도 볼 게 없는 헛걸음이다.
    from urllib.parse import quote
    from lemouton.policy.models import BundlePolicyLink
    codes = [r[1] for r in rows]
    has_policy = ({c for (c,) in session.query(BundlePolicyLink.model_code)
                   .filter(BundlePolicyLink.model_code.in_(codes)).all()}
                  if codes else set())
    made: dict[int, list] = {}
    for mo_id, code, name, no in rows:
        made.setdefault(mo_id, []).append({
            'code': code, 'name': display_name(name, code), 'no': no,
            'policy_url': (f'/policies/product/{quote(code)}' if code in has_policy
                           else f'/policies/apply?model={quote(code)}'),
            'policy_tip': ('이 상품의 정책·가격 보기' if code in has_policy
                           else '이 상품에 정책 붙이기'),
        })
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
    # 🔴 [2026-08-12] 머리줄 숫자는 **화면에 실제로 보이는 것**을 센다.
    #    예전엔 `boxes|length` 였는데 목록이 50개에서 잘려 **언제나 「50」**이었다
    #    — 전체 개수가 아니라 상한값을 전체인 양 보여준 것이다.
    box_counts = {'shown': sum(1 for b in boxes if not b.get('hid')),
                  'hidden': sum(1 for b in boxes if b.get('hid')),
                  'all': len(boxes)}
    return render_template('optgen/index.html',
                           active_app='bundles', active='optgen_' + tab,
                           subtabs=SUBTABS, subtab_groups=subtab_groups(),
                           tab=tab, boxes=boxes, mats=mats,
                           made=made, markets=IMPORT_MARKETS,
                           stages=STAGES, stage_label=STAGE_LABEL_MATRIX,
                           stage_cls=STAGE_CLS, mat_counts=mat_counts,
                           box_counts=box_counts, axis_presets=AXIS_PRESETS)


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
        # 🔴 matrix.py 의 같은 404 와 짝 — 한 곳만 고치면 다른 곳이 남는다.
        return render_template('errors/option_not_found.html',
                               active='optgen_product',
                               requested_code='',
                               sku_label='옵션 묶음 번호',
                               requested_sku=str(mo_id)), 404
    return render_template('matrix/detail.html',
                           active_app='bundles', active='optgen_product',
                           assembly=True, detail_base='/optgen/product/', **ctx)


#: 모음전 종류별 축 프리셋 — 노션 옵션 b (사장님 확정 2026-08-12).
#  ⚠️ 종류는 **저장하지 않는다.** 축에 「모델」이 있으면 모델모음전이다.
#     같은 사실을 두 곳에 두면 언젠가 갈린다(이 프로젝트가 반복해 겪은 사고).
#  ⚠️ 축 이름이 곧 색상/사이즈 칸 배정의 근거다 — 규칙은
#     `lemouton/sourcing/axis_slot.py` 한 곳뿐이다.
AXIS_PRESETS = [
    {'kind': 'color', 'label': '색상 모음전',
     'desc': '한 모델을 색상(과 사이즈)으로 펼칩니다',
     'options': [{'n': 1, 'axes': ['색상']},
                 {'n': 2, 'axes': ['색상', '사이즈']}]},
    # [2026-08-13 사장님 확정] 모델 모음전 — **연다.**
    #   🔴 예전엔 「준비 중」으로 막아 뒀는데 **막는 자리가 틀렸다.**
    #      옵션을 3축으로 만드는 것 자체는 온전하다(실측: 축 값 3개·SKU·옵션명 전부 다름).
    #      겹치는 건 **마켓 전송**뿐이다 — 마켓 옵션 이름이 색상+사이즈 두 칸이라
    #      모델이 달라도 「블랙 250」으로 같아진다.
    #      → 위험이 있는 자리(전송)에 막이를 두고 만들기는 연다.
    #        막이 = `lemouton/formatter/pipeline.py` 의 `option_name_collision`.
    #   마켓별로 몇 축으로 쪼개 보낼지는 **상품가공 「정책 생성」** 몫이다(노션 그대로).
    {'kind': 'model', 'label': '모델 모음전',
     'desc': '여러 모델을 한 상품에 담습니다',
     'options': [{'n': 1, 'axes': ['모델']},
                 {'n': 2, 'axes': ['모델', '색상']},
                 {'n': 3, 'axes': ['모델', '색상', '사이즈']}]},
]

#: 프리셋에서 고를 수 있는 축 조합 — 화면이 보낸 값이 이 안에 있는지 검사한다.
_ALLOWED_AXES = {tuple(o['axes']) for p in AXIS_PRESETS for o in p['options']}


@bp.post('/api/option-box')
def api_create_option_box():
    """옵션함을 만든다 — 상품 없이 옵션만 만들기 위한 그릇.

    겉: 매트릭스 옵션 하나 + `U…` 번호 / 속: 모델 1 + 매트릭스 1 (`M…` 없음).

    [2026-08-12 노션 옵션 a] 축을 **이름만** 먼저 저장한다. 값은 지금처럼 큰 창에서
    채운다 — 그 창이 서버가 준 `axis_steps` 로 축 카드를 그대로 복원하므로
    (`option_url_modal.js`), 창을 새로 만들 필요가 없다.
    """
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.option_service import save_step_design
    body = request.get_json(silent=True) or {}
    axes = [str(a).strip() for a in (body.get('axes') or []) if str(a).strip()]
    if axes and tuple(axes) not in _ALLOWED_AXES:
        return jsonify({'ok': False,
                        'error': f'고를 수 없는 축 구성이에요: {" · ".join(axes)}'}), 400
    s = SessionLocal()
    try:
        mo = create_option_box(s, name=body.get('name') or '',
                               brand=(body.get('brand') or '').strip(),
                               category=(body.get('category') or None),
                               memo=(body.get('memo') or None))
        if axes:
            # 값은 비운 채 이름만 — 큰 창이 이 이름으로 축 카드를 채운 채 열린다.
            save_step_design(s, mo.model_code,
                             [{'axis_name': a, 'values': []} for a in axes])
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


def _box_info(session, code: str) -> dict | None:
    """옵션함 하나의 상세 정보 — 화면(box.html)과 모달의 「재고 입력」 드로어가 같이 쓴다.

    🔴 두 벌로 나누면 반드시 갈린다(이 저장소가 여러 번 겪은 사고 패턴) — 그래서
       Jinja 라우트와 JSON API 가 **이 함수 하나**를 부른다.
    """
    from lemouton.sourcing.models import Model, Option
    # [2026-08-01] 옵션함뿐 아니라 **기존 모음전도** 받는다.
    #   🔴 라이브에서 드러난 구멍 — 옵션함만 열려 기존 172개는 404 였고,
    #      그래서 「같은 기능의 입구는 하나」(설계서 규칙 12)를 적용할 수 없었다.
    #   파는 것과 안 파는 것은 화면에서 갈라 보여준다(아래 sellable).
    m = session.query(Model).filter_by(model_code=code).first()
    if m is None:
        return None
    nm = m.model_name_display or m.model_name_raw or m.model_code
    opts = (session.query(Option).filter_by(model_code=code)
            .order_by(Option.display_no, Option.canonical_sku).all())
    # [2026-08-12 노션 옵션 b★] 옵션마다 **모델명이 비지 않게** 한다.
    #   모델 축이 있으면 그 값, 없으면(색상모음전) 매트릭스 이름이 곧 모델명이다.
    #   축 이름은 저장된 단계 설계에서 읽는다 — 새 칸을 만들지 않는다.
    from lemouton.sourcing.models import BundleOptionStep
    axis_names = [a for (a,) in session.query(BundleOptionStep.axis_name)
                  .filter_by(model_code=code)
                  .order_by(BundleOptionStep.step_no).all()]
    # [2026-08-12] 재고 숫자의 출처를 **원장 합계**로 바꾼다.
    #   `Option.boxhero_stock_total` 은 캐시라, 서비스를 안 거친 경로가 갱신을
    #   빠뜨리면 화면 숫자와 실재고가 갈린다(shared/inventory_stock.py 독스트링).
    from shared.inventory_stock import get_stock_batch
    stock = get_stock_batch(session, [o.canonical_sku for o in opts]) if opts else {}
    # 🔴 [2026-08-13] 「재고 0」과 「아직 안 셌음」은 **다른 상태**다. 수량만으로는
    #   못 가르므로 재고 이력이 있는지 따로 본다 — 화면이 0 을 「—」 로 잘못 보이면
    #   사장님이 이미 센 것을 또 세게 된다.
    from lemouton.inventory.models import InventoryTx
    has_tx = {sk for (sk,) in session.query(InventoryTx.option_canonical_sku)
              .filter(InventoryTx.option_canonical_sku.in_(
                  [o.canonical_sku for o in opts] or ['']),
                  InventoryTx.status == 'completed').distinct().all()} if opts else set()
    from lemouton.matrix.option_name import full_name, model_name_of
    rows = [{'no': o.display_no, 'name': full_name(nm, o),
             'sku': o.canonical_sku,
             'model_name': model_name_of(nm, o, axis_names),
             'color': o.color_display or o.color_code,
             'size': o.size_display or o.size_code,
             'active': bool(o.is_active),
             'stock_on': bool(o.use_purchase_inventory),
             'stock': int(stock.get(o.canonical_sku) or 0),
             'tx': o.canonical_sku in has_tx}
            for o in opts]
    return {'code': m.model_code, 'name': nm, 'brand': m.brand,
            'options': len(rows), 'rows': rows,
            'is_box': bool(m.is_option_box), 'no': m.display_no}


@bp.get('/box/<path:code>')
def box(code: str):
    """옵션함 하나 — 들어오면 색상·사이즈 창이 바로 열린다."""
    s = SessionLocal()
    try:
        info = _box_info(s, code)
        if info is None:
            abort(404)
    finally:
        s.close()
    return render_template('optgen/box.html',
                           active_app='bundles', active='optgen_direct', box=info)


@bp.get('/api/box/<path:code>/rows')
def api_box_rows(code: str):
    """옵션함의 옵션 표 — 모달 「📦 재고 입력」 드로어가 연다.

    box.html 과 완전히 같은 자료(`_box_info`)를 JSON 으로 준다 — 어느 화면에서
    창을 열었든(목록·매트릭스 등) 이 드로어가 스스로 채울 수 있게.
    """
    s = SessionLocal()
    try:
        info = _box_info(s, code)
        if info is None:
            return jsonify({'ok': False, 'error': f'그런 묶음이 없습니다: {code}'}), 404
    finally:
        s.close()
    return jsonify({'ok': True, **info})


@bp.post('/api/box/<path:code>/initial-stock')
def api_initial_stock(code: str):
    """옵션 생성 뒤 **초기 재고**를 넣는다 — 노션 옵션 d 「입력 시, 재고 연동 ㄱㄱ!」

    body: {"qty": {"SKU-…": 3, …}}

    🔴 재고는 돈이다. 지키는 것 세 가지:
      ① `options.boxhero_stock_total` 을 **직접 UPDATE 하지 않는다.** 진실 원천은
         `InventoryTx(status='completed')` 합계다(shared/inventory_stock.py).
         `create_inbound` 가 이력을 남기며 그 캐시 칸까지 알아서 갱신한다.
      ② **이미 재고가 있는 옵션은 건너뛴다.** 「초기」가 두 번 들어가면 이중 계상이다.
         무엇을 건너뛰었는지 그대로 돌려준다 — 조용히 넘어가지 않는다.
         🔴 [2026-08-13 감사] 예전엔 「읽고 → 쓰는」 사이에 아무 잠금이 없어,
            같은 요청이 **동시에 두 번** 들어오면 둘 다 「재고 0」을 보고 둘 다 넣었다
            (실측 3/3 두 배 · 캐시는 한쪽만 반영돼 원장과 갈렸다).
            → 옵션 줄을 **먼저 잠그고**(`with_for_update`) 그 뒤에 읽는다.
              PostgreSQL(라이브)은 두 번째 요청이 첫 요청의 커밋을 기다렸다가
              「이미 있다」를 보고 건너뛴다. SQLite 는 이 잠금이 없지만 쓰기를
              직렬화하므로 로컬 시험에서는 재현되지 않는다.
      ③ 위치가 없으면 **기본 위치를 만들어서라도** 넣는다.
         🔴 [2026-08-13 감사] 예전 독스트링은 「거부한다」였는데 **거짓이었다** —
            `ensure_default_location` 은 이름 그대로 없으면 만든다(실패 경로가 없다).
            위치를 지웠다고 초기 재고를 잃는 쪽이 더 나쁘므로 동작을 그대로 두고
            **글을 사실에 맞춘다.**
    """
    import datetime as _dt

    from shared.inventory_stock import get_stock_batch
    from lemouton.inventory.inbound import create_inbound
    from lemouton.inventory.locations import ensure_default_location
    from lemouton.inventory.models import InventoryTx
    from lemouton.sourcing.models import Option

    body = request.get_json(silent=True) or {}
    raw = body.get('qty') or {}
    if not isinstance(raw, dict):
        return jsonify({'ok': False, 'error': 'qty 는 {SKU: 수량} 이어야 해요.'}), 400
    want: dict[str, int] = {}
    for sku, n in raw.items():
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        # 🔴 [2026-08-13 사장님 확정] **공란 ≠ 0.**
        #   공란 = 아직 안 셌다(화면이 아예 안 보낸다) / 0 = **세어 보니 0개였다**(기록한다).
        #   예전엔 `n > 0` 이라 0 을 적어도 조용히 사라졌다. 음수만 거른다.
        if n >= 0:
            want[str(sku)] = n
    if not want:
        return jsonify({'ok': True, 'added': 0, 'skipped': [], 'skus': []})

    s = SessionLocal()
    try:
        # 이 묶음의 옵션만 받는다 — 남의 SKU 에 재고를 꽂으면 안 된다.
        mine = {sku for (sku,) in s.query(Option.canonical_sku)
                .filter(Option.model_code == code,
                        Option.canonical_sku.in_(list(want))).all()}
        stray = [k for k in want if k not in mine]
        if stray:
            return jsonify({'ok': False,
                            'error': f'이 묶음의 옵션이 아니에요: {", ".join(stray[:5])}'}), 400

        # 🔴 읽기 **전에** 옵션 줄을 잠근다 — 동시 요청 이중 계상 막이(위 ② 참조).
        #   SQLite 는 FOR UPDATE 를 모르므로 조용히 건너뛴다(쓰기 직렬화로 대체).
        try:
            (s.query(Option.canonical_sku)
             .filter(Option.canonical_sku.in_(sorted(mine)))   # 순서 고정 = 교착 방지
             .with_for_update().all())
        except Exception:                # noqa: BLE001 — 잠금을 모르는 DB(SQLite)는 정상 경로
            pass

        # 🔴 「이미 넣었나」는 **재고 수량이 아니라 재고 이력**으로 가른다.
        #   0 도 넣을 수 있게 되면서 「재고 0」과 「아직 안 넣음」이 같은 얼굴이 됐다 —
        #   수량으로 가르면 0 을 적을 때마다 입고가 계속 쌓인다.
        from lemouton.inventory.models import InventoryTx
        already = {sku for (sku,) in s.query(InventoryTx.option_canonical_sku)
                   .filter(InventoryTx.option_canonical_sku.in_(sorted(mine)),
                           InventoryTx.status == 'completed').distinct().all()}
        have = get_stock_batch(s, list(mine))          # 원장 합계 = 진실 원천
        loc_id = ensure_default_location(s)
        added, skipped = [], []
        for sku in sorted(mine):
            if sku in already or int(have.get(sku) or 0) > 0:
                skipped.append(sku)                    # 이미 있다 — 두 번 넣지 않는다
                continue
            if want[sku] == 0:
                # 🔴 0 은 **입고가 아니라 「세어 보니 없더라」는 기록**이다.
                #   `create_inbound` 는 `qty<=0` 을 막는다 — 0개를 받았다는 건 말이 안 되니
                #   그 막이는 옳다. 그래서 여기서 원장 줄만 직접 남긴다.
                #   이 줄이 있어야 ① 화면이 「0」을 보여 주고 ② 다음에 또 묻지 않는다
                #   (「재고 0」과 「아직 안 셌다」가 같은 얼굴이 되는 것을 막는다).
                s.add(InventoryTx(
                    tx_type='in', location_id=loc_id, option_canonical_sku=sku,
                    qty=0, status='completed', source='local',
                    created_by='옵션 생성', created_at=_dt.datetime.utcnow(),
                    memo='옵션 생성 초기 재고 — 세어 보니 0개'))
                s.flush()
            else:
                create_inbound(s, location_id=loc_id, option_canonical_sku=sku,
                               qty=want[sku], unit_purchase_price=0,
                               memo='옵션 생성 초기 재고', created_by='옵션 생성')
            added.append(sku)
        s.commit()
    except ValueError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)[:300]}), 500
    finally:
        s.close()
    return jsonify({'ok': True, 'added': len(added), 'skus': added,
                    'skipped': skipped})


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
        # 옵션을 가리키는 것들을 먼저 치운다 — 안 그러면 PostgreSQL 이 삭제를 거부하고,
        # 재고 이력은 유령으로 남아 나중에 같은 SKU 에 되살아난다(위 함수 주석).
        purged_traces = _purge_option_traces(s, skus)
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
                    'deleted_options': n_opt, 'deleted_urls': n_url,
                    'purged': purged_traces})


@bp.post('/api/box/reset-stock')
def api_reset_stock():
    """옛 재고 기록을 치운다 — body: {"codes": [...]}  (옵션·묶음은 그대로 둔다)

    사장님 — 「재고는 다시 재입력해야해. 옛날 재고야.」

    🔴 되돌릴 수 없다. 지우기 전에 **무엇을 얼마나 지우는지 세어 돌려준다.**
    🔴 옵션·묶음은 **안 건드린다.** 이 창구는 재고 이력만 치운다.
    🔴 치운 뒤 캐시 칸(`boxhero_stock_total`)을 원장 기준으로 다시 계산한다 —
       안 하면 화면 숫자와 실제가 갈린다(캐시는 진실 원천이 아니다).
    """
    from lemouton.inventory.cogs import recalc_stock_total
    from lemouton.inventory.models import InventoryTx
    from lemouton.sourcing.models import Option

    body = request.get_json(silent=True) or {}
    codes = [str(c) for c in (body.get('codes') or []) if str(c).strip()]
    if not codes:
        return jsonify({'ok': False, 'error': '묶음을 골라 주세요.'}), 400
    s = SessionLocal()
    try:
        skus = [r[0] for r in s.query(Option.canonical_sku)
                .filter(Option.model_code.in_(codes)).all()]
        if not skus:
            return jsonify({'ok': True, 'boxes': len(codes), 'options': 0,
                            'removed_rows': 0, 'cleared_qty': 0})
        rows = (s.query(InventoryTx)
                .filter(InventoryTx.option_canonical_sku.in_(skus)).all())
        # 지우기 전에 **얼마가 있었는지** 세어 둔다 — 나중에 되짚을 근거.
        before = 0
        for sku in skus:
            try:
                before += int(recalc_stock_total(sku, s) or 0)
            except Exception:                      # noqa: BLE001
                pass
        n = len(rows)
        (s.query(InventoryTx)
         .filter(InventoryTx.option_canonical_sku.in_(skus))
         .delete(synchronize_session=False))
        s.flush()
        # 캐시를 원장(이제 빈 상태) 기준으로 다시 맞춘다.
        #   🔴 `recalc_stock_total` 은 **계산만 하고 저장은 안 한다** — 돌려준 값을
        #      직접 칸에 써야 한다. 안 그러면 화면은 옛 숫자를 계속 보여준다.
        for sku in skus:
            try:
                o = s.get(Option, sku)
                if o is not None:
                    o.boxhero_stock_total = int(recalc_stock_total(sku, s) or 0)
            except Exception:                      # noqa: BLE001
                pass
        s.commit()
    except Exception as e:                          # noqa: BLE001
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)[:300]}), 500
    finally:
        s.close()
    return jsonify({'ok': True, 'boxes': len(codes), 'options': len(skus),
                    'removed_rows': n, 'cleared_qty': before})


@bp.post('/api/option-box/bulk-delete')
def api_bulk_delete_boxes():
    """여러 묶음을 한 번에 지운다 — body: {"codes": [...]}

    🔴 지우는 건 되돌릴 수 없다. **한 개 지우기와 똑같은 검사**를 거친다
       (판매용 모음전 금지 · 이 묶음으로 만든 상품 있으면 금지 · 파생 있으면 금지).
       하나가 막혀도 나머지는 지운다 — 대신 **왜 막혔는지 그대로 돌려준다.**
       조용히 건너뛰면 「지웠다」는 말이 거짓이 된다.
    """
    body = request.get_json(silent=True) or {}
    codes = [str(c) for c in (body.get('codes') or []) if str(c).strip()]
    if not codes:
        return jsonify({'ok': False, 'error': '지울 묶음을 골라 주세요.'}), 400
    done, failed = [], []
    for c in codes:
        r = api_delete_option_box(c)
        payload = r[0] if isinstance(r, tuple) else r
        j = payload.get_json() if hasattr(payload, 'get_json') else {}
        if j.get('ok'):
            done.append({'code': c, 'options': j.get('deleted_options', 0),
                         'purged': j.get('purged') or {}})
        else:
            failed.append({'code': c, 'error': j.get('error') or '지우지 못했습니다.'})
    return jsonify({'ok': True, 'deleted': len(done), 'failed': len(failed),
                    'done': done, 'errors': failed})


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
