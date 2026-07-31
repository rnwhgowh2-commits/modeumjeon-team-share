# -*- coding: utf-8 -*-
"""옵션함 — 「아직 안 파는 묶음」 구분.

설계서 규칙 3·5 — `M…` 번호는 **판매 단위로 만들어진 것에만** 붙는다.
하위탭①에서 옵션만 만들면 매트릭스(`U…`)만 생기고 `M…` 은 없어야 한다.

🔴 그런데 `_assign_models` 는 **번호 없는 모델 전부**에 `M…` 을 붙인다.
   옵션함을 만들어 두면 다음 크롤 때 판매용 번호가 자동으로 박혀 규칙 3이 깨진다.
   「번호가 없다」로는 판매용 신규와 옵션함을 못 가른다(둘 다 NULL) →
   표시를 따로 둔다.
"""
from datetime import date

import pytest

from shared.db import Base


@pytest.fixture
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.sourcing.models  # noqa: F401
    import lemouton.matrix.models     # noqa: F401
    import shared.display_no          # noqa: F401  (순번 표 display_no_seq 등록)
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _model(code, **over):
    from lemouton.sourcing.models import Model
    kw = dict(model_code=code, model_name_raw=code, brand='르무통')
    kw.update(over)
    return Model(**kw)


def test_옵션함_표시_칸이_있다():
    from lemouton.sourcing.models import Model
    assert 'is_option_box' in Model.__table__.c


def test_기본은_판매용이다():
    """기존 모음전 172개가 갑자기 「안 파는 것」이 되면 안 된다."""
    from lemouton.sourcing.models import Model
    assert Model.__table__.c.is_option_box.default.arg is False
    assert Model.__table__.c.is_option_box.nullable is False


def test_판매용_모델에는_M번호가_붙는다(session):
    from lemouton.sourcing.display_no_assign import _assign_models
    session.add(_model('르무통_메이트'))
    session.flush()
    n = _assign_models(session, date(2026, 8, 1), None)
    assert n == 1
    got = session.query(type(_model('x'))).filter_by(model_code='르무통_메이트').one()
    assert got.display_no.startswith('M20260801-')


def test_옵션함에는_M번호가_안_붙는다(session):
    """🔴 이게 이 파일의 이유 — 안 팔 것에 판매용 번호가 박히면 규칙 3이 깨진다."""
    from lemouton.sourcing.display_no_assign import _assign_models
    session.add(_model('옵션함_새로짠것', is_option_box=True))
    session.flush()
    n = _assign_models(session, date(2026, 8, 1), None)
    assert n == 0
    got = session.query(type(_model('x'))).filter_by(model_code='옵션함_새로짠것').one()
    assert got.display_no is None


def test_섞여_있어도_판매용만_붙는다(session):
    from lemouton.sourcing.display_no_assign import _assign_models
    session.add_all([_model('파는것'), _model('옵션함', is_option_box=True)])
    session.flush()
    assert _assign_models(session, date(2026, 8, 1), None) == 1


def test_옵션함은_번호_대기로_세지_않는다(session):
    """대기 건수에 남아 있으면 「아직 안 끝났다」로 영원히 보인다."""
    from lemouton.sourcing.display_no_assign import pending_counts
    session.add(_model('옵션함', is_option_box=True))
    session.flush()
    assert pending_counts(session)['models'] == 0
