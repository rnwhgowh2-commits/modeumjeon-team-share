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


def _flag(v) -> bool:
    """주소에 붙은 켬·끔 값 한 벌 — `?made=1` · `?made=on` 을 같은 뜻으로 읽는다.

    🔴 값을 「있으면 켬」으로 읽으면 `?made=0` 도 켬이 된다(끄려고 적은 값에 켜진다).
       그래서 **켜는 글자를 나열**하고 나머지는 전부 끔으로 본다.
    """
    return str(v or '').strip().lower() in ('1', 'on', 'true', 'y', 'yes')


def _빈_박스_숫자() -> dict:
    """옵션함 목록을 안 그리는 탭이 쓸 「전부 0」 숫자표.

    🔴 열쇠 목록을 손으로 또 적으면, `_boxes` 가 열쇠를 하나 늘렸을 때 이쪽만 빠져
       화면이 그 탭에서만 오류로 죽는다. 그래서 위상 이름은 `PHASES` 에서 받아 쓴다.
    """
    from lemouton.matrix.readiness import PHASES
    out = {'shown': 0, 'hidden': 0, 'all': 0, 'made': 0}
    out.update({p: 0 for p in PHASES})
    return out


def _box_facts(session, codes: list[str], option_counts: dict) -> dict:
    """옵션함 줄이 필요로 하는 사실 한 벌 — 축 요약 · 소싱처 URL · 맵핑 진척 · 위상.

    Args:
        codes: 옵션함 `model_code` 목록.
        option_counts: {model_code: 옵션(SKU) 수}. **부르는 쪽이 이미 센 것**을 넘긴다
            — 여기서 다시 세면 화면의 「옵션 5개」와 판정이 쓰는 수가 갈릴 수 있다.

    Returns:
        {'axes','sources','urls','map','phase','sku_info'} — 각각 코드별 표.

    🔴 **모으는 자리를 한 곳으로 둔 이유.** 옵션함 목록(`_boxes`)과 상품생성 탭
       (`_matrices`)이 같은 옵션함을 각자 재면, 한쪽만 규칙이 바뀌었을 때 같은 줄이
       한 화면에선 「준비 완료」, 다른 화면에선 「미완료」가 된다. 에러는 안 나고
       화면만 서로 다른 말을 한다 — 이 저장소가 여러 번 겪은 사고다.

    🔴 **조회는 줄 수와 무관하게 5개**(축 1 · 소싱처 URL 1 · 맵핑 1 · 위상 1 ·
       SKU 번호 진척 1). 줄마다 묻기 시작하면 옵션함 200개 화면이 1,000조회가 된다.

    🔴 맵핑 완료 여부는 **3값 그대로** 위상 판정에 넘긴다. URL 이 0개면 `complete`
       가 `None`(모름)이다. 이걸 `False`(아니다)로 뭉개면 「소싱처 URL 없음」과
       「소싱처 맵핑 미완료」가 **둘 다** 떠서, 실제로는 한 군데(주소 붙이기)인
       할 일이 두 군데인 것처럼 보인다.
    """
    from lemouton.matrix.readiness import phase_batch
    from lemouton.matrix.sku_info import counts_batch as sku_info_counts
    from lemouton.sourcing.axis_summary import axis_batch
    from lemouton.sourcing.source_url_stats import (mapping_coverage,
                                                    url_counts_by_source)

    codes = [c for c in (codes or []) if c]
    option_counts = option_counts or {}
    축 = axis_batch(session, codes)                              # 조회 1
    소싱처 = url_counts_by_source(session, codes)                 # 조회 1
    URL수 = {c: sum(n for _k, n in 소싱처.get(c) or ()) for c in codes}
    맵핑 = mapping_coverage(session, codes, option_counts)        # 조회 1
    위상 = phase_batch(session, codes, options=option_counts,     # 조회 1
                      urls=URL수,
                      mapped={c: 맵핑[c]['complete'] for c in codes},
                      axes=축)
    # 🔴 SKU 번호 진척은 **위상에 안 넣는다.** 품번·바코드·GTIN 이 비어도 상품은
    #    만들어지고 팔린다 — 「준비 완료」 판정에 끼우면 오늘까지 완료였던 줄이
    #    전부 미완료로 뒤집힌다. 목록에서 **따로 보여줄 뿐**이다.
    SKU번호 = sku_info_counts(session, codes, option_counts)      # 조회 1
    return {'axes': 축, 'sources': 소싱처, 'urls': URL수,
            'map': 맵핑, 'phase': 위상, 'sku_info': SKU번호}


