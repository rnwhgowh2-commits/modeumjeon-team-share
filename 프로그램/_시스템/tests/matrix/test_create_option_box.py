# -*- coding: utf-8 -*-
"""옵션함 만들기 — 「상품 없이 옵션만」의 입구.

설계서 규칙 1·3 — 옵션의 주인은 원본 매트릭스다. 상품은 나중에 만든다.
그런데 옵션은 반드시 모델 하나에 매달려야 저장되므로(model_code NOT NULL),
매트릭스를 만들 때 **속으로 짝이 되는 모델 줄**을 같이 만들되 판매용이 아님을 표시한다.

겉(사장님이 보는 것) — 매트릭스 옵션 하나가 생겼고 `U…` 번호가 붙었다.
속(저장) — 모델 1 + 매트릭스 1. 모델엔 `M…` 이 없다(안 파니까).
"""
import pytest

from shared.db import Base


@pytest.fixture
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.sourcing.models  # noqa: F401
    import lemouton.matrix.models     # noqa: F401
    import shared.display_no          # noqa: F401
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_옵션함을_만들면_매트릭스와_U번호가_생긴다(session):
    from lemouton.matrix.service import create_option_box
    mo = create_option_box(session, name='르무통 메이트')
    assert mo.kind == 'origin'
    assert mo.name == '르무통 메이트'
    assert mo.display_no.startswith('U')


def test_상품번호는_안_붙는다(session):
    """🔴 아직 파는 게 아니다 — M… 이 붙으면 규칙 3이 깨진다."""
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.models import Model
    mo = create_option_box(session, name='르무통 메이트')
    m = session.get(Model, mo.model_code)
    assert m.is_option_box is True
    assert m.display_no is None


def test_이름이_비면_거절한다(session):
    """이름 없는 묶음은 나중에 아무도 못 찾는다."""
    from lemouton.matrix.service import create_option_box
    with pytest.raises(ValueError):
        create_option_box(session, name='   ')


def test_같은_이름을_두_번_만들어도_안_겹친다(session):
    """사장님이 같은 이름을 또 쓸 수 있다 — 저장이 터지면 안 된다."""
    from lemouton.matrix.service import create_option_box
    a = create_option_box(session, name='메이트')
    b = create_option_box(session, name='메이트')
    assert a.model_code != b.model_code
    assert a.display_no != b.display_no


def test_옵션함에_옵션을_붙일_수_있다(session):
    """이게 목적 — 상품을 안 만들고도 옵션이 저장된다."""
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.models import Option
    mo = create_option_box(session, name='메이트')
    session.add(Option(canonical_sku='SKU-TEST0001', model_code=mo.model_code,
                       matrix_option_id=mo.id, color_code='블랙', size_code='250'))
    session.flush()
    got = session.get(Option, 'SKU-TEST0001')
    assert got.matrix_option_id == mo.id


def test_브랜드를_적어두면_그대로_들어간다(session):
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.models import Model
    mo = create_option_box(session, name='메이트', brand='나이키')
    assert session.get(Model, mo.model_code).brand == '나이키'
