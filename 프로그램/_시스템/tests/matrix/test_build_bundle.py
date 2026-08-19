# -*- coding: utf-8 -*-
"""매트릭스에서 새 모음전 상품 만들기.

지켜야 할 것:
  · 옵션을 **복제**해 새 모델이 소유한다 — 참조로 두면 가격·전송 경로에서 조용히 빠진다
  · **소싱처 연결도 함께 복제** — 없으면 새 상품이 가격·재고를 영영 못 받는다
  · 마켓이 발급한 옵션 ID 는 **가져오지 않는다** — 딴 상품을 가리키게 된다
  · 원본 묶음은 그대로 남는다
"""
import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.matrix import models as MM     # noqa: F401
from lemouton.policy import models as PM      # noqa: F401 — 기본 정책 테스트용
# 🔴 [2026-08-12] 이 줄이 없어 **이 파일만 따로 돌리면** 깨졌다.
#   `Base.metadata.create_all` 은 **그때까지 import 된 모델만** 만든다.
#   상품 번호(M…)를 뽑는 `issue_one` 이 `display_no_seq` 표를 쓰는데, 그 표를 정의한
#   모듈을 아무도 안 불러와 표가 안 생겼다. 전체 실행에선 다른 시험이 먼저 불러와
#   우연히 통과해서 **오래 안 보였다** — 우연히 통과하는 시험은 시험이 아니다.
from shared import display_no as _DN          # noqa: F401
from lemouton.matrix.build_service import create_bundle_from_matrix
from lemouton.matrix.models import BundleMatrixLink
from lemouton.matrix.service import MatrixError, create_derived, ensure_origin, member_skus
from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
from lemouton.sourcing.models import BundleOptionStep, Model, Option

ON = date(2026, 7, 30)


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _seed(s, n=4):
    m = Model(model_code='르무통_메이트', model_name_raw='메이트',
              model_name_display='메이트', brand='르무통', category='스니커즈')
    s.add(m); s.flush()
    s.add(BundleOptionStep(model_code=m.model_code, step_no=1,
                           axis_name='색상', values_json='["블랙","그레이"]'))
    p = SourceProduct(site='musinsa', url='https://x/1'); s.add(p); s.flush()
    for i in range(n):
        sku = f'SKU-OLD{i:05d}'
        s.add(Option(canonical_sku=sku, model_code=m.model_code,
                     color_code='블랙' if i < 2 else '그레이', size_code=str(220 + i * 5),
                     option_id_musinsa=f'MU-{i}', coupang_option_id=f'CP-{i}'))
        so = SourceOption(source_product_id=p.id, color_text='블랙' if i < 2 else '그레이',
                          size_text=str(220 + i * 5), current_price=95000 + i)
        s.add(so); s.flush()
        s.add(OptionSourceLink(canonical_sku=sku, source_option_id=so.id))
    s.flush()
    return m, ensure_origin(s, m)


def test_고른_옵션이_새_상품에_복제된다(db):
    m, org = _seed(db, 4)
    picked = member_skus(db, org)[:2]
    new, made = create_bundle_from_matrix(
        db, matrix=org, name='메이트 블랙', brand='르무통', category='스니커즈',
        skus=picked, on=ON)
    assert made == 2
    news = db.query(Option).filter_by(model_code=new.model_code).all()
    assert len(news) == 2
    assert {o.canonical_sku for o in news}.isdisjoint(set(picked)), '새 옵션번호를 받아야 한다'
    assert len(db.query(Option).filter_by(model_code=m.model_code).all()) == 4, '원본은 그대로'


def test_소싱처_연결도_따라온다(db):
    """이게 없으면 새 상품은 가격·재고를 영영 못 받는다."""
    m, org = _seed(db, 3)
    new, _ = create_bundle_from_matrix(db, matrix=org, name='전부', brand='르무통', on=ON)
    for o in db.query(Option).filter_by(model_code=new.model_code).all():
        links = db.query(OptionSourceLink).filter_by(canonical_sku=o.canonical_sku).count()
        assert links == 1, f'{o.canonical_sku} 에 소싱처 연결이 없다'


