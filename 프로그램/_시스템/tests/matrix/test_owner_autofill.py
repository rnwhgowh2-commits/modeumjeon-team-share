# -*- coding: utf-8 -*-
"""새로 만드는 옵션에 주인이 저절로 붙는다.

🔴 왜 필요한가 — 옵션을 만드는 곳이 **11곳**이다. 한 곳씩 고치면 다음에 새 경로가
   생길 때 또 빠지고, 빠져도 아무도 모른다(주인 없는 옵션은 조용히 남는다).
   그래서 옵션을 저장하는 **길목 한 곳**에서 자동으로 채운다.

라이브에서 실제로 겪은 것 — 옵션함을 만들고 창에서 색상·사이즈를 짜 저장했더니
옵션 6개가 전부 주인 없이 저장됐다. 창의 저장 경로가 새 칸을 몰랐기 때문.
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


def _box(session, name='메이트'):
    from lemouton.matrix.service import create_option_box
    return create_option_box(session, name=name, brand='르무통')


def test_새_옵션에_주인이_저절로_붙는다(session):
    from lemouton.sourcing.models import Option
    mo = _box(session)
    session.add(Option(canonical_sku='SKU-AUTO0001', model_code=mo.model_code,
                       color_code='블랙', size_code='250'))
    session.flush()
    assert session.get(Option, 'SKU-AUTO0001').matrix_option_id == mo.id


def test_여러_개를_한꺼번에_넣어도_다_붙는다(session):
    from lemouton.sourcing.models import Option
    mo = _box(session)
    session.add_all([
        Option(canonical_sku=f'SKU-AUTO{i:04d}', model_code=mo.model_code,
               color_code='블랙', size_code=str(250 + i)) for i in range(5)])
    session.flush()
    got = session.query(Option).filter(Option.matrix_option_id.is_(None)).count()
    assert got == 0


def test_이미_적어_넣었으면_덮어쓰지_않는다(session):
    """일부러 다른 묶음에 넣은 것을 멋대로 되돌리면 안 된다."""
    from lemouton.sourcing.models import Option
    a, b = _box(session, 'A'), _box(session, 'B')
    session.add(Option(canonical_sku='SKU-AUTO9999', model_code=a.model_code,
                       matrix_option_id=b.id, color_code='블랙', size_code='250'))
    session.flush()
    assert session.get(Option, 'SKU-AUTO9999').matrix_option_id == b.id


def test_원본_매트릭스가_없으면_비워둔다(session):
    """🔴 지어내지 않는다 — 비워두면 나중에 붙이기 창구가 잡아낸다."""
    from lemouton.sourcing.models import Model, Option
    session.add(Model(model_code='매트릭스없는모델', model_name_raw='x', brand='르무통'))
    session.flush()
    session.add(Option(canonical_sku='SKU-AUTO0777', model_code='매트릭스없는모델',
                       color_code='블랙', size_code='250'))
    session.flush()
    assert session.get(Option, 'SKU-AUTO0777').matrix_option_id is None


def test_모델을_옮기면_주인도_따라간다(session):
    """옵션을 다른 묶음으로 옮겼는데 주인이 옛 묶음이면 두 곳이 갈린다."""
    from lemouton.sourcing.models import Option
    a, b = _box(session, 'A'), _box(session, 'B')
    session.add(Option(canonical_sku='SKU-AUTO0555', model_code=a.model_code,
                       color_code='블랙', size_code='250'))
    session.flush()
    o = session.get(Option, 'SKU-AUTO0555')
    o.model_code = b.model_code
    o.matrix_option_id = None          # 옮길 땐 비워서 다시 붙게 한다
    session.flush()
    assert session.get(Option, 'SKU-AUTO0555').matrix_option_id == b.id