def _boxes(session, *, show_made: bool = False):
    """만들어 둔 옵션함 목록 — `(화면에 내려보낼 줄, 머리줄 숫자)` 두 개를 같이 돌려준다.

    판매용 모음전은 섞지 않는다. 섞이면 어느 게 아직 안 파는 건지 알 수 없다.

    🔴 [2026-08-12 노션 옵션 e] 예전엔 `model_code` 내림차순 **상위 50개**만 봤다.
       한글 「단」이 영문 「U」보다 뒤라 내림차순 맨 앞을 `단독_…` 이 전부 차지했고,
       라이브에서 **50줄이 전부 재고관리 낱개 제품**이라 사장님이 직접 만드신
       옵션 매트릭스가 **하나도 안 보였다**. 머리줄 숫자 「50」도 전체가 아니라
       상한값이라 화면이 거짓말을 하고 있었다.
       → 상한을 없애고 **최근 만든 순**으로 세우며, 평소 볼 일 없는 것은 `hid` 로
         표시해 화면이 기본으로 감춘다(`/matrix` 가 이미 쓰는 그 규칙 그대로).

    🔴 [2026-08-14 사장님 확정 3] **상품 생성에 이미 쓰인 옵션함은 기본 목록에서 뺀다.**
       할 일이 남은 것만 보여야 「다음에 뭘 해야 하나」가 한눈에 보인다.
       다 쓴 옵션함이 섞여 있으면 목록이 길어지기만 하고, 사장님이 그걸 다시 눌러
       같은 옵션함으로 상품을 **두 번** 만들 위험도 생긴다.
       필요할 때는 `show_made=True`(주소의 `?made=1`)로 꺼내 본다.

    🔴 **숫자를 이 함수 안에서 같이 만든다.** 줄을 거르는 곳과 세는 곳이 갈리면
       머리줄 숫자와 실제로 보이는 줄이 어긋난다 — 이 화면이 이미 한 번 겪은 사고다
       (위 「50」). 같은 목록에서 바로 세면 갈릴 수가 없다.

    🔴 **줄 수와 무관하게 조회 개수가 고정**이어야 한다. 여기는 상한이 없어 라이브에
       200줄 넘게 나온다 — 줄마다 한 번씩 물으면 화면이 눈에 띄게 느려지다 어느 날
       그냥 안 열린다(에러도 안 난다). 그래서 재료는 전부 **묶음 조회 모듈**에서 받는다.

    돌려주는 줄 한 개가 가진 것 (9칸 + 위상)
        code·shown_code — 속 열쇠(창을 여는 주소) / 창고 번호(「단독_」 뗀 것)
        no·kind         — 번호 정본(`MatrixOption.display_no`) · 원본/파생
        name·brand      — 이름 · 브랜드
        moum_kind·moum_kind_label — 모음전 종류(모델 모음전 / 색상 모음전)
        axis_label      — 축 구성 「모델 × 색상 × 사이즈」
        model_names     — 모델 축의 값들
        options         — 옵션(SKU) 수
        sources·urls    — 소싱처별 URL 수 · 그 합계
        map             — 맵핑 진척 (`mapping_coverage` 결과 그대로)
        phase·missing   — 위상 값과 미완료 사유. **라벨은 안 담는다** —
                          이름·색은 `readiness.PHASE_LABEL`·`PHASE_CLS` 한 곳에서만 온다.
        made·hid        — 상품 생성에 썼나 · 평소 감출 줄인가
                          (🔴 둘은 **겹치지 않는다** — 감추는 이유는 줄마다 하나여야
                           서랍 뱃지가 「켜면 늘어나는 줄 수」를 그대로 말할 수 있다)

    🔴 [2026-08-19 사장님 지시로 재도입] `unbuilt`(미구성 딱지) — 한 번은 「축 없음
       사유와 중복」이라 뺐었다(사장님 확정 4). 그런데 그 사유는 **위상(상태) 칸** 얘기고,
       이번에 붙이는 딱지는 **이름 칸**이다 — 목록을 훑을 때 「이건 아직 아무것도 안 짠
       낱개다」를 상태 칸까지 안 보고도 알아보게 하는 것이 목적이라 겹치지 않는다.
       판정은 여전히 `lemouton/matrix/unbuilt.py` 하나뿐 — 여기서 조건을 다시 안 적고
       그 결과만 그대로 받아 화면 표시 여부만 결정한다(값을 새로 저장하지 않음 — 그
       모듈 머리말의 "매트릭스에 편입했다를 따로 저장하지 않는다" 규칙 그대로).
    """
    from sqlalchemy import and_, func

    from lemouton.matrix.models import MatrixOption
    from lemouton.matrix.option_name import bundle_model_names
    from lemouton.matrix.readiness import PHASE_USED, PHASES
    from lemouton.matrix.unbuilt import unbuilt_batch
    from lemouton.sourcing.models import Model, Option
    from lemouton.sourcing.source_url_stats import source_labels

    rows = (session.query(Model.model_code, Model.model_name_display,
                          Model.model_name_raw, Model.brand, Model.created_at,
                          # 🔴 [2026-08-14] 묶음에 따로 적어 둔 모델명도 같이 읽는다.
                          #    안 읽으면 오른쪽 판이 색상 모음전에 대고 「따로 안 짬」
                          #    이라 말하는데 마켓엔 적어 둔 이름이 나간다
                          #    (보는 것 ≠ 나가는 것). 조회 수는 그대로 1개다.
                          Model.bundle_model_name,
                          # 🔴 `distinct` — 매트릭스 줄이 하나 더 붙는 날에도 옵션 수가
                          #    두 배로 부풀지 않게. 숫자가 조용히 틀리는 자리다.
                          func.count(func.distinct(Option.canonical_sku)),
                          MatrixOption.display_no, MatrixOption.kind)
            .outerjoin(Option, Option.model_code == Model.model_code)
            # 🔴 `deleted_at.is_(None)` 을 빠뜨리면 **지운 매트릭스가 되살아나** 번호를
            #    다시 화면에 올린다. 지운 것은 없는 것이다.
            .outerjoin(MatrixOption,
                       and_(MatrixOption.model_code == Model.model_code,
                            MatrixOption.deleted_at.is_(None)))
            # 🔴 이 조건이 목록의 뼈대다 — 빠지면 판매용 모음전이 옵션함 목록에 섞여
            #    어느 게 아직 안 파는 건지 알 수 없게 된다
            #    (`tests/catalog/test_optgen_direct.py` 가 지킨다).
            .filter(Model.is_option_box.is_(True))
            .group_by(Model.model_code, Model.model_name_display,
                      Model.model_name_raw, Model.brand, Model.created_at,
                      Model.bundle_model_name,
                      MatrixOption.display_no, MatrixOption.kind)
            # 만든 날짜가 없는 옛 줄은 뒤로 — `NULLS LAST` 는 SQLite 에 없어
            # 「비었나」를 첫 정렬 키로 쓴다(False=0 이 먼저).
            .order_by(Model.created_at.is_(None),
                      Model.created_at.desc(), Model.model_code.desc())
            .all())

    codes = [r[0] for r in rows]
    옵션수 = {r[0]: int(r[6] or 0) for r in rows}
    # 이 목록은 `Model.is_option_box.is_(True)` 로만 걸러 뒀으니(위 258행) 전부
    # 옵션함이다 — 다시 조회하지 않고 전부 True 로 넘긴다(이미 세어 둔 것은 또 안 센다).
    미구성 = unbuilt_batch(session, codes, option_counts=옵션수,
                          option_box={c: True for c in codes})
    사실 = _box_facts(session, codes, 옵션수)
    축, 소싱처, URL수, 맵핑, 위상 = (사실['axes'], 사실['sources'], 사실['urls'],
                                 사실['map'], 사실['phase'])
    SKU번호 = 사실['sku_info']

    # 소싱처 이름은 **요청당 한 번만** 부른다 — 줄마다 부르면 그게 곧 N+1 이다
    # (그쪽 독스트링의 경고 그대로). 붙은 주소가 하나도 없으면 아예 안 부른다.
    키들 = sorted({k for v in 소싱처.values() for k, _n in v})
    이름 = source_labels(키들) if 키들 else {}

    # 🔴 [2026-08-12 사장님] 「단독_」 이라는 말을 **화면에서 완전히 없앤다.**
    #   이 글자는 사장님이 알 필요가 없는 프로그램 내부 표시다 — 재고관리에서
    #   「모음전으로도 판다」를 체크 안 했을 때, 옵션을 담을 상자가 필요해서
    #   프로그램이 그 SKU 앞에 붙여 만든 상자 이름일 뿐이다.
    #   `display_name()` 이 그 앞글자를 떼는 일을 이미 하고 있었는데 **이 목록만
    #   안 쓰고 있었다** — 그래서 「단독_SKU-…」 가 이름·번호에 그대로 찍혔다.
    #   속(model_code)은 그대로 둔다. 8곳이 그 앞글자로 창고 물건을 가려내고 있어
    #   건드리면 창고 물건이 판매 목록에 다시 섞인다.
    out: list[dict] = []
    만든것 = 0
    for c, d, r, b, _ts, bmn, n, no, mk in rows:
        ph = 위상[c]
        쓴줄 = ph['phase'] == PHASE_USED
        if 쓴줄:
            만든것 += 1
            if not show_made:
                continue            # 사장님 확정 3 — 다 쓴 옵션함은 기본 목록에서 뺀다
        ax = 축.get(c) or {}
        out.append({
            'code': c, 'shown_code': display_name(None, c),
            'no': no, 'kind': mk,             # 번호 정본 · 원본/파생
            'name': display_name(d or r or c, c), 'brand': b,
            # 미구성 SKU(축 0 · 옵션 1) — 이름 칸 배지용. 판정은 unbuilt.py 하나뿐.
            'unbuilt': c in 미구성,
            # 「모음전 종류」와 위 `kind`(원본/파생)는 **다른 것**이다. 이름이 비슷해
            # 섞이기 쉬워 앞에 `moum_` 을 붙여 둔다.
            'moum_kind': ax.get('kind'), 'moum_kind_label': ax.get('kind_label'),
            'axis_label': ax.get('axis_label'),
            # 🔴 「모델명」은 축 값과 묶음 칸 **두 곳**에서 온다. 순서를 여기서
            #    다시 정하지 않는다 — `option_name.bundle_model_names` 한 곳이
            #    `model_name_of` 와 같은 순서를 지킨다(보는 것 = 나가는 것).
            'model_names': bundle_model_names(ax.get('model_names'), bmn),
            'options': n,
            'sources': [{'key': k, 'label': 이름.get(k) or k, 'n': cnt}
                        for k, cnt in (소싱처.get(c) or ())],
            'urls': URL수.get(c, 0), 'map': 맵핑[c],
            # 🔴 「SKU 정보 상태」 — 품번·바코드·GTIN 을 **셋 따로** 센 진척.
            #    못 센 것은 `None` 이고, 화면은 그걸 0 이 아니라 「—」로 그린다
            #    (`lemouton/matrix/sku_info.py` 가 왜 `None` 인지 적어 뒀다).
            'sku_info': SKU번호[c],
            # 🔴 위상은 **글자가 아니라 값**으로 담는다. 「상품생성 준비 완료」 같은
            #    라벨을 줄마다 복사해 두면 이름을 바꿀 때 한쪽만 바뀐다 —
            #    화면은 `readiness.PHASE_LABEL` 을 열쇠로 찾아 쓴다(원천 하나).
            'phase': ph['phase'], 'missing': ph['missing'],
            'made': 쓴줄,
            # 숨김 = 창고에만 있는 물건 + 빈 묶음(옵션 0) — `/matrix` 와 같은 규칙.
            #
            # 🔴 [2026-08-14 검수] **상품에 쓴 줄은 여기서 또 감추지 않는다.**
            #    이 줄은 「상품으로 만든 것도 보기」가 이미 가리고 있다. 여기서 `hid`
            #    까지 켜면 체크를 **둘 다** 켜야만 나오는 줄이 생기고, 그런 줄은 어느
            #    뱃지에도 안 잡힌다 — 실제로 「뱃지는 1인데 켜도 목록이 안 늘어나는」
            #    거짓말이 재현됐다. 감췄으면 몇 개를 감췄는지 말해야 한다는 이 화면의
            #    규칙(index.html)을 지키려면, **감추는 이유는 줄마다 하나**여야 한다.
            'hid': (not 쓴줄) and bool((c or '').startswith(_LEGACY_PREFIX) or n == 0),
        })

    # 🔴 숫자는 전부 **「그 체크를 켜면 실제로 늘어나는 줄 수」**다. 세어 놓고 안
    #    보여주면 눌러도 0줄인 거짓말이 된다(`/matrix` 가 겪은 그것).
    #      · shown  = 지금 보이는 줄
    #      · hidden = 「창고에만 있는 물건 보기」를 켜면 늘어나는 줄
    #      · made   = 「상품으로 만든 것도 보기」를 켜면 늘어나는 줄
    #    🔴 `hidden` 은 `made` 를 켜든 끄든 같은 값이어야 한다 — 옆 체크를 건드릴
    #       때마다 창고 숫자가 늘었다 줄었다 하면 창고 물건이 변한 줄로 읽는다.
    #       위에서 쓴 줄을 `hid` 로 안 겹치게 했으므로 저절로 그렇게 된다.
    보임 = [x for x in out if not x['hid']]
    counts = {'shown': len(보임), 'hidden': len(out) - len(보임), 'all': len(out),
              # 「상품으로 만든 것」은 **목록에서 뺀 것까지 포함한 전체 수**다
              # (전부 `hid` 가 아니므로 켜면 이 수만큼 그대로 늘어난다).
              # 아래 위상별 수(지금 보이는 줄)와는 묻는 것이 다르다.
              'made': 만든것}
    # 위상별 수 — 라벨을 여기 적지 않는다(`readiness.PHASE_LABEL` 이 유일한 원천).
    for p in PHASES:
        counts[p] = sum(1 for x in 보임 if x['phase'] == p)
    return out, counts


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
    _attach_phase(session, out)
    return out


