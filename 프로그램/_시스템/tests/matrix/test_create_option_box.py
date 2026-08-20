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
    mo = create_option_box(session, name='르무통 메이트', brand='르무통')
    assert mo.kind == 'origin'
    assert mo.name == '르무통 메이트'
    assert mo.display_no.startswith('U')


def test_상품번호는_안_붙는다(session):
    """🔴 아직 파는 게 아니다 — M… 이 붙으면 규칙 3이 깨진다."""
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.models import Model
    mo = create_option_box(session, name='르무통 메이트', brand='르무통')
    m = session.get(Model, mo.model_code)
    assert m.is_option_box is True
    assert m.display_no is None


def test_이름이_비면_거절한다(session):
    """이름 없는 묶음은 나중에 아무도 못 찾는다."""
    from lemouton.matrix.service import create_option_box
    with pytest.raises(ValueError):
        create_option_box(session, name='   ', brand='르무통')


def test_같은_브랜드_같은_이름은_거절한다(session):
    """[2026-08-19 ui-verify 감사] 이름이 겹치면 찾을 때 어느 것인지 헷갈린다.

    🔴 예전엔(브랜드 없이 만들던 시절부터) 조용히 두 번째도 저장됐다 —
       사장님 확인: 「중복이름 저장 안되게 해야지」로 규칙을 뒤집었다.
    """
    from lemouton.matrix.service import DuplicateNameError, create_option_box
    create_option_box(session, name='메이트', brand='르무통')
    with pytest.raises(DuplicateNameError):
        create_option_box(session, name='메이트', brand='르무통')


def test_다른_브랜드면_같은_이름도_허용한다(session):
    """브랜드가 다르면 이름이 같아도 다른 물건일 수 있다 — 전역으로 막지 않는다."""
    from lemouton.matrix.service import create_option_box
    a = create_option_box(session, name='베이직 반팔', brand='르무통')
    b = create_option_box(session, name='베이직 반팔', brand='나이키')
    assert a.model_code != b.model_code


def test_중복이름_에러는_ValueError로도_잡힌다(session):
    """`DuplicateNameError` 는 `ValueError` 의 하위형 — 기존 400 처리 경로가 그대로 잡는다."""
    from lemouton.matrix.service import create_option_box
    create_option_box(session, name='메이트', brand='르무통')
    with pytest.raises(ValueError):
        create_option_box(session, name='메이트', brand='르무통')


def test_지운_옵션함_이름은_다시_쓸_수_있다(session):
    """`Model` 행은 지우면 진짜로 사라진다(소프트삭제 아님) — 되살아난 이름과 안 겹친다."""
    from lemouton.sourcing.models import Model
    from lemouton.matrix.service import create_option_box
    mo = create_option_box(session, name='메이트', brand='르무통')
    session.query(Model).filter_by(model_code=mo.model_code).delete()
    session.flush()
    again = create_option_box(session, name='메이트', brand='르무통')
    assert again.model_code != mo.model_code


def test_band을_안_주면_기존과_똑같다(session):
    """직접 생성 호출부는 안 건드린다 — band 기본값은 예전 번호와 동일해야 한다."""
    from lemouton.matrix.service import create_option_box
    mo = create_option_box(session, name='직접생성', brand='르무통')
    assert mo.display_no[-6] == '0'          # 예전 그대로 000001 꼴


def test_band을_주면_순번_앞자리로_출처가_갈린다(session):
    """내마켓 불러오기(band=1)는 직접 생성(band 없음)과 번호 앞자리로 구별된다."""
    from lemouton.matrix.service import create_option_box
    direct = create_option_box(session, name='직접생성', brand='르무통')
    market = create_option_box(session, name='내마켓생성', brand='르무통', band=1)
    assert direct.display_no[-6] == '0'
    assert market.display_no[-6] == '1'
    assert direct.model_code[:-6] == market.model_code[:-6]   # 접두+생성일은 그대로


def test_band이_달라도_같은_체계_안에서_절대_안_겹친다(session):
    """직접 여러 개 + 내마켓 여러 개를 섞어 만들어도 U번호가 하나도 안 겹친다."""
    from lemouton.matrix.service import create_option_box
    made = []
    for i in range(30):
        made.append(create_option_box(session, name=f'직접{i}', brand='르무통').display_no)
        made.append(create_option_box(session, name=f'마켓{i}', brand='르무통', band=1).display_no)
    assert len(made) == len(set(made))


def test_옵션함에_옵션을_붙일_수_있다(session):
    """이게 목적 — 상품을 안 만들고도 옵션이 저장된다."""
    from lemouton.matrix.service import create_option_box
    from lemouton.sourcing.models import Option
    mo = create_option_box(session, name='메이트', brand='르무통')
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


def test_브랜드가_비면_거절한다(session):
    """[2026-08-12 노션 옵션 b★ 「브랜드/모델명 입력되어야함」]

    🔴 예전엔 비우면 조용히 「르무통」이 박혔다. 다른 브랜드 물건이 르무통으로
       잡히면 브랜드별 정책·크롤 계수·정산 분류가 통째로 어긋난다.
       「누락 없이」의 뜻은 「거짓으로 채우지 않기」다.
    """
    from lemouton.matrix.service import create_option_box
    for bad in (None, '', '   '):
        with pytest.raises(ValueError):
            create_option_box(session, name='메이트', brand=bad)
