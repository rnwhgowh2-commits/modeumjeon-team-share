# -*- coding: utf-8 -*-
"""옵션마다 붙는 번호 — `U20260801-000003-01`.

노션 — 「옵션별 개별 1축형 옵션번호/옵션명 생성」.
설계서 확정 — **매트릭스 번호 + 순번 2자리**. 번호만 봐도 어느 묶음 소속인지 보인다.

🔴 속 열쇠(`canonical_sku`)는 **그대로 둔다.** 252파일 1,715곳이 그 열쇠로 돈다.
   이 번호는 소싱처 옵션에 번호를 붙인 것과 같은 방식으로 **옆에 붙는 표시용**이다.
"""
import pytest

from lemouton.matrix.option_no import next_seq, option_display_no
from shared.db import Base


def test_매트릭스_번호에_순번을_붙인다():
    assert option_display_no('U20260801-000003', 1) == 'U20260801-000003-01'
    assert option_display_no('U20260801-000003', 12) == 'U20260801-000003-12'


def test_두_자리를_넘으면_자리를_늘린다():
    """옵션이 126개까지 간다 — 두 자리로 자르면 번호가 겹친다."""
    assert option_display_no('U20260801-000003', 126) == 'U20260801-000003-126'


def test_순번은_1부터():
    assert option_display_no('U20260801-000003', 1).endswith('-01')


def test_잘못된_순번은_거절한다():
    with pytest.raises(ValueError):
        option_display_no('U20260801-000003', 0)


def test_이미_쓴_번호_다음을_준다():
    """중간에 지운 옵션이 있어도 번호를 다시 쓰면 안 된다."""
    assert next_seq(['U20260801-000003-01', 'U20260801-000003-05']) == 6
    assert next_seq([]) == 1
    assert next_seq([None, '']) == 1


def test_다른_묶음_번호가_섞여도_안_흔들린다():
    """묶음마다 순번은 따로 돈다."""
    assert next_seq(['U20260801-000003-07']) == 8


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


def test_옵션에_번호_칸이_있다():
    from lemouton.sourcing.models import Option
    assert 'display_no' in Option.__table__.c


def test_새_옵션에_번호가_저절로_붙는다(session):
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.models import Option
    mo = create_option_box(session, name='메이트', brand='르무통')
    session.add_all([
        Option(canonical_sku='SKU-NO000001', model_code=mo.model_code,
               color_code='블랙', size_code='250'),
        Option(canonical_sku='SKU-NO000002', model_code=mo.model_code,
               color_code='블랙', size_code='255')])
    session.flush()
    nos = sorted(o.display_no for o in session.query(Option).all())
    assert nos == [f'{mo.display_no}-01', f'{mo.display_no}-02']


def test_나중에_더_넣어도_이어서_붙는다(session):
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.models import Option
    mo = create_option_box(session, name='메이트', brand='르무통')
    session.add(Option(canonical_sku='SKU-NO000001', model_code=mo.model_code,
                       color_code='블랙', size_code='250'))
    session.flush()
    session.add(Option(canonical_sku='SKU-NO000002', model_code=mo.model_code,
                       color_code='화이트', size_code='250'))
    session.flush()
    assert session.get(Option, 'SKU-NO000002').display_no == f'{mo.display_no}-02'


def test_주인이_없으면_번호도_안_붙인다(session):
    """🔴 지어내지 않는다 — 어느 묶음인지 모르면 번호를 만들 수 없다."""
    from lemouton.sourcing.models import Model, Option
    session.add(Model(model_code='매트릭스없음', model_name_raw='x', brand='르무통'))
    session.flush()
    session.add(Option(canonical_sku='SKU-NO000009', model_code='매트릭스없음',
                       color_code='블랙', size_code='250'))
    session.flush()
    assert session.get(Option, 'SKU-NO000009').display_no is None


def test_이미_있던_옵션에도_소급으로_붙는다(session):
    """🔴 라이브에서 잡은 것 — 길목 장치는 «저장되는 순간»의 옵션만 본다.
    이미 DB 에 있던 옵션은 세션에 올라오지도 않아 번호가 안 붙었다(955개 전부).
    """
    from lemouton.matrix.option_no import assign_numbers
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.models import Option
    mo = create_option_box(session, name='메이트', brand='르무통')
    for i in range(3):
        o = Option(canonical_sku=f'SKU-BF{i:06d}', model_code=mo.model_code,
                   color_code='블랙', size_code=str(250 + i))
        session.add(o)
    session.flush()
    # 번호를 일부러 지워 «옛날 데이터» 상태로 만든다
    for o in session.query(Option).all():
        o.display_no = None
    session.flush()
    assert session.query(Option).filter(Option.display_no.is_(None)).count() == 3

    n = assign_numbers(session, limit=None)
    session.flush()
    assert n == 3
    assert session.query(Option).filter(Option.display_no.is_(None)).count() == 0


def test_소급을_두_번_돌려도_새로_붙는_게_없다(session):
    from lemouton.matrix.option_no import assign_numbers
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.models import Option
    mo = create_option_box(session, name='메이트', brand='르무통')
    session.add(Option(canonical_sku='SKU-BF999999', model_code=mo.model_code,
                       color_code='블랙', size_code='250'))
    session.flush()
    assign_numbers(session, limit=None)
    session.flush()
    assert assign_numbers(session, limit=None) == 0


def test_매트릭스에_번호가_없으면_옵션도_못_받는다(session):
    """🔴 라이브에서 막힌 지점 — 이 상황 자체를 창구가 먼저 없애야 한다."""
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.matrix.option_no import assign_numbers
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.models import Option
    mo = create_option_box(session, name='번호없는묶음', brand='르무통')
    session.query(MatrixOption).filter_by(id=mo.id).update({'display_no': None})
    session.add(Option(canonical_sku='SKU-NOMX0001', model_code=mo.model_code,
                       color_code='블랙', size_code='250'))
    session.flush()
    session.query(Option).filter_by(canonical_sku='SKU-NOMX0001').update(
        {'display_no': None})
    session.flush()
    assert assign_numbers(session, limit=None) == 0          # 지어내지 않는다
    assert session.get(Option, 'SKU-NOMX0001').display_no is None

    # 매트릭스에 번호가 생기면 그제야 붙는다
    session.query(MatrixOption).filter_by(id=mo.id).update(
        {'display_no': 'U20260801-000999'})
    session.flush()
    assert assign_numbers(session, limit=None) == 1
    assert session.get(Option, 'SKU-NOMX0001').display_no == 'U20260801-000999-01'


def test_창구가_매트릭스_번호부터_챙긴다(monkeypatch):
    """창구 코드에 그 호출이 실제로 들어 있는지 — 빠지면 라이브에서 또 막힌다."""
    import io as _io
    src = _io.open('webapp/routes/admin_owner_snapshot.py', encoding='utf-8').read()
    assert 'assign_missing' in src
