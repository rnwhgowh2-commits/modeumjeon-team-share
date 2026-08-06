# -*- coding: utf-8 -*-
"""「단독_」 흔적 — 화면에서 감추고, 함정은 막고, 만든 상품은 만들었다고 말한다.

배경 (2026-08-06 사장님 확정)
  「단독_」 는 재고관리에서 「모음전에도 등록」을 안 한 물건에 시스템이 붙이던
  코드 앞글자다. 뜻은 「창고에만 두고 아직 팔 상품으로 안 만든 것」인데,
  그 말이 화면에 그대로 새어 나와 뜻이 안 통했다.

  코드 앞글자는 **그대로 둔다** — 상품관리·타워 등 8곳이 그걸로 창고 물건을
  걸러낸다. 건드리면 창고 물건이 판매 목록에 다시 섞인다(전송 사고 = 돈).
  대신 ① 화면에서 감추고 ② 그 앞글자로 새 상품을 못 만들게 막는다.
"""
import uuid

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


# ── ① 화면에서 감춘다 ──────────────────────────────────────────────────────

def test_이름에서_앞글자를_뗀다():
    from webapp.routes.optgen import display_name
    assert display_name('단독_SKU-484B2862', '단독_SKU-484B2862') == 'SKU-484B2862'
    # 이름을 지은 것은 손대지 않는다
    assert display_name('르무통 메이트', '르무통_메이트') == '르무통 메이트'
    # 이름이 비면 코드로 채우되, 거기서도 앞글자는 뗀다
    assert display_name('', '단독_SKU-AAA') == 'SKU-AAA'
    # 「단독」이 중간에 있는 정상 이름은 건드리지 않는다
    assert display_name('단독포장 세트', 'X') == '단독포장 세트'