def _attach_phase(session, mats):
    """옵션함 줄에 「상품 만들 준비 됐나」 위상을 붙인다.

    🔴 판정도 라벨도 **`lemouton/matrix/readiness.py` 한 곳**에서만 온다. 여기서
       「옵션이 있으면 준비 완료」처럼 다시 정하면, 같은 옵션함이 이 탭과 옵션함
       목록에서 서로 다른 상태로 보인다.

    🔴 **옵션함만** 묻는다. 판매 상품은 이 물음의 대상이 아니다
       (그쪽은 `_attach_stage` 의 4상태 — 정의역이 서로소다).
    """
    codes = [m['code'] for m in mats if m.get('code') and m.get('box')]
    if not codes:
        return
    위상 = _box_facts(session, codes,
                     {m['code']: int(m.get('options') or 0)
                      for m in mats if m.get('code')})['phase']
    for m in mats:
        p = 위상.get(m.get('code'))
        if p is None:
            continue                # 옵션함이 아닌 줄 — 위상을 지어내지 않는다
        # 🔴 라벨은 안 담는다 — 화면이 `readiness.PHASE_LABEL` 에서 찾아 쓴다(원천 하나).
        m['phase'] = p['phase']
        m['missing'] = p['missing']


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

    🔴 [2026-08-14] 옵션함 갈래를 예전의 두 글자(`none`/`made`)에서 **위상**
       (`readiness` 의 준비 미완료 / 준비 완료 / 상품 생성에 사용됨)으로 갈아끼웠다.
       예전 두 글자는 「상품을 만들었나」만 물어서, 아직 축도 안 짜고 소싱처도 안 붙인
       옵션함과 지금 바로 상품을 만들 수 있는 옵션함이 **같은 글자**로 보였다.
       사장님은 그 목록에서 무엇부터 손봐야 하는지 알 수 없었다.

    🔴 `bundles_tower.stage_of` 의 4상태와 **중복이 아니다 — 정의역이 서로소다.**
       · 4상태 : 판매 상품이 정책·마켓까지 어디까지 갔나  (`is_option_box=False`)
       · 위상   : 옵션함이 상품이 될 준비가 됐나           (`is_option_box=True`)
       한 줄이 둘 다인 경우는 없다. 물어보는 것도 다르다(파는 진도 ↔ 만들 준비)라
       합치면 「정책 적용」 같은 말이 옵션함에도 붙어 화면이 거짓말을 한다.
    """
    from lemouton.matrix.readiness import PHASE_DRAFT

    for m in mats:
        if m.get('kind') == 'derived':
            m['show'] = 'derived'                             # 갈라진 묶음 — 4상태 밖
        elif m.get('box') or not m.get('code'):
            # 옵션함: 상품 만들 준비가 어디까지 됐나.
            # 🔴 위상을 못 물어본 줄(코드가 없어 판정 대상이 아닌 줄)은 **미완료**로
            #    둔다 — 모르는 것에 초록불을 켜면 사장님이 눌렀다가 빈 상품을 만든다.
            m['show'] = m.get('phase') or PHASE_DRAFT
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
    # [2026-08-14 사장님 확정 3] 「상품으로 만든 것도 보기」 — 기본은 꺼짐.
    #   🔴 `made` 라는 이름을 **상품 탭이 다른 뜻으로** 쓰고 있다(상품을 막 만들고
    #      돌아올 때 그 상품번호가 실려 온다: `?tab=product&made=M2026…`).
    #      그래서 이 값을 켬·끔으로 읽는 것은 **옵션 탭에서만**이다. 상품 탭에서
    #      읽으면 상품번호가 「켬」으로 보여, 뜻이 다른 두 값이 한 이름에서 섞인다.
    show_made = tab in ('direct', 'market') and _flag(request.args.get('made'))
    s = SessionLocal()
    try:
        # 옵션 매트릭스 목록은 **옵션 탭 두 곳 모두**에 깔린다(사장님 확정 B2).
        # 어느 쪽으로 만들었든 이어서 할 자리를 한 군데서 찾게 한다.
        if tab in ('direct', 'market'):
            boxes, box_counts = _boxes(s, show_made=show_made)
        else:
            # 목록을 안 그리는 탭 — 숫자도 전부 0이다. 🔴 열쇠를 빠뜨리면 화면이
            # 「없음」 대신 오류로 죽으므로, 만드는 쪽과 **같은 열쇠**를 쓴다.
            boxes, box_counts = [], _빈_박스_숫자()
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
    from lemouton.matrix.readiness import PHASE_CLS, PHASE_ICON, PHASE_LABEL, PHASES
    from lemouton.matrix.sku_info import FIELDS as SKU_FIELDS
    from lemouton.matrix.sku_info import LABELS as SKU_LABELS
    from webapp.routes.bundles_tower import STAGES, STAGE_CLS, STAGE_LABEL_MATRIX
    _attach_shown(mats)
    mat_counts = {'all': len(mats)}
    for st in STAGES:
        mat_counts['s%d' % st] = sum(1 for m in mats if m.get('show') == str(st))
    # 옵션함 갈래는 위상 3종 + 갈라진 묶음. 🔴 여기 글자를 손으로 나열하지 않는다 —
    # `PHASES` 가 늘거나 이름이 바뀌면 판에서만 조용히 빠져 「합이 안 맞는」 화면이 된다.
    for k in tuple(PHASES) + ('derived',):
        mat_counts[k] = sum(1 for m in mats if m.get('show') == k)
    # 막대의 회색 토막 = 아직 상품이 아닌 옵션함 몫. 🔴 위상 하나만 세면 나머지 위상
    # 줄이 막대 어디에도 안 들어가 「막대와 목록의 합」이 갈린다(상품관리가 겪은 그것).
    mat_counts['box'] = sum(mat_counts[p] for p in PHASES)
    return render_template('optgen/index.html',
                           active_app='bundles', active='optgen_' + tab,
                           subtabs=SUBTABS, subtab_groups=subtab_groups(),
                           tab=tab, boxes=boxes, mats=mats,
                           made=made, markets=IMPORT_MARKETS,
                           stages=STAGES, stage_label=STAGE_LABEL_MATRIX,
                           stage_cls=STAGE_CLS, mat_counts=mat_counts,
                           box_counts=box_counts, axis_presets=presets_for_screen(),
                           # 🔴 위상 이름·색은 `readiness` 한 곳에서만 온다 —
                           #    화면이 「상품생성 준비 완료」 같은 글자를 또 적으면
                           #    한쪽만 고쳤을 때 같은 옵션함이 화면마다 다른 이름으로 불린다.
                           phases=PHASES, phase_label=PHASE_LABEL,
                           phase_cls=PHASE_CLS, phase_icon=PHASE_ICON, show_made=show_made,
                           # 🔴 「품번·바코드·GTIN」이라는 이름과 **그 순서**도 한 곳에서만
                           #    온다(`matrix/sku_info.FIELDS`·`LABELS`). 화면에 손으로
                           #    적어 두면 칸이 하나 늘거나 이름이 바뀔 때 이 화면만 뒤처져,
                           #    격자에서 고친 값이 목록에서는 다른 이름으로 세어진다.
                           sku_fields=SKU_FIELDS, sku_labels=SKU_LABELS)


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


def presets_for_screen() -> list[dict]:
    """화면에 내려줄 프리셋 — 원천은 위 `AXIS_PRESETS` **하나뿐**이다.

    여기서 딱 하나를 더 붙인다: `model_axis` = 「이 축 구성에 모델 축이 있나」.

    🔴 왜 서버가 계산해 주나. 만들기 창은 ⑤모델명 칸의 안내 문구를 갈라야 하는데
       (모델 모음전이면 「쉼표로 나열」, 아니면 「모델 하나」), 그 판정을 화면이 하려면
       **축 이름 목록을 화면에 또 적어야 한다.** 그러면 `axis_slot.is_model_axis`
       가 아는 이름('모델명'·'model' 등)이 늘어날 때 이 화면만 뒤처져,
       사장님이 보는 안내와 실제 저장 갈래가 갈린다.
    """
    from lemouton.sourcing.axis_slot import is_model_axis

    out = []
    for p in AXIS_PRESETS:
        opts = [dict(o, model_axis=any(is_model_axis(a) for a in o['axes']))
                for o in p['options']]
        # 갈래(kind) 자체의 값 — 아직 축을 안 골랐을 때 쓸 답이다.
        # 🔴 「하나라도」가 아니라 **「전부」**여야 한다. 섞여 있으면 축을 고르기 전엔
        #    모른다고 봐야 하고, 그때는 모델명이 한 칸이라는 쪽(False)이 안전하다.
        out.append(dict(p, options=opts,
                        model_axis=bool(opts) and all(o['model_axis'] for o in opts)))
    return out


@bp.post('/api/option-box')
def api_create_option_box():
    """옵션함을 만든다 — 상품 없이 옵션만 만들기 위한 그릇.

    겉: 매트릭스 옵션 하나 + `U…` 번호 / 속: 모델 1 + 매트릭스 1 (`M…` 없음).

    [2026-08-12 노션 옵션 a] 축을 **이름만** 먼저 저장한다. 값은 지금처럼 큰 창에서
    채운다 — 그 창이 서버가 준 `axis_steps` 로 축 카드를 그대로 복원하므로
    (`option_url_modal.js`), 창을 새로 만들 필요가 없다.

    [2026-08-14 사장님 확정 ④ 요청3] 만들기 창의 ⑤모델명 칸이 여기로 온다.
    🔴 **저장 갈래가 둘이고, 둘을 동시에 쓰면 안 된다.**
       · 모델 모음전(축에 모델이 있음) → 쉼표로 나눠 **「모델」 축의 값**으로.
       · 그 밖(색상 모음전)          → 모델이 하나이므로 `Model.bundle_model_name` 한 칸에.
       둘 다 넣으면 같은 사실이 두 곳에 생기고, `option_name.model_name_of` 의
       판정 순서(① 축 값 → ② 그 칸)상 뒤엣것이 조용히 가려져 언젠가 갈린다.
    """
    from lemouton.matrix.option_name import split_model_names
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.axis_slot import is_model_axis
    from lemouton.sourcing.option_service import save_step_design
    body = request.get_json(silent=True) or {}
    axes = [str(a).strip() for a in (body.get('axes') or []) if str(a).strip()]
    if axes and tuple(axes) not in _ALLOWED_AXES:
        return jsonify({'ok': False,
                        'error': f'고를 수 없는 축 구성이에요: {" · ".join(axes)}'}), 400
    적은모델명 = str(body.get('model_name') or '').strip()
    모델축있음 = any(is_model_axis(a) for a in axes)
    # 모델 축이 있을 때만 나눈다 — 색상 모음전에서 쉼표를 나누면 사장님이 적은 이름을
    # 프로그램이 말없이 토막 낸 것이 된다(적은 그대로 한 칸에 둔다).
    모델값들 = split_model_names(적은모델명) if 모델축있음 else []
    s = SessionLocal()
    try:
        mo = create_option_box(s, name=body.get('name') or '',
                               brand=(body.get('brand') or '').strip(),
                               category=(body.get('category') or None),
                               memo=(body.get('memo') or None),
                               model_name=(None if 모델축있음 else (적은모델명 or None)))
        if axes:
            # 축 이름은 그대로, 모델 축에만 값이 들어간다 —
            # 큰 창이 이 이름·값으로 축 카드를 채운 채 열린다.
            save_step_design(s, mo.model_code,
                             [{'axis_name': a,
                               'values': (모델값들 if is_model_axis(a) else [])}
                              for a in axes])
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
        # [2026-08-12 노션 옵션 b★] 옵션마다 **모델명이 비지 않게** 한다.
        #   모델 축이 있으면 그 값, 따로 적어 뒀으면 그 값, 없으면 매트릭스 이름.
        #   축 이름은 저장된 단계 설계에서 읽는다.
        #   🔴 [2026-08-13] 여기가 사장님이 모델명을 **눈으로 확인하는 화면**이다.
        #     `m.bundle_model_name` 을 안 넘기면 화면엔 매트릭스 이름이 뜨는데
        #     마켓엔 적어 둔 모델명이 나가 「보는 것 ≠ 나가는 것」이 된다.
        from lemouton.sourcing.models import BundleOptionStep
        axis_names = [a for (a,) in s.query(BundleOptionStep.axis_name)
                      .filter_by(model_code=code)
                      .order_by(BundleOptionStep.step_no).all()]
        # [2026-08-12] 재고 숫자의 출처를 **원장 합계**로 바꾼다.
        #   `Option.boxhero_stock_total` 은 캐시라, 서비스를 안 거친 경로가 갱신을
        #   빠뜨리면 화면 숫자와 실재고가 갈린다(shared/inventory_stock.py 독스트링).
        from shared.inventory_stock import get_stock_batch
        stock = get_stock_batch(s, [o.canonical_sku for o in opts]) if opts else {}
        # 🔴 [2026-08-13] 「재고 0」과 「아직 안 셌음」은 **다른 상태**다. 수량만으로는
        #   못 가르므로 재고 이력이 있는지 따로 본다 — 화면이 0 을 「—」 로 잘못 보이면
        #   사장님이 이미 센 것을 또 세게 된다.
        from lemouton.inventory.models import InventoryTx
        has_tx = {sk for (sk,) in s.query(InventoryTx.option_canonical_sku)
                  .filter(InventoryTx.option_canonical_sku.in_(
                      [o.canonical_sku for o in opts] or ['']),
                      InventoryTx.status == 'completed').distinct().all()} if opts else set()
        from lemouton.matrix.option_name import full_name, model_name_of
        rows = [{'no': o.display_no, 'name': full_name(nm, o),
                 'sku': o.canonical_sku,
                 'model_name': model_name_of(
                     nm, o, axis_names,
                     bundle_model_name=m.bundle_model_name),
                 'color': o.color_display or o.color_code,
                 'size': o.size_display or o.size_code,
                 'active': bool(o.is_active),
                 'stock_on': bool(o.use_purchase_inventory),
                 'stock': int(stock.get(o.canonical_sku) or 0),
                 'tx': o.canonical_sku in has_tx}
                for o in opts]
        info = {'code': m.model_code, 'name': nm, 'brand': m.brand,
                'options': len(rows), 'rows': rows,
                'is_box': bool(m.is_option_box), 'no': m.display_no}
    finally:
        s.close()
    return render_template('optgen/box.html',
                           active_app='bundles', active='optgen_direct', box=info)


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
