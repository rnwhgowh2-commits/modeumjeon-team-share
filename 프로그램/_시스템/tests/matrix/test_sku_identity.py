# -*- coding: utf-8 -*-
"""SKU 연결상태 호버카드 — 「이 SKU 가 누구인가」(번호·브랜드·모델명·색상·사이즈).

지키는 것:
  ① 브랜드는 옵션 자체 값 → 모델 상속 순서(`effective_option_brand`)를 그대로 따른다.
  ② 모델명은 모델 축 값이 있으면 그 값, 없으면 매트릭스 이름으로 떨어진다.
  ③ 🔴 사이즈가 매트릭스 전체에서 1개뿐이면 「FREE」 — 2개 이상이면 그대로.
  ④ 없는 묶음·옵션 0개는 빈 목록(지어내지 않는다).
"""
import pytest

from shared.db import Base


@pytest.fixture
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.sourcing.models   # noqa: F401
    import lemouton.matrix.models     # noqa: F401
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _모델(session, code, *, brand='르무통', bundle_model_name=None):
    from lemouton.sourcing.models import Model
    session.add(Model(model_code=code, model_name_raw=code,
                      model_name_display=code, brand=brand, is_option_box=True,
                      bundle_model_name=bundle_model_name))
    session.flush()


def _축(session, code, step_no, axis_name, values):
    import json
    from lemouton.sourcing.models import BundleOptionStep
    session.add(BundleOptionStep(model_code=code, step_no=step_no,
                                 axis_name=axis_name,
                                 values_json=json.dumps(values, ensure_ascii=False)))
    session.flush()


def _옵션(session, code, sku, *, color='블랙', size='250', brand=None,
        axis_values=None, sort_order=0):
    import json
    from lemouton.sourcing.models import Option
    session.add(Option(canonical_sku=sku, model_code=code,
                       color_code=color, color_display=color,
                       size_code=size, size_display=size, brand=brand,
                       sort_order=sort_order,
                       axis_values_json=(json.dumps(axis_values, ensure_ascii=False)
                                         if axis_values is not None else None)))
    session.flush()


# ══════════════════════════════════════════════════════════════════
#  ① 브랜드 상속
# ══════════════════════════════════════════════════════════════════

def test_옵션_자체_브랜드가_있으면_그걸_쓴다(session):
    from lemouton.matrix.sku_identity import rows_of
    _모델(session, 'U-ID-01', brand='르무통')
    _옵션(session, 'U-ID-01', 'SKU-01', brand='마르디 메크르디')

    rows = rows_of(session, 'U-ID-01')

    assert rows[0]['brand'] == '마르디 메크르디'


def test_옵션_브랜드가_없으면_모델_브랜드를_상속한다(session):
    from lemouton.matrix.sku_identity import rows_of
    _모델(session, 'U-ID-02', brand='르무통')
    _옵션(session, 'U-ID-02', 'SKU-02')

    rows = rows_of(session, 'U-ID-02')

    assert rows[0]['brand'] == '르무통'


# ══════════════════════════════════════════════════════════════════
#  ② 모델명
# ══════════════════════════════════════════════════════════════════

def test_모델_축_값이_있으면_그걸_모델명으로_쓴다(session):
    from lemouton.matrix.sku_identity import rows_of
    _모델(session, 'U-ID-03', brand='노이무이')
    _축(session, 'U-ID-03', 1, '모델', ['메이트', '스위트'])
    _축(session, 'U-ID-03', 2, '색상', ['블랙', '화이트'])
    _옵션(session, 'U-ID-03', 'SKU-03', axis_values=['메이트', '블랙'])

    rows = rows_of(session, 'U-ID-03')

    assert rows[0]['model_name'] == '메이트'


def test_모델_축이_없으면_매트릭스_이름으로_떨어진다(session):
    from lemouton.matrix.sku_identity import rows_of
    _모델(session, 'U-ID-04', brand='노이무이')
    _축(session, 'U-ID-04', 1, '색상', ['블랙'])
    _옵션(session, 'U-ID-04', 'SKU-04')

    rows = rows_of(session, 'U-ID-04')

    assert rows[0]['model_name'] == 'U-ID-04'   # model_name_display 폴백


# ══════════════════════════════════════════════════════════════════
#  ③ 사이즈 1개면 FREE
# ══════════════════════════════════════════════════════════════════

def test_사이즈가_매트릭스_전체에서_1개뿐이면_FREE로_나온다(session):
    from lemouton.matrix.sku_identity import rows_of
    _모델(session, 'U-ID-05')
    _옵션(session, 'U-ID-05', 'SKU-05-A', color='블랙', size='FREE')
    _옵션(session, 'U-ID-05', 'SKU-05-B', color='화이트', size='FREE')

    rows = rows_of(session, 'U-ID-05')

    assert [r['size'] for r in rows] == ['FREE', 'FREE']


def test_사이즈가_2개_이상이면_그대로_보여준다(session):
    """🔴 여기서 FREE 로 뭉개면 사이즈가 실제로 갈리는 옵션이 하나로 보인다."""
    from lemouton.matrix.sku_identity import rows_of
    _모델(session, 'U-ID-06')
    _옵션(session, 'U-ID-06', 'SKU-06-A', color='블랙', size='250')
    _옵션(session, 'U-ID-06', 'SKU-06-B', color='블랙', size='260')

    rows = rows_of(session, 'U-ID-06')

    assert {r['size'] for r in rows} == {'250', '260'}


def test_색상_사이즈_값이_없으면_None이지_빈문자열이_아니다(session):
    from lemouton.sourcing.models import Option
    from lemouton.matrix.sku_identity import rows_of
    _모델(session, 'U-ID-07')
    session.add(Option(canonical_sku='SKU-07', model_code='U-ID-07',
                       color_code='', size_code=''))
    session.flush()

    rows = rows_of(session, 'U-ID-07')

    assert rows[0]['color'] is None
    assert rows[0]['size'] is None


# ══════════════════════════════════════════════════════════════════
#  ④ 없는 것을 지어내지 않는다
# ══════════════════════════════════════════════════════════════════

def test_없는_묶음은_빈_목록이다(session):
    from lemouton.matrix.sku_identity import rows_of
    assert rows_of(session, 'U-없음') == []


def test_옵션이_0개면_빈_목록이다(session):
    from lemouton.matrix.sku_identity import rows_of
    _모델(session, 'U-ID-08')
    assert rows_of(session, 'U-ID-08') == []


def test_sku_번호와_옵션번호가_그대로_실린다(session):
    from lemouton.sourcing.models import Option
    from lemouton.matrix.sku_identity import rows_of
    _모델(session, 'U-ID-09')
    session.add(Option(canonical_sku='SKU-09', model_code='U-ID-09',
                       color_code='블랙', size_code='250', display_no='U-ID-09-01'))
    session.flush()

    rows = rows_of(session, 'U-ID-09')

    assert rows[0]['sku'] == 'SKU-09'
    assert rows[0]['no'] == 'U-ID-09-01'
