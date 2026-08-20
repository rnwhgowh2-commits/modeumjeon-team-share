# -*- coding: utf-8 -*-
"""만들기 창에서 고른 **축**과 적은 **모델명**이 다음 화면까지 그대로 이어지는가.

사장님 확정 2026-08-14 (④ 요청2·요청3).

요청2 — 「1/2/3축 → 축에 따라 색상·사이즈·모델 등 매칭.
        여기서 생성된 기준으로 다음 옵션 조합생성에 자동으로 축 및 축네임 설정됨」
  이건 **이미 되고 있었다**(2026-08-14 라이브 실측으로 확인). 그래서 새로 만들지 않고
  **그 사실을 여기서 못 박는다.** 잠가 두지 않으면 다음 사람이 「축은 큰 창에서만
  정한다」고 여기고 이 배선을 걷어낼 수 있다.
  길: 만들기 창 → `POST /optgen/api/option-box` → `option_service.save_step_design()`
      → `GET /api/bundles/<code>/source-urls` 의 `axis_steps`
      → `webapp/static/option_url_modal.js` 가 축 카드로 복원.

요청3 — 「모델 모음전의 경우 쉼표로 나열하기. 예: 메이트,스위트,버디
        → 옵션조합생성에서 반영될 것」
  🔴 **저장 갈래가 둘이고, 둘을 동시에 쓰면 안 된다.**
     · 모델 모음전 → 「모델」 축의 **값**
     · 색상 모음전 → `Model.bundle_model_name` **한 칸**
     둘 다 넣으면 같은 사실이 두 곳에 생기고, `option_name.model_name_of` 의 판정
     순서(① 축 값 → ② 그 칸)상 뒤엣것이 조용히 가려져 있다가 언젠가 갈린다.
"""
import uuid

import pytest

from lemouton.matrix.option_name import split_model_names


@pytest.fixture
def client():
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _만들기(client, **kw):
    # [2026-08-19 ui-verify 감사] 옵션함 이름이 겹치면 이제 두 번째부터 거절된다
    #   (중복이름 저장 금지) — 이 파일의 시험 여럿이 같은 이름으로 이 창구를 부르므로
    #   매번 다른 이름을 준다. 이름 값 자체를 검사하는 시험은 없다(있으면 이름을 직접 준다).
    body = {'name': f'모델축 검사함 {uuid.uuid4().hex[:8]}', 'brand': '르무통'}
    body.update(kw)
    r = client.post('/optgen/api/option-box', json=body)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()['code']


def _축단계(client, code):
    """큰 창(옵션 조합 생성)이 실제로 읽는 그 값."""
    j = client.get(f'/api/bundles/{code}/source-urls').get_json()
    return j.get('axis_steps') or []


def _묶음모델명(code):
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model
    s = SessionLocal()
    try:
        return s.query(Model).filter_by(model_code=code).one().bundle_model_name
    finally:
        s.close()


# ── 쉼표 나누기 규칙 ────────────────────────────────────────────────────────
def test_쉼표로_나누고_공백_빈값_중복을_거른다():
    """🔴 중복을 안 지우면 같은 조합이 두 번 생겨 **SKU 가 중복**된다 —
    한 옵션에 가격·재고가 두 벌 생겨 어느 쪽이 맞는지 알 수 없게 된다."""
    assert split_model_names(' 메이트, 스위트 ,, 버디 , 메이트 ') == \
        ['메이트', '스위트', '버디']
    assert split_model_names('') == []
    assert split_model_names(None) == []
    assert split_model_names(' , , ') == []
    # 순서는 사장님이 적은 그대로 — 정렬하지 않는다(옵션 차례가 바뀐다).
    assert split_model_names('버디,메이트') == ['버디', '메이트']


