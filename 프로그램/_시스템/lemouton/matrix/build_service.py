"""매트릭스 옵션을 불러와 **새 모음전 상품(모상품)** 을 만든다.

노션 「모음전 상품 생성 — STEP 2) 옵션 불러오기 (매트릭스 옵션번호 or 개별 옵션번호)」.

🔴 **옵션을 복제한다**(참조가 아니라). 이유:
   지금 프로그램 전체가 「옵션은 모델 하나에 속한다」(Option.model_code)를 전제로 돈다 —
   가격 계산·마켓 전송·주문 매칭·재고 연결이 전부 그렇다.
   참조로 바꾸면 새 모상품의 옵션이 그 경로에 안 잡혀 **조용히 전송에서 빠진다**.
   그래서 옵션을 복제해 새 모델에 소유시키고, 소싱처 연결도 함께 복제한다.
   기존 경로는 한 줄도 바뀌지 않는다.

   대신 「어느 매트릭스에서 왔는가」를 bundle_matrix_links 에 남긴다(추적용).
"""
from __future__ import annotations

import json as _json
from datetime import date

from sqlalchemy import select

from lemouton.matrix.models import BundleMatrixLink, MatrixOption
from lemouton.matrix.service import MatrixError, member_skus


def _clean_code(s: str) -> str:
    return '_'.join((s or '').split())[:64]


def _derive_code(brand: str, name: str) -> str:
    """상품 코드 = 「브랜드_이름」 — 단, **이름이 이미 브랜드로 시작하면 겹치지 않게**.

    🔴 사장님이 상품 이름에 브랜드를 같이 적으시는 게 자연스럽다
       (「르무통 메이트 스니커즈」). 그대로 붙이면 `르무통_르무통_메이트_스니커즈`
       가 되어 코드가 지저분해진다(2026-08-06 라이브 실측).
       화면에 보이는 **이름은 손대지 않는다** — 코드만 겹침을 없앤다.
    """
    b, n = (brand or '').strip(), (name or '').strip()
    if b and n.lower().startswith(b.lower()):
        꼬리 = n[len(b):].lstrip(' _-')
        if 꼬리:                       # 이름이 브랜드뿐이면 그대로 둔다(빈 코드 방지)
            n = 꼬리
    return _clean_code(f'{b}_{n}' if b else n)


def _axis_names(session, mx) -> list[str]:
    """그 묶음의 축 이름들 — 여러 묶음을 합쳐도 되는지 가르는 잣대."""
    from lemouton.sourcing.models import BundleOptionStep
    if not mx.model_code:
        return []
    return [a for (a,) in session.execute(
        select(BundleOptionStep.axis_name)
        .where(BundleOptionStep.model_code == mx.model_code)
        .order_by(BundleOptionStep.step_no)).all()]


