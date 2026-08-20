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


# ── [2026-08-12 사장님 확정 1안] 옵션 묶음도 화면에서 지울 수 있어야 한다 ────────

def _템플릿(path: str) -> str:
    import pathlib
    뿌리 = pathlib.Path(__file__).resolve().parents[2]
    return (뿌리 / path).read_text(encoding='utf-8')


def test_옵션_묶음_줄에도_지우기가_있다():
    """🔴 옵션함엔 지우기가 있는데 **매트릭스 묶음 줄에만 없었다**(2026-08-12 실측).
    그래서 시험용 묶음 82줄을 화면에서 지울 방법이 아예 없었다.
    """
    h = _템플릿('webapp/templates/optgen/index.html')
    import re
    # 매트릭스 줄의 메뉴(= 「옵션 고치기 →」 가 있는 그 메뉴) 안에 지우기가 있어야 한다
    메뉴 = re.search(r'(?s)<a class="og-mi" href="/optgen/box/\{\{ m\.code \}\}">'
                     r'옵션 고치기 →</a>(.*?)</div>', h)
    assert 메뉴, '매트릭스 줄 메뉴를 못 찾았다 — 시험이 헛돈다'
    assert 'og-mi-del' in 메뉴.group(1), '옵션 묶음 줄에 지우기가 없다'
    assert 'data-del="{{ m.code }}"' in 메뉴.group(1), '무엇을 지울지 안 넘긴다'


def test_조립대에도_지우기가_있고_보기전용엔_없다():
    """지우기는 **작업하는 화면**에만. 상품관리 쪽 옵션관리는 보기 전용이다."""
    h = _템플릿('webapp/templates/matrix/detail.html')
    assert 'mxd-del' in h, '조립대에 지우기 단추가 없다'
    assert '{% if assembly and mo.model_code %}' in h, \
        '보기 전용(assembly 아님)에도 지우기가 보인다 — 「관리 탭은 확인」 원칙 위반'
    assert "fetch('/optgen/api/option-box/'" in h, \
        '조립대 지우기가 서버를 안 부른다'


def test_지우기_처리는_한_벌이다():
    """목록과 조립대가 **같은 코드**를 써야 막는 조건·알림이 안 갈린다."""
    목록 = _템플릿('webapp/templates/optgen/index.html')
    조립대 = _템플릿('webapp/templates/matrix/detail.html')
    for 조각 in ("fetch('/optgen/api/option-box/'",
                 "alert(j.error || '지우지 못했습니다.')",
                 '개도 같이 사라지고 되돌릴 수 없습니다.'):
        assert 조각 in 목록, f'목록에 원본 조각이 없다: {조각}'
        assert 조각 in 조립대, f'조립대가 다른 코드를 쓴다: {조각}'
