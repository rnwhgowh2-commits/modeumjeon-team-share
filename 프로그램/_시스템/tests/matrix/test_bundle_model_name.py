# -*- coding: utf-8 -*-
"""묶음에 따로 적어 두는 **모델명** — `Model.bundle_model_name`.

왜 만들었나 (2026-08-13 사장님 확인)
  「매트릭스명은 사용자가 지정하기 나름임. 다만, 대부분
   **브랜드 + 모델명 + (사용자 추가)** 이렇게 구성 많이함.」
  그래서 이름이 「르무통 메이트 24FW」인 묶음은 모델명도 통째로 그렇게 저장돼
  **마켓 전송 payload 의 `model` 로 그대로 나가고 있었다.** 화면 편의가 아니라
  데이터 오류를 고치는 칸이다.

이 파일이 지키는 것 넷:
  ① 안 적었으면(NULL) **오늘과 완전히 같은 결과** — 기존 172개 묶음 회귀 0
  ② 색상모음전에 적어 두면 그 값이 모델명 (매트릭스 이름을 이긴다)
  ③ 🔴 모델모음전이면 **축 값이 이긴다** — 옵션마다 다른 모델명이 하나로 안 뭉개진다
  ④ 축 값 개수가 축 이름 개수와 다르면 자리를 못 믿는다 (기존 가드 유지)

🔴 판정 함수만 보면 안 된다. 값이 **마켓 전송까지 흐르는지**(다리)를 같이 본다 —
   계산기를 고쳐도 인자를 안 넘기면 라이브는 한 글자도 안 바뀐다.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.matrix.option_name import model_name_of


@pytest.fixture()
def s():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng)()
    yield sess
    sess.close()


class _O:
    """옵션 흉내 — 판정 함수는 축 값만 읽는다."""

    def __init__(self, color=None, size=None, axis_values_json=None):
        self.color_code = color
        self.size_code = size
        self.axis_values_json = axis_values_json


def _axes(*vals):
    return _O(axis_values_json=json.dumps(list(vals), ensure_ascii=False))


# ── ① 안 적었으면 오늘 그대로 (회귀 0) ────────────────────────────────────

def test_안_적었으면_매트릭스_이름_그대로():
    """NULL = 「따로 안 정함」. 기존 172개 묶음이 오늘과 똑같이 돌아야 한다."""
    o = _O('블랙', '265')
    오늘 = model_name_of('르무통 메이트 24FW', o, ['색상', '사이즈'])
    assert 오늘 == '르무통 메이트 24FW'
    # 키워드를 아예 안 넘겨도 · None 을 넘겨도 · 빈 문자열이어도 결과가 같다.
    for 안적음 in (None, '', '   '):
        assert model_name_of('르무통 메이트 24FW', o, ['색상', '사이즈'],
                             bundle_model_name=안적음) == 오늘


def test_안_적었으면_모델모음전도_오늘_그대로():
    o = _axes('메이트', '블랙', '265')
    assert model_name_of('르무통 신발', o, ['모델', '색상', '사이즈']) == '메이트'
    assert model_name_of('르무통 신발', o, ['모델', '색상', '사이즈'],
                         bundle_model_name=None) == '메이트'


# ── ② 색상모음전 — 적어 두면 그 값이 이긴다 ───────────────────────────────

def test_색상모음전은_적어_둔_모델명이_매트릭스_이름을_이긴다():
    """이름이 「르무통 메이트 24FW」여도 모델명은 「메이트」로 나가야 한다."""
    o = _O('블랙', '265')
    got = model_name_of('르무통 메이트 24FW', o, ['색상', '사이즈'],
                        bundle_model_name='메이트')
    assert got == '메이트'


def test_적어_둔_모델명의_앞뒤_공백은_정리한다():
    o = _O('블랙', '265')
    assert model_name_of('르무통 메이트 24FW', o, ['색상', '사이즈'],
                         bundle_model_name='  메이트  ') == '메이트'


def test_축이_아예_없어도_적어_둔_모델명을_쓴다():
    """옵션함처럼 축 설계가 아직 없는 묶음도 모델명이 비지 않는다."""
    assert model_name_of('르무통 메이트 24FW', _O(), None,
                         bundle_model_name='메이트') == '메이트'


# ── ③ 🔴 모델모음전 — 축 값이 이긴다 ──────────────────────────────────────

def test_모델모음전은_적어_둔_값이_있어도_축_값이_이긴다():
    """🔴 뒤집히면 옵션 3개의 모델명이 「메이트」 하나로 뭉개져 마켓에 나간다.

    구매자가 보는 드롭다운이 「메이트/스위트/데일리」에서
    「메이트/메이트/메이트」가 되는 사고다.
    """
    names = ['모델', '색상', '사이즈']
    got = [model_name_of('르무통 신발', _axes(mdl, '블랙', '265'), names,
                         bundle_model_name='메이트')
           for mdl in ('메이트', '스위트', '데일리')]
    assert got == ['메이트', '스위트', '데일리']
    assert len(set(got)) == 3, '옵션마다 달라야 한다 — 하나로 뭉개지면 안 된다'


def test_모델_축_값이_비면_적어_둔_모델명으로_떨어진다():
    """축은 있는데 그 옵션의 값이 비었을 때 — 지어내지 않고 다음 순위로."""
    o = _axes('', '블랙', '265')
    assert model_name_of('르무통 신발', o, ['모델', '색상', '사이즈'],
                         bundle_model_name='메이트') == '메이트'
    # 적어 둔 것도 없으면 매트릭스 이름 (오늘 그대로)
    assert model_name_of('르무통 신발', o, ['모델', '색상', '사이즈']) == '르무통 신발'


# ── ④ 기존 가드 — 값 개수가 다르면 자리를 못 믿는다 ───────────────────────

def test_축_값_개수가_다르면_축_값을_안_믿는다():
    """🔴 옛 옵션은 `axis_values_json` 이 없어 (색상,사이즈) 2개로 떨어진다.

    축 이름이 ['모델','색상','사이즈'] 3개인데 그대로 0번째를 집으면
    **색상 값(블랙)이 모델명으로 찍힌다** — 실제로 재현됐던 사고다.
    개수가 다르면 축을 버리고 ②·③으로 내려간다.
    """
    옛옵션 = _O('블랙', '265')          # axis_values_json 없음 → 값 2개
    names = ['모델', '색상', '사이즈']   # 축 이름 3개
    assert model_name_of('르무통 신발', 옛옵션, names,
                         bundle_model_name='메이트') == '메이트'
    assert model_name_of('르무통 신발', 옛옵션, names) == '르무통 신발'
    # 어느 쪽이든 '블랙' 이 모델명으로 새어 나오면 안 된다.
    assert model_name_of('르무통 신발', 옛옵션, names,
                         bundle_model_name='메이트') != '블랙'


# ── 다리 — 값이 마켓 전송까지 흐르는가 ────────────────────────────────────

def _model(s, code='M1', name='르무통 메이트 24FW', bundle_model_name=None):
    from lemouton.sourcing.models import Model
    m = Model(model_code=code, model_name_raw=name, model_name_display=name,
              brand='르무통', category='신발', bundle_model_name=bundle_model_name)
    s.add(m)
    s.flush()
    return m


def _option(s, sku, color, size, code='M1', axis_values=None):
    from lemouton.sourcing.models import Option
    o = Option(canonical_sku=sku, model_code=code,
               color_code=color, color_display=color,
               size_code=size, size_display=size,
               boxhero_stock_total=5, is_active=True)
    if axis_values is not None:
        o.axis_values_json = json.dumps(list(axis_values), ensure_ascii=False)
    s.add(o)
    s.flush()
    return o


def _steps(s, *names, code='M1'):
    from lemouton.sourcing.models import BundleOptionStep
    for i, nm in enumerate(names, start=1):
        s.add(BundleOptionStep(model_code=code, step_no=i, axis_name=nm,
                               values_json='[]'))
    s.flush()


def _set(s, skus, code='M1'):
    from lemouton.sets.models import ProductSet, SetOption, SetProduct
    ps = ProductSet(model_code=code, name='단품')
    s.add(ps)
    s.flush()
    sp = SetProduct(set_id=ps.id, model_code=code, quantity=1)
    s.add(sp)
    s.flush()
    for i, sku in enumerate(skus):
        s.add(SetOption(set_product_id=sp.id, canonical_sku=sku, sort_order=i))
    s.flush()
    return ps


def test_전송_payload_에_적어_둔_모델명이_실린다(s):
    """🔴 돈이 걸린 경로 — 여기 안 흐르면 화면만 바뀌고 마켓엔 옛 이름이 나간다."""
    from lemouton.policy import to_payload as TP
    _model(s, bundle_model_name='메이트')
    _option(s, 'SKU-A', '블랙', '265')
    ps = _set(s, ('SKU-A',))
    got = json.loads(TP.set_view(s, set_id=ps.id).options_json)
    assert got[0]['model'] == '메이트', got


def test_전송_payload_는_안_적었으면_오늘_그대로_매트릭스_이름(s):
    """회귀 0 증명 — 기존 172개 묶음은 NULL 이라 이 길로 간다."""
    from lemouton.policy import to_payload as TP
    _model(s)                                   # bundle_model_name NULL
    _option(s, 'SKU-A', '블랙', '265')
    ps = _set(s, ('SKU-A',))
    got = json.loads(TP.set_view(s, set_id=ps.id).options_json)
    assert got[0]['model'] == '르무통 메이트 24FW', got


def test_전송_payload_모델모음전은_축_값이_이긴다(s):
    """🔴 옵션 3개가 서로 **다른** 모델명을 달고 나가야 한다."""
    from lemouton.policy import to_payload as TP
    _model(s, bundle_model_name='메이트')
    for sku, mdl in (('SKU-A', '메이트'), ('SKU-B', '스위트'), ('SKU-C', '데일리')):
        _option(s, sku, '블랙', '265', axis_values=[mdl, '블랙', '265'])
    _steps(s, '모델', '색상', '사이즈')
    ps = _set(s, ('SKU-A', 'SKU-B', 'SKU-C'))
    got = json.loads(TP.set_view(s, set_id=ps.id).options_json)
    assert [c['model'] for c in got] == ['메이트', '스위트', '데일리'], got


def test_판매처_대조도_같은_모델명을_쓴다(s):
    """전송과 대조가 갈리면 전부 unmatched 가 돼 가격·재고가 조용히 안 나간다."""
    from lemouton.sets.set_link_service import _gather_set_options
    _model(s, bundle_model_name='메이트')
    _option(s, 'SKU-A', '블랙', '265')
    ps = _set(s, ('SKU-A',))
    got = _gather_set_options(s, ps.id)
    assert got[0]['model'] == '메이트', got


def test_격자_화면도_같은_모델명을_쓴다(s):
    """🔴 「보는 것 = 나가는 것」 — 화면만 매트릭스 이름이면 사장님이 못 알아챈다.

    예전엔 이 자리가 매트릭스 이름을 **빈 문자열로** 넘겨, 모델명을 알면서도
    화면에는 아무것도 안 내놓았다.
    """
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from webapp.routes.matrix import _attach_model
    _model(s, bundle_model_name='메이트')
    _option(s, 'SKU-A', '블랙', '265')
    mo = MatrixOption(name='르무통 메이트 24FW', kind=KIND_ORIGIN, model_code='M1')
    s.add(mo)
    s.flush()
    rows = [{'sku': 'SKU-A'}]
    models = _attach_model(s, mo, rows)
    assert rows[0]['model'] == '메이트'
    assert models == ['메이트']


def test_격자_화면은_안_적었으면_오늘_그대로_모델명_없음(s):
    """색상모음전 + 안 적음 → 모델 탭이 안 뜬다(오늘 그대로)."""
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from webapp.routes.matrix import _attach_model
    _model(s)                                   # bundle_model_name NULL
    _option(s, 'SKU-A', '블랙', '265')
    mo = MatrixOption(name='르무통 메이트 24FW', kind=KIND_ORIGIN, model_code='M1')
    s.add(mo)
    s.flush()
    rows = [{'sku': 'SKU-A'}]
    assert _attach_model(s, mo, rows) == []
    assert rows[0]['model'] == ''


def test_격자_화면_모델모음전은_옵션마다_다른_모델명(s):
    """🔴 축 값이 이겨야 격자가 모델별로 갈린다 — 하나로 뭉개지면 칸이 겹친다."""
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from webapp.routes.matrix import _attach_model
    _model(s, bundle_model_name='메이트')
    for sku, mdl in (('SKU-A', '메이트'), ('SKU-B', '스위트'), ('SKU-C', '데일리')):
        _option(s, sku, '블랙', '265', axis_values=[mdl, '블랙', '265'])
    _steps(s, '모델', '색상', '사이즈')
    mo = MatrixOption(name='르무통 신발', kind=KIND_ORIGIN, model_code='M1')
    s.add(mo)
    s.flush()
    rows = [{'sku': 'SKU-A'}, {'sku': 'SKU-B'}, {'sku': 'SKU-C'}]
    models = _attach_model(s, mo, rows)
    assert [r['model'] for r in rows] == ['메이트', '스위트', '데일리']
    assert models == ['메이트', '스위트', '데일리']


# ── 옵션함 상세 화면 — 사장님이 모델명을 **눈으로 보는** 자리 ─────────────
#
# 🔴 여기는 판정 함수를 다시 부르는 게 아니라 **화면이 실제로 그린 글자**를 본다.
#    함수만 다시 부르면 라우트가 인자를 안 넘겨도 초록불이 뜬다(아무것도 안 보는 시험).
#    그래서 Flask 로 진짜 요청을 보내고 `<td>메이트</td>` 가 있는지 센다.

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture
def 라이브묶음():
    """공용 시험 DB 에 묶음+옵션 하나. 끝나면 지운다(파일 DB 를 여럿이 나눠 쓴다)."""
    import uuid
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option

    code = f'모델명칸_{uuid.uuid4().hex[:8]}'
    sku = f'SKU-{uuid.uuid4().hex[:8].upper()}'
    s = SessionLocal()
    try:
        s.add(Model(model_code=code, model_name_raw='겨울 신발 24FW',
                    model_name_display='겨울 신발 24FW', brand='르무통',
                    display_no='M20260813-999998'))
        s.add(Option(canonical_sku=sku, model_code=code,
                     color_code='블랙', color_display='블랙',
                     size_code='265', size_display='265', is_active=True))
        s.commit()
        yield code, sku
    finally:
        s.query(Option).filter_by(model_code=code).delete()
        s.query(Model).filter_by(model_code=code).delete()
        s.commit()
        s.close()


def _set_bundle_model_name(code, value):
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model
    s = SessionLocal()
    try:
        s.get(Model, code).bundle_model_name = value
        s.commit()
    finally:
        s.close()


def test_옵션함_화면이_적어_둔_모델명을_그린다(client, 라이브묶음):
    """🔴 [2026-08-20 병합 정리] 모델명 칸은 이제 box.html 이 아니라 옵션 조합
    창의 「재고 입력」 서랍이 `/optgen/api/box/<code>/rows` 로 그린다(box.html
    은 그 창을 열기만 하는 껍데기). `_box_info()`(두 길 공용)가 만드는 이
    API 응답으로 「사장님이 보는 것」을 확인한다 — 화면이 실제로 그 값을
    그리는지는 실브라우저로 직접 확인했다.
    """
    code, _sku = 라이브묶음
    # 안 적었을 때 — 매트릭스 이름이 뜬다(오늘 그대로). '메이트' 는 아직 없다.
    j = client.get(f'/optgen/api/box/{code}/rows').get_json()
    assert j['rows'][0]['model_name'] == '겨울 신발 24FW'

    # 적으면 — 그 값이 뜬다.
    _set_bundle_model_name(code, '메이트')
    j = client.get(f'/optgen/api/box/{code}/rows').get_json()
    assert j['rows'][0]['model_name'] == '메이트', j