def test_옵션매트릭스_화면에_앞글자가_안_보인다(client):
    """🔴 사장님 눈에 코드 앞글자가 보이면 안 된다.

    ⚠️ 이 시험은 **「단독_」 물건을 직접 심고** 본다. 안 심으면 시험용 DB 에 그런
       물건이 없어서 **아무것도 검사하지 않고 통과**한다(실제로 그럴 뻔했다).

    링크 주소(`/optgen/box/단독_…`)에는 남아 있어도 된다 — 그건 그 물건을 가리키는
    식별자라 바꾸면 링크가 깨진다. 검사 대상은 **눈에 보이는 글자**뿐이다.
    """
    import re
    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.sourcing.models import Model, Option

    tag = uuid.uuid4().hex[:8]
    code = f'단독_SKU-{tag.upper()}'
    s = SessionLocal()
    try:
        s.add(Model(model_code=code, model_name_raw=code, model_name_display=code,
                    brand='르무통', is_option_box=True))
        s.add(Option(canonical_sku=f'SKU-{tag.upper()}', model_code=code,
                     color_code='블랙', size_code='250'))
        s.add(MatrixOption(model_code=code, display_no=f'U-{tag}', name=code,
                           kind=KIND_ORIGIN))
        s.commit()

        html = client.get('/optgen/?tab=product').get_data(as_text=True)
        assert tag.upper() in html, '심은 물건이 목록에 안 보인다 — 시험이 헛돈다'
        # 태그·주석·속성을 걷어낸 「보이는 글자」에만 없어야 한다
        visible = re.sub(r'<[^>]*>', ' ', re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', html))
        assert '단독_' not in visible, '화면 글자에 「단독_」 이 새어 나왔다'
    finally:
        s.rollback()
        s.query(MatrixOption).filter(MatrixOption.model_code == code).delete()
        s.query(Option).filter(Option.model_code == code).delete()
        s.query(Model).filter(Model.model_code == code).delete()
        s.commit()
        s.close()


# ── ② 앞글자 함정을 막는다 ────────────────────────────────────────────────

def test_단독_로_시작하는_상품은_못_만든다():
    """🔴 만들어지면 **파는 상품인데 상품관리에서 영영 안 보인다** — 조용히 사라진다."""
    import app as appmod                     # noqa: F401 — 모델 등록
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.matrix.build_service import create_bundle_from_matrix
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.matrix.service import MatrixError
    from lemouton.sourcing.models import Model, Option

    tag = uuid.uuid4().hex[:8]
    code = f'상자_{tag}'
    sku = f'SKU-BOX{tag.upper()}'
    s = SessionLocal()
    mo = None
    try:
        s.add(Model(model_code=code, model_name_raw=code, model_name_display=code,
                    brand='르무통', is_option_box=True))
        s.add(Option(canonical_sku=sku, model_code=code,
                     color_code='블랙', size_code='250'))
        mo = MatrixOption(model_code=code, display_no=f'U-{tag}', name=code,
                          kind=KIND_ORIGIN)
        s.add(mo)
        s.commit()

        with pytest.raises(MatrixError) as e:
            create_bundle_from_matrix(s, matrix=mo, name=f'테스트_{tag}',
                                      brand='단독', skus=[sku])
        assert '단독_' in str(e.value), str(e.value)
        s.rollback()
        # 정말 안 만들어졌나 — 말만 하고 만들어 두면 더 나쁘다
        assert s.query(Model).filter(
            Model.model_code.like('단독\\_%', escape='\\'),
            Model.model_code.like(f'%{tag}%')).first() is None
    finally:
        s.rollback()
        if mo is not None:
            s.query(MatrixOption).filter(MatrixOption.model_code == code).delete()
        s.query(Option).filter(Option.model_code == code).delete()
        s.query(Model).filter(Model.model_code == code).delete()
        s.commit()
        s.close()


# ── ③ 만든 것은 만들었다고 말한다 ─────────────────────────────────────────

def test_상품을_만든_묶음은_아직_안_만듦이_아니다(client):
    """🔴 만들어 놓고도 「아직 상품 생성 안 함」이라고 하면 같은 묶음으로 두 번 만든다."""
    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.matrix.models import KIND_ORIGIN, BundleMatrixLink, MatrixOption
    from lemouton.sourcing.models import Model, Option
    from webapp.routes.optgen import _matrices

    tag = uuid.uuid4().hex[:8]
    box_code, made_code = f'상자_{tag}', f'만든상품_{tag}'
    s = SessionLocal()
    mo = None
    try:
        s.add(Model(model_code=box_code, model_name_raw=box_code,
                    model_name_display=box_code, brand='르무통', is_option_box=True))
        s.add(Option(canonical_sku=f'SKU-B{tag.upper()}', model_code=box_code,
                     color_code='블랙', size_code='250'))
        mo = MatrixOption(model_code=box_code, display_no=f'U-{tag}',
                          name=box_code, kind=KIND_ORIGIN)
        s.add(mo)
        s.flush()

        got = {m['id']: m for m in _matrices(s)}
        assert got[mo.id]['made'] == [], '아직 아무것도 안 만들었는데 만들었다고 한다'

        # 이 묶음으로 상품을 만들었다고 기록한다
        s.add(Model(model_code=made_code, model_name_raw='만든 상품',
                    model_name_display='만든 상품', brand='르무통',
                    display_no='M20260806-777777'))
        s.add(BundleMatrixLink(model_code=made_code, matrix_option_id=mo.id,
                               copied_count=1))
        s.commit()

        got = {m['id']: m for m in _matrices(s)}
        made = got[mo.id]['made']
        assert made and made[0]['code'] == made_code, made
        assert made[0]['name'] == '만든 상품'
    finally:
        s.rollback()
        if mo is not None:
            s.query(BundleMatrixLink).filter(
                BundleMatrixLink.matrix_option_id == mo.id).delete()
            s.query(MatrixOption).filter(MatrixOption.model_code == box_code).delete()
        s.query(Option).filter(Option.model_code == box_code).delete()
        s.query(Model).filter(Model.model_code.in_([box_code, made_code])).delete()
        s.commit()
        s.close()
