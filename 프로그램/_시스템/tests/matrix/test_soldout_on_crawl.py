# -*- coding: utf-8 -*-
"""크롤이 끝나면 품절 알림이 저절로 간다.

지금까지는 **사람이 눌러야** 검사했다. 크롤은 몇 분마다 도는데 그때마다
사람이 누를 수는 없으므로, 모음전 하나의 크롤이 끝나는 자리에서 그 상품만 본다.

🔴 전체 스캔(173개)을 크롤마다 돌리면 안 된다 — 크롤은 자주 돈다.
   **그 상품 하나만** 본다.
🔴 알림이 실패해도 **크롤을 깨뜨리지 않는다** — 크롤이 멈추면 가격·재고가 낡는다.
"""
import pytest

from shared.db import Base


@pytest.fixture
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.sourcing.models   # noqa: F401
    import lemouton.matrix.models      # noqa: F401
    import lemouton.sources.models     # noqa: F401
    import shared.display_no           # noqa: F401
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _product(session, code='르무통_메이트', *, stocks):
    """옵션마다 (소싱처 재고 목록, 사입 재고) 를 주고 상품 하나를 만든다."""
    from lemouton.sources.models import (OptionSourceLink, SourceOption,
                                         SourceProduct)
    from lemouton.sourcing.models import Model, Option
    session.add(Model(model_code=code, model_name_raw=code, brand='르무통'))
    session.flush()
    sp = SourceProduct(site='lemouton', url='https://x/1',
                       external_product_id='X1')
    session.add(sp)
    session.flush()
    for i, (srcs, own) in enumerate(stocks):
        sku = f'SKU-CR{i:06d}'
        session.add(Option(canonical_sku=sku, model_code=code,
                           color_code='블랙', size_code=str(250 + i),
                           boxhero_stock_total=own))
        session.flush()
        for st in srcs:
            so = SourceOption(source_product_id=sp.id, current_stock=st)
            session.add(so)
            session.flush()
            session.add(OptionSourceLink(canonical_sku=sku,
                                         source_option_id=so.id))
    session.flush()
    return code


def test_다_품절이면_새로_알린다(session):
    from lemouton.matrix.soldout_alert import notify_one
    code = _product(session, stocks=[([0], 0), ([0, 0], 0)])
    out = notify_one(session, code)
    assert out['soldout'] is True
    assert out['sent'] == 1


def test_하나라도_팔_수_있으면_안_알린다(session):
    from lemouton.matrix.soldout_alert import notify_one
    code = _product(session, stocks=[([0], 0), ([3], 0)])
    out = notify_one(session, code)
    assert out['soldout'] is False
    assert out['sent'] == 0


def test_두_번_돌아도_같은_상품을_다시_안_알린다(session):
    """크롤은 몇 분마다 돈다 — 매번 알리면 알림이 폭주한다."""
    from lemouton.matrix.soldout_alert import notify_one
    code = _product(session, stocks=[([0], 0)])
    assert notify_one(session, code)['sent'] == 1
    assert notify_one(session, code)['sent'] == 0


def test_다시_들어오면_표시를_비운다(session):
    """재입고 뒤 또 품절되면 다시 알려야 한다."""
    from lemouton.matrix.soldout_alert import notify_one
    from lemouton.sources.models import SourceOption
    from lemouton.sourcing.models import Model
    code = _product(session, stocks=[([0], 0)])
    notify_one(session, code)
    assert session.get(Model, code).soldout_alerted_at is not None

    session.query(SourceOption).update({'current_stock': 5})
    session.flush()
    out = notify_one(session, code)
    assert out['soldout'] is False
    assert session.get(Model, code).soldout_alerted_at is None


def test_옵션함은_검사하지_않는다(session):
    """아직 안 파는 묶음이다 — 품절이라고 알리면 거짓말이다."""
    from lemouton.matrix.soldout_alert import notify_one
    from lemouton.sourcing.models import Model
    code = _product(session, code='옵션함_테스트', stocks=[([0], 0)])
    session.query(Model).filter_by(model_code=code).update(
        {'is_option_box': True})
    session.flush()
    assert notify_one(session, code)['sent'] == 0


def test_없는_상품이면_조용히_넘어간다(session):
    """크롤 중에 상품이 지워졌을 수 있다 — 크롤을 깨뜨리면 안 된다."""
    from lemouton.matrix.soldout_alert import notify_one
    out = notify_one(session, '없는코드')
    assert out['sent'] == 0


def test_크롤_끝에서_부른다():
    """🔴 붙이는 걸 빠뜨리면 라이브에서 영영 안 돈다 — 코드에 있는지 지킨다."""
    import io
    src = io.open('lemouton/sources/service.py', encoding='utf-8').read()
    assert 'notify_one' in src