def test_마켓이_준_옵션ID는_가져오지_않는다(db):
    """마켓 번호는 그 상품에 발급된 것 — 새 상품에 붙이면 딴 상품을 가리킨다."""
    m, org = _seed(db, 2)
    new, _ = create_bundle_from_matrix(db, matrix=org, name='새것', brand='르무통', on=ON)
    for o in db.query(Option).filter_by(model_code=new.model_code).all():
        assert o.coupang_option_id is None
        assert o.option_id_musinsa is not None, '소싱처가 준 값은 가져온다'


def test_모상품번호가_자동으로_붙는다(db):
    m, org = _seed(db, 2)
    new, _ = create_bundle_from_matrix(db, matrix=org, name='새것', brand='르무통', on=ON)
    assert new.display_no == 'M20260730-000001'


def test_축도_함께_가져온다(db):
    """축이 없으면 새 상품의 매트릭스 화면이 비어 보인다."""
    m, org = _seed(db, 2)
    new, _ = create_bundle_from_matrix(db, matrix=org, name='새것', brand='르무통', on=ON)
    steps = db.query(BundleOptionStep).filter_by(model_code=new.model_code).all()
    assert [s.axis_name for s in steps] == ['색상']


def test_어느_묶음에서_왔는지_남는다(db):
    m, org = _seed(db, 3)
    new, made = create_bundle_from_matrix(db, matrix=org, name='새것', brand='르무통', on=ON)
    link = db.query(BundleMatrixLink).filter_by(model_code=new.model_code).one()
    assert link.matrix_option_id == org.id and link.copied_count == made


def test_파생에서도_상품을_만들_수_있다(db):
    m, org = _seed(db, 4)
    d = create_derived(db, origin=org, name='블랙만', skus=member_skus(db, org)[:2], on=ON)
    new, made = create_bundle_from_matrix(db, matrix=d, name='블랙 상품', brand='르무통', on=ON)
    assert made == 2


def test_이름이나_브랜드가_비면_막는다(db):
    m, org = _seed(db, 2)
    with pytest.raises(MatrixError, match='상품 이름'):
        create_bundle_from_matrix(db, matrix=org, name='  ', brand='르무통', on=ON)
    with pytest.raises(MatrixError, match='브랜드'):
        create_bundle_from_matrix(db, matrix=org, name='이름', brand='', on=ON)


def test_같은_코드가_이미_있으면_막는다(db):
    m, org = _seed(db, 2)
    create_bundle_from_matrix(db, matrix=org, name='메이트 블랙', brand='르무통', on=ON)
    with pytest.raises(MatrixError, match='이미 있어요'):
        create_bundle_from_matrix(db, matrix=org, name='메이트 블랙', brand='르무통', on=ON)


def test_원본_모델과_같은_이름이면_바로_막는다(db):
    """이름에서 코드를 만드는데 그게 기존 상품과 겹치면 덮어쓰기 사고가 난다."""
    m, org = _seed(db, 2)
    with pytest.raises(MatrixError, match='이미 있어요'):
        create_bundle_from_matrix(db, matrix=org, name='메이트', brand='르무통', on=ON)


def test_이_묶음에_없는_옵션은_막는다(db):
    m, org = _seed(db, 2)
    with pytest.raises(MatrixError, match='없는 옵션'):
        create_bundle_from_matrix(db, matrix=org, name='x', brand='르무통',
                                  skus=['SKU-NOTMINE'], on=ON)


def test_기본_정책이_있으면_새_상품에_자동으로_붙는다(db):
    """노션 「기본 셋팅 해두고 전체 적용」."""
    from lemouton.policy.service import create_policy, policy_of, toggle_default
    m, org = _seed(db, 2)
    p = create_policy(db, name='르무통 기본')
    toggle_default(db, policy=p)
    new, _ = create_bundle_from_matrix(db, matrix=org, name='새것', brand='르무통', on=ON)
    assert policy_of(db, new.model_code).id == p.id


def test_기본_정책이_없으면_아무것도_안_붙인다(db):
    """아무 정책이나 붙이면 엉뚱한 규칙으로 마켓에 올라간다."""
    from lemouton.policy.service import create_policy, policy_of
    m, org = _seed(db, 2)
    create_policy(db, name='기본 아님')      # is_default 아님
    new, _ = create_bundle_from_matrix(db, matrix=org, name='새것', brand='르무통', on=ON)
    assert policy_of(db, new.model_code) is None
