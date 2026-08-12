# -*- coding: utf-8 -*-
"""여러 묶음을 한 상품으로 (2026-08-12 · 노션 상품 c-2 · 사장님 C1 확정).

노션 원문 — 「여러개 체크해서 상품만들기 있어야함. (ex. 단일 모음전 옵션 매트릭스만
있었다면, 색상 모음전 옵션매트릭스 만들려면 여러 옵션 선택해야함. 옵션 생성으로
신규할 수 있지만, 그럴 경우 매트릭스에 소싱처 url 신규 구성해야하고 sku도 생성됨)」

여기서 못 박는 것
  ① 축은 **이름으로 합치고 순번을 1부터 다시** 매긴다
     — 그냥 복제하면 두 묶음이 똑같이 step_no=1 을 들고 와 저장이 터진다.
     — 「첫 묶음 것만」 쓰면 두 번째 색상이 축에 없어 **옵션은 있는데 격자에서 사라진다**.
  ② 축 이름이 다른 묶음은 **막는다** (사장님 확정) — 옵션 칸이 둘뿐이라 거짓 상품이 된다
  ③ (색상,사이즈)가 겹치면 첫 것만 담고 **무엇을 건너뛰었는지 돌려준다**
  ④ 출처(BundleMatrixLink)는 **묶음마다 한 줄** — 두 묶음 모두에 「상품 만듦」이 떠야 한다
"""
import json
from datetime import date

import pytest

from shared.db import Base

ON = date(2026, 8, 12)


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.sourcing.models   # noqa: F401
    import lemouton.matrix.models     # noqa: F401
    import lemouton.sources.models    # noqa: F401
    import shared.display_no          # noqa: F401
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _matrix(db, code, name, axes, cells):
    """묶음 하나 — 축 설계 + 옵션들."""
    from lemouton.matrix.models import MatrixOption
    from lemouton.sourcing.models import BundleOptionStep, Model, Option
    db.add(Model(model_code=code, model_name_raw=name, model_name_display=name,
                 brand='르무통', is_option_box=True))
    db.flush()
    for i, (ax, vals) in enumerate(axes, start=1):
        db.add(BundleOptionStep(model_code=code, step_no=i, axis_name=ax,
                                values_json=json.dumps(vals, ensure_ascii=False)))
    for n, (c, z) in enumerate(cells, start=1):
        db.add(Option(canonical_sku='SKU-%s%02d' % (code[-4:], n), model_code=code,
                      color_code=c, size_code=z,
                      axis_values_json=json.dumps([c, z], ensure_ascii=False)))
    mo = MatrixOption(kind='origin', model_code=code, name=name, display_no=code)
    db.add(mo)
    db.flush()
    return mo


def test_두_묶음의_축을_이름으로_합치고_순번을_다시_매긴다(db):
    from lemouton.matrix.build_service import create_bundle_from_matrix
    from lemouton.sourcing.models import BundleOptionStep
    a = _matrix(db, 'UAAA1', '메이트', [('색상', ['블랙']), ('사이즈', ['250'])],
                [('블랙', '250')])
    b = _matrix(db, 'UBBB2', '데일리', [('색상', ['아이보리']), ('사이즈', ['260'])],
                [('아이보리', '260')])
    m, made = create_bundle_from_matrix(db, matrices=[a, b], name='합친상품',
                                        brand='르무통', on=ON)
    assert made == 2
    steps = (db.query(BundleOptionStep).filter_by(model_code=m.model_code)
             .order_by(BundleOptionStep.step_no).all())
    assert [s.step_no for s in steps] == [1, 2], '순번이 1부터 다시 매겨져야 한다'
    assert [s.axis_name for s in steps] == ['색상', '사이즈']
    assert json.loads(steps[0].values_json) == ['블랙', '아이보리'], '값이 합쳐져야 한다'
    assert json.loads(steps[1].values_json) == ['250', '260']


def test_축이_다른_묶음은_막는다(db):
    """옵션 칸은 색상·사이즈 둘뿐 — 축만 늘려 적으면 거짓 상품이 된다."""
    from lemouton.matrix.build_service import create_bundle_from_matrix
    from lemouton.matrix.service import MatrixError
    a = _matrix(db, 'UCCC1', '메이트', [('색상', ['블랙']), ('사이즈', ['250'])],
                [('블랙', '250')])
    b = _matrix(db, 'UDDD2', '재질형', [('색상', ['블랙']), ('재질', ['가죽'])],
                [('블랙', '가죽')])
    with pytest.raises(MatrixError) as e:
        create_bundle_from_matrix(db, matrices=[a, b], name='섞기', brand='르무통', on=ON)
    assert '축이 다른' in str(e.value)


def test_겹치는_조합은_한_번만_담고_알려준다(db):
    from lemouton.matrix.build_service import create_bundle_from_matrix
    a = _matrix(db, 'UEEE1', '메이트', [('색상', ['블랙']), ('사이즈', ['250'])],
                [('블랙', '250')])
    b = _matrix(db, 'UFFF2', '데일리', [('색상', ['블랙']), ('사이즈', ['250'])],
                [('블랙', '250')])
    skipped = []
    m, made = create_bundle_from_matrix(db, matrices=[a, b], name='겹침', brand='르무통',
                                        skipped_out=skipped, on=ON)
    assert made == 1, '같은 (색상,사이즈)가 두 줄이 되면 마켓에 같은 조합이 두 번 올라간다'
    assert skipped == ['블랙 250'], '조용히 버리지 않고 무엇을 건너뛰었는지 알려야 한다'


def test_출처는_묶음마다_한_줄(db):
    """두 묶음 모두에 「상품 만듦」이 떠야 한다 — 읽는 쪽은 이미 N:N 이다."""
    from lemouton.matrix.build_service import create_bundle_from_matrix
    from lemouton.matrix.models import BundleMatrixLink
    a = _matrix(db, 'UGGG1', '메이트', [('색상', ['블랙']), ('사이즈', ['250'])],
                [('블랙', '250')])
    b = _matrix(db, 'UHHH2', '데일리', [('색상', ['아이보리']), ('사이즈', ['260'])],
                [('아이보리', '260')])
    m, _made = create_bundle_from_matrix(db, matrices=[a, b], name='둘출처',
                                         brand='르무통', on=ON)
    links = db.query(BundleMatrixLink).filter_by(model_code=m.model_code).all()
    assert sorted(x.matrix_option_id for x in links) == sorted([a.id, b.id])


def test_하나만_줘도_예전과_똑같다(db):
    """단수 호출을 안 깨뜨린다 — 조립대 화면이 그 길로 부른다."""
    from lemouton.matrix.build_service import create_bundle_from_matrix
    from lemouton.matrix.models import BundleMatrixLink
    a = _matrix(db, 'UIII1', '메이트', [('색상', ['블랙']), ('사이즈', ['250', '260'])],
                [('블랙', '250'), ('블랙', '260')])
    m, made = create_bundle_from_matrix(db, matrix=a, name='단수', brand='르무통', on=ON)
    assert made == 2
    assert db.query(BundleMatrixLink).filter_by(model_code=m.model_code).count() == 1
