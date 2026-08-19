# -*- coding: utf-8 -*-
"""옵션함 목록(「모음전 옵션 생성 (직접)」) 백엔드 — 9칸 + 위상이 화면까지 흐르는지.

이 파일이 지키는 것 (2026-08-14 사장님 확정 3·4)

  ① 🔴 **상품 생성에 이미 쓴 옵션함은 기본 목록에 없다.**
     섞여 있으면 할 일이 남은 것과 다 끝난 것이 한 덩어리로 보인다. 더 나쁜 건
     사장님이 그 줄을 다시 눌러 **같은 옵션함으로 상품을 두 번** 만드는 것이다.
     필요할 때만 주소(`?made=1`)로 꺼내 본다.

  ② 🔴 **「미구성」이라는 딱지를 안 그린다.**
     미구성 SKU 는 축이 0개라 위상이 **언제나 「준비 미완료」**로 떨어지고 사유에
     「축 없음」이 뜬다. 딱지를 또 붙이면 같은 사실을 두 가지 말로 하게 된다.

  ③ 🔴 **「상품 생성에 사용됨」이라는 글자가 이 화면에 없다.**
     사장님 확정 — 이 목록의 상태는 「준비 완료 / 준비 미완료」 둘뿐이다.

  ④ 🔴 **줄이 몇 개든 조회 수가 같다(N+1 방지).**
     이 목록은 상한이 없어 라이브에 200줄 넘게 나온다. 줄마다 한 번씩 물으면
     화면이 느려지다 어느 날 그냥 안 열린다 — 에러가 안 나서 제일 늦게 발견된다.

  ⑤ 🔴 **머리줄 숫자는 실제로 보이는 줄 수와 같다.**
     예전에 상한값 50을 전체인 양 보여 준 사고가 있었다(그 주석이 `_boxes` 에 있다).

  ⑥ 🔴 **서랍 뱃지 숫자 = 그 체크를 켜면 실제로 늘어나는 줄 수.** [2026-08-14 검수]
     감출 이유가 두 개인 줄(창고 물건이면서 상품에도 쓴 것)을 세면, 켜도 화면 JS 가
     계속 감춰 **「1」이라 적혀 있는데 목록이 안 늘어난다.** 그리고 옆 체크를 켤 때만
     그런 줄이 창고 몫에 얹혀 **창고 숫자까지 흔들린다.**

  ⑦ 🔴 **「모른다」와 「아니다」를 안 뭉갠다.**
     소싱처 URL 이 0개면 맵핑 완료 여부는 「모른다」다. 「아니다」로 적으면
     사유가 두 줄(「URL 없음」+「맵핑 미완료」)이 되어, 실제로는 한 군데인 할 일이
     두 군데인 것처럼 보인다.

시험을 쓰면서 지킨 것
  · 대상 데이터를 **직접 심는다** — 없으면 아무것도 검사 안 하고 통과한다.
  · 「없어야 한다」는 **눈에 보이는 글자**로 본다 — 원시 HTML 은 속성·주석까지 걸린다.
  · 시험용 DB 는 파일로 공유된다 — 이름을 매번 다르게 짓고 끝나면 지운다.
"""
import json
import re
import uuid

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _글자만(html: str) -> str:
    """눈에 보이는 글자만 — 태그·스크립트·스타일을 걷어낸다.

    🔴 원시 HTML 로 「없어야 한다」를 검사하면 `title=` 속성·주석·JS 조각까지 걸려
       엉뚱한 곳에서 빨간불이 뜬다. 사장님이 보는 것은 글자다.
    """
    return re.sub(r'<[^>]*>', ' ',
                  re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', html))


# ═══════════════════════════════════════════════════════════════════════════
#  표본 심기 — 다섯 가지 옵션함
# ═══════════════════════════════════════════════════════════════════════════

def _옵션함(s, code, name, *, 옵션=(), 축=(), 주소=0, 다이음=False,
           브랜드='르무통', 번호=None):
    """옵션함 하나를 통째로 심는다 — 모델 · 매트릭스 · 옵션 · 축 · 소싱처 URL.

    · `옵션`   — 넣을 (색상, 사이즈) 목록
    · `축`     — [(축이름, [값…]), …]. 값이 빈 축도 그대로 심는다(미완료 사유 확인용)
    · `주소`   — 붙일 소싱처 URL 개수
    · `다이음` — 모든 옵션을 그 URL 에 잇는가(맵핑 완료 여부)
    """
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.sourcing.models import (BundleOptionStep, BundleSourceUrl,
                                          Model, Option, OptionSourceUrlLink)

    s.add(Model(model_code=code, model_name_raw=name, model_name_display=name,
                brand=브랜드, is_option_box=True))
    mo = MatrixOption(model_code=code, display_no=(번호 or 'U-' + code[-10:]),
                      name=name, kind=KIND_ORIGIN)
    s.add(mo)
    skus = []
    for i, (색, 사이즈) in enumerate(옵션):
        # 🔴 SKU 는 **코드 전체**로 짓는다. 뒷글자만 잘라 쓰면 코드가 달라도 SKU 가
        #    같아져 두 번째 상자부터 심다가 터진다(실제로 그렇게 터졌다).
        sku = f'SKU-{code}-{i}'
        skus.append(sku)
        s.add(Option(canonical_sku=sku, model_code=code,
                     color_code=색, size_code=사이즈))
    for n, (이름, 값들) in enumerate(축, start=1):
        s.add(BundleOptionStep(model_code=code, step_no=n, axis_name=이름,
                               values_json=json.dumps(값들, ensure_ascii=False)))
    s.flush()
    for u in range(주소):
        bsu = BundleSourceUrl(model_code=code, source_key='musinsa',
                              url=f'https://example.test/{code}/{u}')
        s.add(bsu)
        s.flush()
        if 다이음:
            for sku in skus:
                s.add(OptionSourceUrlLink(option_canonical_sku=sku,
                                          bundle_source_url_id=bsu.id))
    s.flush()
    return mo


def _지우기(s, codes):
    from lemouton.matrix.models import BundleMatrixLink, MatrixOption
    from lemouton.sourcing.models import (BundleOptionStep, BundleSourceUrl,
                                          Model, Option, OptionSourceUrlLink)
    s.rollback()
    skus = [x for (x,) in s.query(Option.canonical_sku)
            .filter(Option.model_code.in_(codes)).all()]
    url_ids = [x for (x,) in s.query(BundleSourceUrl.id)
               .filter(BundleSourceUrl.model_code.in_(codes)).all()]
    mo_ids = [x for (x,) in s.query(MatrixOption.id)
              .filter(MatrixOption.model_code.in_(codes)).all()]
    if url_ids:
        (s.query(OptionSourceUrlLink)
         .filter(OptionSourceUrlLink.bundle_source_url_id.in_(url_ids))
         .delete(synchronize_session=False))
    if mo_ids:
        (s.query(BundleMatrixLink)
         .filter(BundleMatrixLink.matrix_option_id.in_(mo_ids))
         .delete(synchronize_session=False))
    for 표, 칸 in ((BundleSourceUrl, BundleSourceUrl.model_code),
                  (BundleOptionStep, BundleOptionStep.model_code),
                  (Option, Option.model_code),
                  (MatrixOption, MatrixOption.model_code)):
        s.query(표).filter(칸.in_(codes)).delete(synchronize_session=False)
    s.query(Model).filter(Model.model_code.in_(codes)).delete(
        synchronize_session=False)
    s.commit()
    assert skus is not None      # 지운 SKU 목록은 참고용 — 실패 메시지에 쓸 수 있게


@pytest.fixture
def 다섯상자():
    """준비완료 · 준비미완료 · 상품에 쓴 것 · 창고물건 · 미구성 — 다섯 가지를 심는다.

    🔴 안 심으면 시험이 헛돈다. 「없어야 한다」만 보는 검사는 화면이 통째로 비어도
       초록불이 된다 — 이 저장소가 여러 번 겪은 함정이다. 그래서 아래 시험들은
       「있어야 할 것이 있는지」를 **항상 같이** 본다.
    """
    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.matrix.models import BundleMatrixLink
    from lemouton.sourcing.models import Model

    tag = uuid.uuid4().hex[:8].upper()
    준비완료 = f'U-RDY{tag}'
    미완료 = f'U-DRF{tag}'
    쓴것 = f'U-USE{tag}'
    창고 = f'단독_SKU-{tag}'
    미구성 = f'U-UNB{tag}'
    만든상품 = f'M-MADE{tag}'
    codes = [준비완료, 미완료, 쓴것, 창고, 미구성, 만든상품]

    s = SessionLocal()
    try:
        축둘 = [('색상', ['블랙', '화이트']), ('사이즈', ['250'])]
        옵션둘 = [('블랙', '250'), ('화이트', '250')]
        # ① 준비 완료 — 옵션·축값·소싱처 URL·맵핑이 전부 갖춰졌다
        _옵션함(s, 준비완료, f'준비끝난함{tag}', 옵션=옵션둘, 축=축둘,
               주소=1, 다이음=True)
        # ② 준비 미완료 — 소싱처 URL 을 아직 안 붙였다
        _옵션함(s, 미완료, f'덜된함{tag}', 옵션=옵션둘, 축=축둘, 주소=0)
        # ③ 상품 생성에 사용됨 — 재료는 ①과 같고 만든 상품 기록만 더 있다
        mo = _옵션함(s, 쓴것, f'다쓴함{tag}', 옵션=옵션둘, 축=축둘,
                   주소=1, 다이음=True)
        s.add(Model(model_code=만든상품, model_name_raw=f'만든상품{tag}',
                    model_name_display=f'만든상품{tag}', brand='르무통',
                    display_no=f'M2026-{tag[:6]}'))
        s.flush()
        s.add(BundleMatrixLink(model_code=만든상품, matrix_option_id=mo.id,
                               copied_count=2))
        # ④ 창고에만 있는 물건 — 「단독_」 앞글자. 화면이 기본으로 감춘다
        _옵션함(s, 창고, 창고, 옵션=[('블랙', '250')], 축=[])
        # ⑤ 미구성 SKU — 정식 옵션함 코드인데 축을 아직 하나도 안 짰다
        #    (2026-08-06 이후 재고관리 「제품 추가」가 만드는 꼴 — 「단독_」 가 아니다)
        _옵션함(s, 미구성, f'아직안짠함{tag}', 옵션=[('블랙', '250')], 축=[])
        s.commit()
        yield {'tag': tag, '준비완료': 준비완료, '미완료': 미완료, '쓴것': 쓴것,
               '창고': 창고, '미구성': 미구성, 'codes': codes,
               '이름': {'준비완료': f'준비끝난함{tag}', '미완료': f'덜된함{tag}',
                       '쓴것': f'다쓴함{tag}', '미구성': f'아직안짠함{tag}'}}
    finally:
        _지우기(s, codes)
        s.close()


@pytest.fixture
def 창고인데_상품에_쓴_것():
    """창고 물건(`단독_`)인데 **상품 생성에도 쓴** 옵션함 — 감출 이유가 두 개인 줄.

    🔴 이 표본이 없으면 검수에서 잡힌 거짓말을 재현할 수 없다. 「상품으로 만든 것도
       보기」 뱃지가 이런 줄까지 세면서 화면은 계속 감추면, **뱃지는 1인데 켜도
       목록이 안 늘어난다.** 그래서 이 시험은 늘 이 줄을 같이 심는다.
    """
    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.matrix.models import BundleMatrixLink
    from lemouton.sourcing.models import Model

    tag = uuid.uuid4().hex[:8].upper()
    창고쓴것 = f'단독_SKU-H{tag}'
    만든상품 = f'M-HID{tag}'
    s = SessionLocal()
    try:
        mo = _옵션함(s, 창고쓴것, f'창고다쓴함{tag}', 옵션=[('블랙', '250')],
                   축=[('색상', ['블랙'])])
        s.add(Model(model_code=만든상품, model_name_raw=f'창고로만든상품{tag}',
                    model_name_display=f'창고로만든상품{tag}', brand='르무통',
                    display_no=f'M2026-H{tag[:5]}'))
        s.flush()
        s.add(BundleMatrixLink(model_code=만든상품, matrix_option_id=mo.id,
                               copied_count=1))
        s.commit()
        yield {'code': 창고쓴것, '이름': f'창고다쓴함{tag}'}
    finally:
        _지우기(s, [창고쓴것, 만든상품])
        s.close()


def _boxes(codes_show_made=False):
    """`_boxes()` 를 직접 불러 (줄, 숫자) 를 받는다 — 화면 뒤의 값을 그대로 본다."""
    from shared.db import SessionLocal
    from webapp.routes.optgen import _boxes as f
    s = SessionLocal()
    try:
        return f(s, show_made=codes_show_made)
    finally:
        s.close()


def _문맥(client, url: str) -> dict:
    """그 주소를 그릴 때 화면으로 넘어간 값 한 벌 — 라우트가 **실제로 정한 것**을 본다.

    🔴 왜 렌더된 글자가 아니라 문맥인가. 상품 탭은 옵션함 목록을 아예 안 그려서,
       `show_made` 가 잘못 켜져도 화면 글자는 한 글자도 안 바뀐다. 글자만 보는
       시험은 **막으려는 것을 지워도 초록불**이라 아무것도 안 지킨다(검수 재현).
    """
    from flask import template_rendered
    받은 = []

    def _잡기(sender, template, context, **extra):
        받은.append(context)

    app = client.application
    template_rendered.connect(_잡기, app)
    try:
        client.get(url)
    finally:
        template_rendered.disconnect(_잡기, app)
    문맥 = [c for c in 받은 if 'show_made' in c]
    assert 문맥, f'{url} 을 그릴 때 문맥을 못 잡았다 — 시험이 헛돈다'
    return 문맥[0]


def _보이는줄(html: str) -> set:
    """화면에서 **실제로 보이는** 줄의 코드 — `data-hid="1"` 은 화면 JS 가 감춘다.

    🔴 「내려보낸 줄」이 아니라 「보이는 줄」을 세는 것이 요점이다. 내려보내기만 하고
       감추면 사장님 눈에는 없는 것이고, 그걸 센 숫자는 거짓말이 된다.
    """
    return set(re.findall(
        r'<tr class="og-row" data-href="/optgen/box/([^"]+)"[^>]*data-hid="0"', html))


# ═══════════════════════════════════════════════════════════════════════════
#  ① 상품 생성에 쓴 옵션함은 기본 목록에 없다 (사장님 확정 3)
# ═══════════════════════════════════════════════════════════════════════════

def test_상품에_쓴_옵션함은_기본_화면에_안_나온다(client, 다섯상자):
    """🔴 이번 지시의 핵심. 섞여 있으면 같은 옵션함으로 상품을 두 번 만들게 된다."""
    글 = _글자만(client.get('/optgen/?tab=direct').get_data(as_text=True))
    # 시험이 헛돌지 않는다는 증거를 **먼저** 본다 — 화면이 통째로 비어도
    # 「없다」는 검사는 통과하기 때문이다.
    assert 다섯상자['이름']['준비완료'] in 글, '심은 표본이 화면에 없다 — 시험이 헛돈다'
    assert 다섯상자['이름']['미완료'] in 글, '심은 표본이 화면에 없다 — 시험이 헛돈다'
    assert 다섯상자['이름']['쓴것'] not in 글, (
        '상품 생성에 이미 쓴 옵션함이 목록에 그대로 있다')


def test_주소로_켜면_쓴_것도_보인다(client, 다섯상자):
    """평소엔 감추되 **찾을 길은 남긴다** — 아예 못 보면 「어디 갔지」가 된다."""
    글 = _글자만(client.get('/optgen/?tab=direct&made=1').get_data(as_text=True))
    assert 다섯상자['이름']['쓴것'] in 글, '켜도 안 보인다 — 꺼낼 길이 없다'
    assert 다섯상자['이름']['준비완료'] in 글, '켰더니 나머지가 사라졌다'


def test_끄는_값은_켜지_않는다(client, 다섯상자):
    """🔴 `?made=0` 은 **끄려고** 적은 값이다. 「값이 있으면 켬」으로 읽으면 거꾸로 켜진다."""
    글 = _글자만(client.get('/optgen/?tab=direct&made=0').get_data(as_text=True))
    assert 다섯상자['이름']['쓴것'] not in 글, 'made=0 인데 켜졌다'


def test_상품탭의_made_는_다른_뜻이라_섞이지_않는다(client, 다섯상자):
    """🔴 `made` 라는 이름을 상품 탭이 **상품번호**로 쓰고 있다.

    상품을 막 만들고 돌아올 때 `?tab=product&made=M2026…` 로 온다. 그 값을
    켬·끔으로 읽으면 「상품번호가 있으니 켬」이 되어 뜻이 다른 두 값이 한 이름에서
    섞인다. 그래서 켬·끔으로 읽는 것은 옵션 탭에서만이다.

    🔴 **왜 `made=1` 로 묻나(검수에서 고친 자리).** 예전 이 시험은 상품번호
       (`M2026-000001`)를 넣고 **배너 글자**만 봤다. 배너는 `show_made` 와 아무
       상관 없이 따로 만들어지고, 상품번호는 `_flag` 가 어차피 「끔」으로 읽는다.
       그래서 지키려던 탭 제한을 통째로 지워도 시험은 전부 초록이었다 —
       **아무것도 안 지키는 시험**이었다. 켬 글자 그대로인 `made=1` 로 물어야
       탭 제한이 유일한 자물쇠가 되어, 지웠을 때 실제로 빨간불이 뜬다.
    """
    # ① 상품 탭 — 켬 글자가 그대로 와도 「보기」로 켜지지 않는다(여기가 자물쇠다).
    assert _문맥(client, '/optgen/?tab=product&made=1')['show_made'] is False, (
        '상품 탭에서 「상품으로 만든 것도 보기」가 켜졌다 — 뜻이 다른 두 값이 섞였다')

    # ② 실제로 오는 모양(상품번호)도 당연히 안 켜지고, 그 값은 배너로 쓰인다.
    문맥 = _문맥(client, '/optgen/?tab=product&made=M2026-000001')
    assert 문맥['show_made'] is False
    assert (문맥['made'] or {}).get('no') == 'M2026-000001', (
        '상품 만든 뒤 알림 배너 재료가 사라졌다')
    html = client.get('/optgen/?tab=product&made=M2026-000001').get_data(as_text=True)
    assert 'M2026-000001' in html, '상품 만든 뒤 알림 배너가 사라졌다'

    # ③ 반대쪽 자물쇠 — 옵션 탭에서는 정상으로 켜져야 한다. 이게 없으면 탭 제한
    #    대신 **기능을 통째로 지워도** ①②가 초록이라 시험이 다시 헛돈다.
    assert _문맥(client, '/optgen/?tab=direct&made=1')['show_made'] is True, (
        '옵션 탭에서 「상품으로 만든 것도 보기」가 안 켜진다')


def test_쓴_것의_개수는_숫자로_알려_준다(다섯상자):
    """감췄으면 **몇 개를 감췄는지**는 말해야 한다 — 안 그러면 없어진 걸로 읽는다."""
    줄, 숫자 = _boxes()
    assert 숫자['made'] >= 1, f'상품에 쓴 옵션함을 하나도 안 셌다: {숫자}'
    assert all(not b['made'] for b in 줄), '기본 목록에 쓴 것이 섞여 있다'
    켠줄, _ = _boxes(True)
    assert any(b['code'] == 다섯상자['쓴것'] for b in 켠줄), '켜도 안 나온다'


def test_만든것_뱃지가_켜면_늘어나는_줄_수와_같다(client, 다섯상자, 창고인데_상품에_쓴_것):
    """🔴 뱃지 숫자는 「켜면 목록이 몇 줄 느나」다 — 세어 놓고 안 보여주면 거짓말이다.

    검수 재현: 창고 물건(`단독_`)이면서 상품에도 쓴 줄을 뱃지가 세는데, 화면 JS 는
    그 줄을 계속 감춘다(감출 이유가 두 개라 체크 하나로는 안 나온다).
    그래서 **뱃지는 1인데 켜도 목록이 안 늘어났다.**
    """
    끔 = client.get('/optgen/?tab=direct').get_data(as_text=True)
    켬 = client.get('/optgen/?tab=direct&made=1').get_data(as_text=True)
    뱃지 = re.search(r'(?s)id="og-made".*?og-bc">(\d+)<', 켬)
    assert 뱃지, '「상품으로 만든 것도 보기」 뱃지를 못 찾음 — 화면 구조가 바뀌었나?'
    늘어난 = _보이는줄(켬) - _보이는줄(끔)
    # 헛돔 방지 — 두 표본이 실제로 늘어난 줄에 들어 있는지 **먼저** 본다.
    assert 다섯상자['쓴것'] in 늘어난, '켜도 「상품에 쓴 옵션함」이 안 나온다 — 시험이 헛돈다'
    assert 창고인데_상품에_쓴_것['code'] in 늘어난, (
        '창고 물건이면서 상품에도 쓴 줄이 켜도 안 보인다 — 감출 이유가 두 개라 갇혔다')
    assert int(뱃지.group(1)) == len(늘어난), (
        f'뱃지는 {뱃지.group(1)} 인데 실제로 늘어난 줄은 {len(늘어난)} 이다')


def test_창고_뱃지는_옆_체크를_켜도_안_흔들린다(client, 다섯상자, 창고인데_상품에_쓴_것):
    """🔴 창고 숫자가 옆 체크를 켜고 끌 때마다 달라지면, 창고 물건이 늘었다 줄었다
    하는 줄로 읽는다. 실제로는 창고에 아무 일도 안 일어났다.

    「상품으로 만든 것도 보기」를 켤 때만 나오는 줄을 `hid` 로 또 감추면, 그 줄이
    켤 때만 창고 몫에 얹혀 숫자가 흔들렸다(검수 지적).
    """
    def _창고뱃지(html):
        m = re.search(r'(?s)id="og-hid".*?og-bc">(\d+)<', html)
        assert m, '「창고에만 있는 물건 보기」 뱃지를 못 찾음 — 창고 표본이 없나?'
        return int(m.group(1))

    끔 = _창고뱃지(client.get('/optgen/?tab=direct').get_data(as_text=True))
    켬 = _창고뱃지(client.get('/optgen/?tab=direct&made=1').get_data(as_text=True))
    assert 끔 >= 1, '창고 표본이 없다 — 시험이 헛돈다'
    assert 끔 == 켬, (
        f'「상품으로 만든 것도 보기」를 켰다고 창고 숫자가 {끔} → {켬} 으로 바뀐다')


# ═══════════════════════════════════════════════════════════════════════════
#  ②③ 화면에 없어야 하는 글자 (사장님 확정 3·4)
# ═══════════════════════════════════════════════════════════════════════════

def _화면코드(경로: str) -> str:
    """템플릿 원문에서 **주석을 걷어낸 것** — 화면이 실제로 그리는 코드만 본다.

    🔴 주석을 안 걷으면 시험이 **자기 설명에 걸린다.** 「미구성 딱지를 그리지 않는다」고
       적어 둔 주석이 「미구성을 그린다」로 읽혀 없는 결함에 빨간불이 뜬다
       (`tests/design/test_optgen_menu_not_clipped.py` 가 이미 겪은 함정과 같다).
    """
    import io
    import os
    뿌리 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
    본문 = io.open(os.path.join(뿌리, 경로), encoding='utf-8').read()
    본문 = re.sub(r'(?s)\{#.*?#\}', ' ', 본문)            # Jinja 주석
    본문 = re.sub(r'(?s)/\*.*?\*/', ' ', 본문)             # CSS 주석
    return '\n'.join(l for l in 본문.splitlines()
                     if not l.lstrip().startswith('//'))   # JS 한 줄 주석


def test_미구성이라는_딱지를_화면이_안_그린다(client, 다섯상자):
    """🔴 미구성 SKU 는 축이 0개라 **언제나 「준비 미완료」**다 — 딱지가 없어도 구분된다.

    딱지를 또 붙이면 같은 사실을 두 가지 말로 하게 되고, 한쪽만 고쳤을 때
    같은 줄이 화면에서 서로 다른 말을 한다.

    🔴 **왜 렌더된 글자가 아니라 화면 코드를 보나.** 처음엔 렌더 결과에서
       「미구성」을 찾았는데, 다른 시험이 남긴 **매트릭스 이름**(`목록_미구성`)에 걸려
       빨간불이 떴다. 딱지가 아니라 남의 자료였다. 사장님이 지으신 이름에 그 두 글자가
       들어가는 것은 막을 일이 아니므로, 막을 것(화면이 딱지를 **그리는가**)을 본다.
    """
    # 헛돔 방지 — 미구성 표본이 실제로 목록에 올라와 있는지 먼저 본다.
    글 = _글자만(client.get('/optgen/?tab=direct').get_data(as_text=True))
    assert 다섯상자['이름']['미구성'] in 글, '미구성 표본이 화면에 없다 — 시험이 헛돈다'
    코드 = _화면코드('webapp/templates/optgen/index.html')
    assert '미구성' not in 코드, '없애기로 한 「미구성」 딱지를 화면이 그리고 있다'


def test_미구성은_축_없음으로_미완료가_된다(다섯상자):
    """딱지를 뗀 대신 **사유가 그 자리를 대신한다** — 없으면 구분할 길이 사라진다."""
    from lemouton.matrix.readiness import PHASE_DRAFT
    줄 = {b['code']: b for b in _boxes()[0]}
    x = 줄[다섯상자['미구성']]
    assert x['phase'] == PHASE_DRAFT, '축이 하나도 없는데 준비 완료라고 한다'
    assert '축 없음' in x['missing'], f'왜 미완료인지 안 알려 준다: {x["missing"]}'
    # 🔴 딱지 자체를 안 담는다 — 담아 두면 화면이 언젠가 다시 그린다.
    assert 'unbuilt' not in x, '없애기로 한 「미구성」 딱지가 값으로 남아 있다'


def test_상품_생성에_사용됨이라는_글자가_화면에_없다(client, 다섯상자):
    """사장님 확정 — 이 목록의 상태는 「준비 완료 / 준비 미완료」 둘뿐이다.

    🔴 **두 겹으로 본다.** 지금 이 표는 상태 배지를 아직 안 그리므로, 글자만 세는
       검사는 배선이 통째로 망가져도 통과한다(그게 이 저장소가 여러 번 데인 함정이다).
       그래서 ① 화면에 내려보내는 줄에 「사용됨」이 하나도 없는지를 **값으로** 보고,
       ② 그 글자가 화면에 없는지를 **글자로** 본다. ②는 표가 배지를 그리기 시작하는
       날(W9)을 대비한 자물쇠다.
    """
    from lemouton.matrix.readiness import PHASE_LABEL, PHASE_USED
    줄, _ = _boxes()
    assert 줄, '내려보낼 줄이 하나도 없다 — 시험이 헛돈다'
    assert all(b['phase'] != PHASE_USED for b in 줄), (
        '화면에 내려보내는 줄에 「사용됨」이 섞여 있다 — 배지를 그리는 순간 글자가 뜬다')
    글 = _글자만(client.get('/optgen/?tab=direct').get_data(as_text=True))
    assert 다섯상자['이름']['준비완료'] in 글, '심은 표본이 화면에 없다 — 시험이 헛돈다'
    assert PHASE_LABEL[PHASE_USED] not in 글, (
        f'화면에 없기로 한 「{PHASE_LABEL[PHASE_USED]}」 가 있다')


# ═══════════════════════════════════════════════════════════════════════════
#  ⑤ 머리줄 숫자 = 실제로 보이는 줄 수
# ═══════════════════════════════════════════════════════════════════════════

def test_머리줄_숫자가_보이는_줄_수와_같다(client, 다섯상자):
    """🔴 예전엔 상한값 50을 전체인 양 보여 줬다 — 화면이 거짓말을 하고 있었다.

    창고 물건(`data-hid="1"`)은 화면 JS 가 감추므로 기본 숫자에서 빠진다.
    세어 놓고 안 보여주면 눌러도 0줄인 거짓말이 된다.
    """
    html = client.get('/optgen/?tab=direct').get_data(as_text=True)
    머리 = re.search(r'id="og-boxn">(\d+)<', html)
    assert 머리, '머리줄 숫자를 못 찾음 — 화면 구조가 바뀌었나?'
    줄 = re.findall(r'<tr class="og-row"[^>]*data-hid="(\d)"', html)
    보임 = sum(1 for h in 줄 if h == '0')
    assert 보임 >= 3, f'보이는 줄이 너무 적다 — 시험이 헛돈다 ({보임}줄)'
    assert '1' in 줄, '숨긴 줄이 하나도 없다 — 이 시험이 헛돈다(창고 물건을 심었는데도)'
    assert int(머리.group(1)) == 보임, (
        f'머리줄은 {머리.group(1)} 인데 실제로 보이는 줄은 {보임} 이다')


# ═══════════════════════════════════════════════════════════════════════════
#  ⑥ 「모른다」와 「아니다」를 안 뭉갠다
# ═══════════════════════════════════════════════════════════════════════════

def test_URL_이_없으면_맵핑_사유가_따로_안_뜬다(다섯상자):
    """🔴 URL 이 0개면 맵핑 완료 여부는 **모른다**다.

    「아니다」로 뭉개면 사유가 「소싱처 URL 없음」+「소싱처 맵핑 미완료」 두 줄이 되어,
    실제로는 한 군데(주소 붙이기)인 할 일이 두 군데인 것처럼 보인다.
    """
    줄 = {b['code']: b for b in _boxes()[0]}
    x = 줄[다섯상자['미완료']]
    assert x['map']['complete'] is None, (
        f'URL 이 0개인데 맵핑 여부를 단정했다: {x["map"]}')
    assert '소싱처 URL 없음' in x['missing']
    assert not any('맵핑' in m for m in x['missing']), (
        f'URL 이 없어서 못 잰 것을 「맵핑 미완료」라고 단정한다: {x["missing"]}')


def test_다_갖추면_준비_완료다(다섯상자):
    """네 조건이 다 찼는데도 미완료면, 사장님은 손볼 곳이 없는 줄을 계속 들여다본다."""
    from lemouton.matrix.readiness import PHASE_READY
    줄 = {b['code']: b for b in _boxes()[0]}
    x = 줄[다섯상자['준비완료']]
    assert x['phase'] == PHASE_READY, f'다 갖췄는데 미완료라 한다: {x["missing"]}'
    assert x['missing'] == []


# ═══════════════════════════════════════════════════════════════════════════
#  9칸 재료가 실제로 실린다
# ═══════════════════════════════════════════════════════════════════════════

def test_아홉_칸_재료가_줄마다_실린다(다섯상자):
    """빈 칸을 화면이 「없음」으로 그리면, 있는 것을 없다고 말하는 화면이 된다."""
    줄 = {b['code']: b for b in _boxes()[0]}
    x = 줄[다섯상자['준비완료']]
    assert x['no'], '번호(매트릭스 display_no)가 안 실렸다'
    assert x['kind'] == 'origin', f'원본·파생 갈래가 안 실렸다: {x["kind"]}'
    assert x['axis_label'] == '색상 × 사이즈', f'축 구성이 안 실렸다: {x["axis_label"]}'
    assert x['moum_kind_label'] == '색상 모음전', f'모음전 종류가 안 실렸다: {x}'
    assert x['options'] == 2
    assert x['urls'] == 1
    assert [d['key'] for d in x['sources']] == ['musinsa']
    assert x['sources'][0]['label'], '소싱처 이름이 비었다 — 키라도 넣기로 했다'
    assert x['map']['skus'] == 2 and x['map']['skus_done'] == 2


def test_모델_모음전은_모델명을_같이_준다():
    """모델 축이 있으면 그 값들을 줄에 실어 준다 — 화면이 다시 읽지 않게."""
    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()
    tag = uuid.uuid4().hex[:8].upper()
    code = f'U-MDL{tag}'
    s = SessionLocal()
    try:
        _옵션함(s, code, f'모델함{tag}', 옵션=[('블랙', '250')],
               축=[('모델', ['메이트', '스위트']), ('색상', ['블랙'])])
        s.commit()
        줄 = {b['code']: b for b in _boxes()[0]}
        x = 줄[code]
        assert x['moum_kind_label'] == '모델 모음전', x['moum_kind_label']
        assert x['model_names'] == ['메이트', '스위트'], x['model_names']
    finally:
        _지우기(s, [code])
        s.close()


def test_지운_매트릭스는_번호를_되살리지_않는다():
    """🔴 `deleted_at` 을 안 보면 **지운 매트릭스가 화면에 번호를 다시 올린다.**

    지운 것은 없는 것이다. 되살아나면 사장님이 없는 묶음을 눌러 들어가게 된다.
    """
    import datetime as dt                    # 지운 때는 아무 값이나 되면 된다

    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.matrix.models import MatrixOption
    tag = uuid.uuid4().hex[:8].upper()
    code = f'U-DEL{tag}'
    s = SessionLocal()
    try:
        _옵션함(s, code, f'지운함{tag}', 옵션=[('블랙', '250')], 축=[('색상', ['블랙'])],
               번호=f'U-NO{tag}')
        s.commit()
        assert {b['code']: b for b in _boxes()[0]}[code]['no'] == f'U-NO{tag}'

        (s.query(MatrixOption).filter(MatrixOption.model_code == code)
         .update({'deleted_at': dt.datetime(2026, 8, 14)}, synchronize_session=False))
        s.commit()
        x = {b['code']: b for b in _boxes()[0]}[code]
        assert x['no'] is None, f'지운 매트릭스 번호가 되살아났다: {x["no"]}'
        # 🔴 옵션 수까지 같이 확인한다 — 조인을 잘못 붙이면 줄이 겹쳐 두 배가 된다.
        assert x['options'] == 1, f'옵션 수가 부풀었다: {x["options"]}'
    finally:
        _지우기(s, [code])
        s.close()


# ═══════════════════════════════════════════════════════════════════════════
#  ④ 🔴 N+1 방지 — 줄이 3개든 30개든 조회 수가 같다
# ═══════════════════════════════════════════════════════════════════════════

def _조회수를_세며(fn):
    """fn() 이 도는 동안 실제로 나간 SQL 개수 — 형제 시험들과 같은 방법이다."""
    from sqlalchemy import event

    from shared.db import engine
    통 = {'n': 0}

    def _세기(*a, **k):
        통['n'] += 1

    event.listen(engine, 'before_cursor_execute', _세기)
    try:
        fn()
    finally:
        event.remove(engine, 'before_cursor_execute', _세기)
    return 통['n']


def test_줄이_3개든_30개든_조회_수가_같다(client):
    """🔴 이 목록은 상한이 없다 — 줄마다 물으면 라이브에서만 어느 날 안 열린다.

    화면이 실제로 치르는 값을 재려고 **주소를 그대로 두드려** 센다.
    """
    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()

    tag = uuid.uuid4().hex[:6].upper()
    적은코드 = [f'U-N3{tag}{i:02d}' for i in range(3)]
    많은코드 = [f'U-N30{tag}{i:02d}' for i in range(27)]
    s = SessionLocal()
    try:
        for c in 적은코드:
            _옵션함(s, c, f'셋{c}', 옵션=[('블랙', '250')], 축=[('색상', ['블랙'])])
        s.commit()

        # 🔴 먼저 한 번 돌려 둔다 — 첫 요청은 준비 작업(표 만들기·캐시 채우기)이 섞여
        #    조회 수가 더 나온다. 그걸 재면 두 숫자가 「줄 수 때문에」 다른지 알 수 없다.
        client.get('/optgen/?tab=direct')
        적게 = _조회수를_세며(lambda: client.get('/optgen/?tab=direct'))

        for c in 많은코드:
            _옵션함(s, c, f'서른{c}', 옵션=[('블랙', '250')], 축=[('색상', ['블랙'])])
        s.commit()
        많이 = _조회수를_세며(lambda: client.get('/optgen/?tab=direct'))

        # 시험이 헛돌지 않는다는 증거 — 줄이 실제로 열 배가 됐는지 본다.
        html = client.get('/optgen/?tab=direct').get_data(as_text=True)
        보인줄 = len(re.findall(r'<tr class="og-row"', html))
        assert 보인줄 >= 30, f'줄이 안 늘었다 — 시험이 헛돈다 ({보인줄}줄)'
        assert 적게 == 많이, (
            f'조회가 줄 수를 따라 늘었다 — N+1 이 들어왔다 (3줄 {적게} · 30줄 {많이})')
    finally:
        _지우기(s, 적은코드 + 많은코드)
        s.close()
