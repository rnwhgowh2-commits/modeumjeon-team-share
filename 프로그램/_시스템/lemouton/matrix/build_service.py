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

from datetime import date

from sqlalchemy import select

from lemouton.matrix.models import BundleMatrixLink, MatrixOption
from lemouton.matrix.service import MatrixError, member_skus


def _clean_code(s: str) -> str:
    return '_'.join((s or '').split())[:64]


def create_bundle_from_matrix(session, *, matrix: MatrixOption, name: str,
                              brand: str, category: str = '',
                              model_code: str = '', skus: list[str] | None = None,
                              on: date | None = None):
    """매트릭스에서 옵션을 가져와 새 모상품을 만든다.

    Args:
        matrix: 불러올 매트릭스(원본·파생 모두 가능)
        skus: 그중 일부만 쓰려면 지정. 비우면 매트릭스 전부.

    Returns:
        (새 Model, 만들어진 옵션 수)

    Raises:
        MatrixError: 이름·브랜드가 없거나, 코드가 이미 있거나, 고른 옵션이
                     그 매트릭스에 없을 때.
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

    code = _clean_code(model_code) or _clean_code(f'{brand}_{name}')
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

    pool = member_skus(session, matrix)
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
    if matrix.model_code:
        for st in session.scalars(select(BundleOptionStep).where(
                BundleOptionStep.model_code == matrix.model_code)):
            session.add(BundleOptionStep(model_code=code, step_no=st.step_no,
                                         axis_name=st.axis_name,
                                         values_json=st.values_json))

    existing = set(session.scalars(select(Option.canonical_sku)))
    made = 0
    for old_sku in picked:
        src = src_opts.get(old_sku)
        if src is None:
            continue
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
    session.add(BundleMatrixLink(model_code=code, matrix_option_id=matrix.id,
                                 copied_count=made))

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

    session.flush()
    return m, made