# ── 요청2 · 고른 축이 그대로 이어진다 ────────────────────────────────────────
@pytest.mark.parametrize('axes', [
    ['색상'], ['색상', '사이즈'],
    ['모델'], ['모델', '색상'], ['모델', '색상', '사이즈'],
])
def test_고른_축이_그_이름_그_차례로_저장된다(client, axes):
    """🔴 차례까지 본다. 이름만 맞고 차례가 틀리면 「모델 × 색상」이 어느 날
    「색상 × 모델」로 열려, 색상 칸에 모델명이 들어간다(옛 사고 그대로)."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import BundleOptionStep
    code = _만들기(client, axes=axes)
    s = SessionLocal()
    try:
        rows = (s.query(BundleOptionStep)
                .filter_by(model_code=code)
                .order_by(BundleOptionStep.step_no).all())
        assert [r.axis_name for r in rows] == axes
        assert [r.step_no for r in rows] == list(range(1, len(axes) + 1))
    finally:
        s.close()


@pytest.mark.parametrize('axes', [
    ['색상'], ['색상', '사이즈'],
    ['모델'], ['모델', '색상'], ['모델', '색상', '사이즈'],
])
def test_조합_생성_창이_그_축을_그대로_받아_간다(client, axes):
    """큰 창이 읽는 창구(`axis_steps`)까지 이어져야 「자동으로 축 설정됨」이 참이 된다."""
    code = _만들기(client, axes=axes)
    steps = _축단계(client, code)
    assert [st['axis_name'] for st in steps] == axes
    assert [st['step_no'] for st in steps] == list(range(1, len(axes) + 1))


def test_조합_생성_창은_이_값으로_축_카드를_복원한다():
    """🔴 서버가 잘 줘도 창이 안 읽으면 사장님 화면엔 아무것도 안 뜬다.
    창 쪽 배선(`option_url_modal.js`)이 `axis_steps` 를 축 카드로 옮기는지 본다."""
    import io
    import os
    경로 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       '..', '..', 'webapp', 'static', 'option_url_modal.js')
    js = io.open(경로, encoding='utf-8').read()
    assert 'const axisSteps = j.axis_steps || [];' in js, (
        '창이 서버가 준 축을 안 읽는다 — 만들기 창에서 고른 축이 사라진다')
    본문 = js[js.find('if (axisSteps.length > 0) {'):]
    본문 = 본문[:본문.find('} else if')]
    assert 'name: st.axis_name' in 본문 and 'values: (st.values || []).join' in 본문, (
        f'축 이름·값을 카드로 옮기지 않는다: {본문!r}')


# ── 요청3 · 모델 모음전이면 축 값으로 ────────────────────────────────────────
def test_모델_모음전이면_모델_축의_값이_된다(client):
    code = _만들기(client, axes=['모델', '색상', '사이즈'],
                 model_name='메이트, 스위트, 버디')
    steps = {st['axis_name']: st['values'] for st in _축단계(client, code)}
    assert steps['모델'] == ['메이트', '스위트', '버디']
    # 나머지 축은 큰 창에서 채운다 — 여기서 지어내지 않는다.
    assert steps['색상'] == [] and steps['사이즈'] == []


def test_모델_모음전이면_중복_빈칸_공백이_걸러진다(client):
    code = _만들기(client, axes=['모델'],
                 model_name='  메이트 , 스위트 ,, 메이트 ,  ')
    steps = _축단계(client, code)
    assert [st['values'] for st in steps] == [['메이트', '스위트']]


def test_모델_모음전이면_묶음_모델명_칸은_비운다(client):
    """🔴 **두 곳 동시 저장 금지.** 같은 사실이 두 곳에 있으면 언젠가 갈리고,
    `model_name_of` 의 판정 순서상 이 칸이 조용히 가려져 아무도 못 본다."""
    code = _만들기(client, axes=['모델', '색상'], model_name='메이트,스위트')
    assert _묶음모델명(code) is None


def test_색상_모음전이면_묶음_모델명_한_칸에_들어간다(client):
    code = _만들기(client, axes=['색상', '사이즈'], model_name='  메이트  ')
    assert _묶음모델명(code) == '메이트'
    # 축 값은 비어 있다 — 모델 축이 없으니 담을 자리도 없다.
    assert [st['values'] for st in _축단계(client, code)] == [[], []]


def test_색상_모음전에서는_쉼표를_나누지_않는다(client):
    """🔴 모델이 하나인 갈래다 — 여기서 토막 내면 사장님이 적은 이름을
    프로그램이 말없이 바꾼 것이 된다. 적은 그대로 한 칸에 둔다."""
    code = _만들기(client, axes=['색상'], model_name='메이트,스위트')
    assert _묶음모델명(code) == '메이트,스위트'


def test_모델명을_안_적으면_오늘_그대로다(client):
    """「안 적음」은 **None** 이다 — 빈 이름(`''`)과 다르다.
    None 이어야 `model_name_of` 가 예전처럼 매트릭스 이름으로 떨어진다(회귀 0)."""
    for axes in (['색상', '사이즈'], ['모델', '색상']):
        code = _만들기(client, axes=axes)
        assert _묶음모델명(code) is None
        assert [st['values'] for st in _축단계(client, code)] == [[] for _ in axes]


def test_목록_오른쪽_판이_적어_둔_모델명을_보여준다(client):
    """🔴 **보는 것 = 나가는 것.** 색상 모음전의 모델명은 축이 아니라 묶음 칸에
    들어가므로, 판이 축만 보면 「따로 안 짬」이라 말하는데 마켓엔 「메이트」가
    나간다 — 화면이 거짓말하는 자리다."""
    from lemouton.matrix.option_name import bundle_model_names
    # 순서는 `model_name_of` 와 같다 — 축 값이 있으면 그게 이긴다.
    assert bundle_model_names(['메이트', '스위트'], '버디') == ['메이트', '스위트']
    assert bundle_model_names([], '  메이트  ') == ['메이트']
    # 🔴 없으면 **빈 목록**이다. 매트릭스 이름으로 채우면 「따로 정한 것」과
    #    「안 정해서 이름을 쓰는 것」이 화면에서 같아 보인다.
    assert bundle_model_names([], None) == []

    code = _만들기(client, name='판_모델명_검사', axes=['색상', '사이즈'],
                 model_name='메이트')
    r = client.get('/optgen?tab=direct')
    html = r.get_data(as_text=True)
    # 🔴 곳간(`og-sd`)을 콕 집는다 — 그냥 `data-code=` 로 찾으면 표의 체크칸이
    #    먼저 걸려, **딴 줄의 판**을 보고 통과할 수 있다.
    시작 = html.find('<div class="og-sd" data-code="%s">' % code)
    assert 시작 >= 0, '오른쪽 판 곳간에 이 줄이 없다'
    판 = html[시작:html.find('</dl>', 시작)]
    assert '메이트' in 판, f'오른쪽 판에 적어 둔 모델명이 안 뜬다: {판!r}'
    assert '따로 안 짬' not in 판, (
        f'적어 뒀는데 「따로 안 짬」이라고 말한다 — 화면이 거짓말한다: {판!r}')


def test_적은_모델명이_옵션_모델명으로_나온다(client):
    """끝까지 이어지는지 — 조합을 실제로 만들어 보고 옵션함 화면이 읽는 값을 본다."""
    from lemouton.matrix.option_name import model_name_of
    from lemouton.sourcing.models import BundleOptionStep, Option
    from shared.db import SessionLocal
    code = _만들기(client, axes=['모델', '색상'], model_name='메이트,스위트')
    r = client.post(f'/api/bundles/{code}/options/combo', json={
        'steps': [{'axis_name': '모델', 'values': ['메이트', '스위트']},
                  {'axis_name': '색상', 'values': ['블랙']}],
        'selected': [['메이트', '블랙'], ['스위트', '블랙']],
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    s = SessionLocal()
    try:
        축이름 = [a for (a,) in s.query(BundleOptionStep.axis_name)
                 .filter_by(model_code=code)
                 .order_by(BundleOptionStep.step_no).all()]
        opts = s.query(Option).filter_by(model_code=code).all()
        assert sorted(model_name_of('모델축 검사함', o, 축이름,
                                    bundle_model_name=None) for o in opts) == \
            ['메이트', '스위트'], '옵션마다 모델명이 갈라지지 않았다'
    finally:
        s.close()