def create_bundle_from_matrix(session, *, matrix: MatrixOption = None, name: str,
                              brand: str, category: str = '',
                              model_code: str = '', skus: list[str] | None = None,
                              matrices: list = None, skipped_out: list = None,
                              on: date | None = None):
    """매트릭스에서 옵션을 가져와 새 모상품을 만든다.

    Args:
        matrix: 불러올 매트릭스(원본·파생 모두 가능). 하나만 쓸 때.
        matrices: [2026-08-12 노션 상품 c-2] **여러 묶음을 한 상품으로** 합칠 때.
                  단수 `matrix` 는 그대로 남겨 둔다 — 기존 호출부와 시험이 산다.
        skus: 그중 일부만 쓰려면 지정. 비우면 고른 묶음들의 옵션 전부
              (사장님 확정 — 여러 개 고를 땐 고르는 격자가 없으므로 전부 담는다).

    Returns:
        (새 Model, 만들어진 옵션 수) — **모양을 안 바꿨다.** 부르는 곳이 18군데라
        늘리면 전부 깨진다. 건너뛴 조합은 `skipped_out` 리스트에 담아 준다.

    Raises:
        MatrixError: 이름·브랜드가 없거나, 코드가 이미 있거나, 고른 옵션이
                     그 묶음들에 없거나, **축 이름이 서로 다를 때**.
    """
    from shared.display_no import PREFIX_BUNDLE_PRODUCT, issue_one
    from shared.sku_format import gen_sku
    from lemouton.sources.models import OptionSourceLink
    from lemouton.sourcing.models import BundleOptionStep, Model, Option

    name = (name or '').strip()
    brand = (brand or '').strip()
    if not name:
        raise MatrixError('상품 이름을 넣어 주세요.')
    if not brand:
        raise MatrixError('브랜드를 넣어 주세요. (한 상품에 하나만)')

    code = _clean_code(model_code) or _derive_code(brand, name)
    # 🔴 「단독_」로 시작하는 코드는 만들지 못하게 막는다.
    #   상품관리 목록·타워는 `~model_code.like('단독_%')` 로 그 앞글자를 걸러낸다.
    #   브랜드를 「단독」으로 넣으면 코드가 `단독_이름` 이 되어, **파는 상품인데도**
    #   상품관리에서 영영 안 보인다 — 조용히 사라지는 쪽이라 알아채기도 어렵다.
    if code.startswith('단독_'):
        raise MatrixError('「단독_」 로 시작하는 이름은 쓸 수 없어요 — '
                          '창고 전용 물건을 가리키는 옛 표시라, 이 이름으로 만들면 '
                          '상품 목록에서 안 보입니다. 브랜드나 상품 이름을 바꿔 주세요.')
    if session.get(Model, code) is not None:
        raise MatrixError(f'「{code}」 는 이미 있어요. 상품 이름을 조금 바꿔 주세요.')

    mats = [m for m in (list(matrices) if matrices else [matrix]) if m is not None]
    if not mats:
        raise MatrixError('불러올 묶음이 없어요.')

    # 🔴 축 이름이 서로 다른 묶음은 함께 담지 않는다 (사장님 확정 2026-08-12).
    #   옵션 행에는 색상·사이즈 두 칸뿐이라, 축만 늘려 적으면 축과 옵션이 어긋난
    #   **거짓 상품**이 된다. 막지 않으면 그 사실을 아무도 못 본다.
    if len(mats) > 1:
        축 = [(mx, _axis_names(session, mx)) for mx in mats]
        기준 = 축[0][1]
        다름 = [mx for mx, a in 축 if a != 기준]
        if 다름:
            보기 = ' / '.join('「%s」 %s' % (mx.name, ' · '.join(a) or '축 없음')
                             for mx, a in 축[:3])
            raise MatrixError('축이 다른 묶음은 함께 담을 수 없어요 — %s' % 보기)

    pool: list[str] = []
    for mx in mats:
        for s in member_skus(session, mx):
            if s not in pool:
                pool.append(s)
    picked = [s for s in dict.fromkeys(skus or pool) if s]
    if not picked:
        raise MatrixError('불러올 옵션이 없어요.')
    outside = [s for s in picked if s not in set(pool)]
    if outside:
        raise MatrixError(f'이 묶음에 없는 옵션이 섞여 있어요: {", ".join(outside[:5])}')

    src_opts = {o.canonical_sku: o for o in session.scalars(
        select(Option).where(Option.canonical_sku.in_(picked)))}

    m = Model(model_code=code, model_name_raw=name, model_name_display=name,
              brand=brand, category=(category or '').strip() or None)
    session.add(m)
    session.flush()
    m.display_no = issue_one(session, PREFIX_BUNDLE_PRODUCT, on=on)

    # 축(색상·사이즈 등)도 그대로 가져온다 — 없으면 새 모상품의 매트릭스 화면이 비어 보인다.
    #   🔴 여러 묶음이면 **축 이름으로 값을 합치고 순번을 1부터 다시 매긴다.**
    #      그냥 복제하면 두 묶음이 똑같이 step_no=1 을 들고 와 저장이 터진다
    #      (BundleOptionStep 은 (model_code, step_no) 가 유일해야 한다).
    #      「첫 묶음 것만」 쓰면 두 번째에서 온 색상이 축에 없어 **옵션은 있는데
    #      격자에서 사라진다** — 화면이 거짓말하게 된다.
    합친축: dict = {}
    for mx in mats:
        if not mx.model_code:
            continue
        for st in session.scalars(select(BundleOptionStep)
                                  .where(BundleOptionStep.model_code == mx.model_code)
                                  .order_by(BundleOptionStep.step_no)):
            vals = 합친축.setdefault(st.axis_name, [])
            try:
                for v in _json.loads(st.values_json or '[]'):
                    if v not in vals:
                        vals.append(v)
            except (ValueError, TypeError):
                pass
    for i, (축이름, 값들) in enumerate(합친축.items(), start=1):
        session.add(BundleOptionStep(model_code=code, step_no=i, axis_name=축이름,
                                     values_json=_json.dumps(값들, ensure_ascii=False)))

    existing = set(session.scalars(select(Option.canonical_sku)))
    made = 0
    # 🔴 조합이 겹치면 **첫 묶음 것만** 담는다 (사장님 확정).
    #   DB 가 막아 주지 않아 그냥 두면 한 칸이 두 옵션을 가리고 마켓에 같은 조합이
    #   두 번 올라간다. 조용히 버리지 않고 무엇을 건너뛰었는지 돌려준다.
    #
    # 🔴 [2026-08-13 감사] 열쇠는 **축 값 전부**다 — 예전엔 (색상,사이즈) 둘뿐이었다.
    #   모델모음전 3축은 모델 값이 옛 칸 어디에도 안 들어가므로
    #   (`axis_slot.storage_slots(['모델','색상','사이즈']) = [None,'color','size']`),
    #   모델만 다른 옵션이 **전부 같은 열쇠**가 되어 통째로 버려졌다.
    #   실측: 3축 묶음 2개(각 8옵션) → 새 상품 옵션 4개, 12개가 조용히 사라짐.
    #   단수 호출(matrix=)도 같은 루프를 타므로 예전보다 나빠졌었다(made 2 → 1).
    #   `option_axis_values` 는 axis_values_json 을 먼저 보고 없으면 (색상,사이즈)로
    #   떨어지므로, 옛 2축 데이터의 판정 결과는 **바뀌지 않는다**.
    from lemouton.sourcing.option_combo import option_axis_values

    본조합: set = set()
    skipped: list = []
    skipped_skus: set = set()      # 출처 개수를 셀 때 쓴다(표시문자열과 섞으면 안 된다)
    for old_sku in picked:
        src = src_opts.get(old_sku)
        if src is None:
            continue
        키 = tuple(option_axis_values(src)) or (src.color_code or '', src.size_code or '')
        if 키 in 본조합:
            skipped.append(' '.join(x for x in 키 if x) or old_sku)
            skipped_skus.add(old_sku)
            continue
        본조합.add(키)
        new_sku = gen_sku(existing)
        new = Option(canonical_sku=new_sku, model_code=code,
                     color_code=src.color_code, size_code=src.size_code)
        # 소싱처가 준 옵션 ID·마켓 옵션 ID 등 값 칸을 그대로 옮긴다.
        #   ★ 마켓 옵션 ID 는 옮기지 않는다 — 그건 마켓이 그 상품에 발급한 번호라
        #     새 상품에 붙이면 딴 상품을 가리킨다.
        for col in ('option_id_lemouton', 'option_id_musinsa', 'option_id_ssf',
                    'option_id_lotteon', 'option_id_ss_lemouton',
                    'axis_values_json'):
            if hasattr(src, col):
                setattr(new, col, getattr(src, col))
        session.add(new)
        session.flush()
        made += 1
        # 소싱처 연결 복제 — 이게 없으면 새 상품은 가격·재고를 영영 못 받는다.
        for link_sid in session.scalars(select(OptionSourceLink.source_option_id)
                                        .where(OptionSourceLink.canonical_sku == old_sku)):
            session.add(OptionSourceLink(canonical_sku=new_sku,
                                         source_option_id=link_sid))
    # 출처는 묶음마다 한 줄 — 표에 유일 제약이 없고 읽는 쪽(optgen._attach_made)도
    #   이미 N:N 이라, 이렇게만 남기면 두 묶음 모두에 「상품 만듦」이 뜬다.
    # 🔴 [2026-08-13 감사] 예전엔 `s not in skipped` 였다 — `s` 는 SKU 인데 `skipped` 는
    #   「블랙 250」 같은 **표시문자열** 목록이라 조건이 **늘 참**이었다. 그래서 버린 것을
    #   안 빼고 세어, 화면(`matrix/index.html`)이 실제보다 많이 담긴 것처럼 말했다.
    for mx in mats:
        n = sum(1 for s in picked
                if s in set(member_skus(session, mx)) and s not in skipped_skus)
        session.add(BundleMatrixLink(model_code=code, matrix_option_id=mx.id,
                                     copied_count=n))

    # [2026-07-30] 기본 정책이 지정돼 있으면 새 상품에 자동으로 붙인다
    #   (노션 「기본 셋팅 해두고 전체 적용」). 없으면 아무것도 안 한다 —
    #   아무 정책이나 붙이면 엉뚱한 규칙으로 올라간다.
    try:
        from lemouton.policy.models import BundlePolicyLink, MarketPolicy
        default = session.scalar(select(MarketPolicy).where(
            MarketPolicy.is_default == 1, MarketPolicy.deleted_at.is_(None)))
        if default is not None:
            session.add(BundlePolicyLink(model_code=code, policy_id=default.id))
    except Exception:       # noqa: BLE001 — 정책이 없어도 상품은 만들어져야 한다
        pass

    if skipped_out is not None:
        skipped_out.extend(skipped)
    session.flush()
    return m, made
