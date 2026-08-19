# -*- coding: utf-8 -*-
"""옵션함 목록 4안 — **라이브 분량**으로 진짜 브라우저에서 폭을 잰다.

왜 글자를 세는 검사로는 안 되나 (이 저장소가 두 번 데인 자리)
  · 2026-08-12 — 로컬 3줄로 「가로 스크롤 사라짐」이라 보고했는데 라이브는
    1481 > 1265 로 그대로였다. **줄이 많고 이름이 길수록 표가 벌어진다.**
  · 2026-08-13 — 서랍이 `width:max-content` 라 가장 긴 글자만큼 넓어져
    문서가 통째로 146px 굴렀다. CSS 글자만 봐서는 몇 px 인지 알 수 없다.
그래서 여기서는 스물넉 줄 + **44자 이름**을 심고 실제로 그려서 잰다.

무엇을 지키나
  ① 🔴 문서가 가로로 안 구른다(`scrollWidth == innerWidth`). 구르면 사이드바까지
     같이 밀려 화면 틀이 통째로 움직인다 — 사장님이 여러 번 지적하신 그것.
  ② 🔴 사장님 화면 폭(1870 실측)에서는 **표도 안 밀린다.** 4안이 다른 안을 제치고
     뽑힌 까닭이 「일곱 칸이 한눈에 보이고 옆으로 밀 일이 없다」라, 여기가 밀리면
     4안을 고른 이유가 사라진다.
  ③ ⓘ 를 누르면 판에 **그 줄** 값이 실제로 뜬다(글자가 아니라 동작으로 확인).
  ④ ⓘ 는 줄 클릭(=이어서 하기)을 같이 일으키지 않는다 — 판을 열려다 화면이 넘어가면
     사장님은 판을 영영 못 본다.

브라우저가 없는 곳(CI 등)에서는 **건너뛴다.** 여기서 실패시키면 배포가 「내 PC 에만
있는 것」 때문에 막힌다(그 사고도 이미 겪었다).
"""
import json
import threading
import uuid

import pytest

긴이름_최소 = 44


@pytest.fixture(scope='module')
def 브라우저():
    pw = pytest.importorskip('playwright.sync_api',
                             reason='playwright 가 없으면 폭을 잴 수 없다')
    with pw.sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception as e:                      # noqa: BLE001
            pytest.skip(f'크로미움을 못 띄웠다(브라우저 미설치): {e}')
        yield br
        br.close()


@pytest.fixture(scope='module')
def 라이브화면():
    """스물넉 줄 심고 진짜 서버를 띄운다 — 끝나면 줄도 서버도 걷는다."""
    import app as appmod
    from shared.db import SessionLocal, init_db
    init_db()

    from lemouton.matrix.models import KIND_DERIVED, KIND_ORIGIN, MatrixOption
    from lemouton.sourcing.models import (BundleOptionStep, BundleSourceUrl,
                                          Model, Option, OptionSourceUrlLink)

    tag = uuid.uuid4().hex[:6].upper()
    긴이름 = '르무통 24FW 프리미엄 스웨이드 앵클부츠 여성용 방한 기모 안감 스페셜 에디션'
    assert len(긴이름) >= 긴이름_최소, f'이름 표본이 짧다({len(긴이름)}자) — 시험이 헛돈다'

    코드들 = []
    s = SessionLocal()

    def 심기(code, name, *, 축, 주소, 다이음, 브랜드, kind):
        코드들.append(code)
        s.add(Model(model_code=code, model_name_raw=name, model_name_display=name,
                    brand=브랜드, is_option_box=True))
        s.add(MatrixOption(model_code=code, display_no=code, name=name, kind=kind))
        skus = []
        for i, (색, 사이즈) in enumerate([('블랙', '250'), ('화이트', '250'),
                                        ('블랙', '260'), ('화이트', '260')]):
            sku = f'SKU-{code}-{i}'
            skus.append(sku)
            s.add(Option(canonical_sku=sku, model_code=code,
                         color_code=색, size_code=사이즈))
        for n, (축이름, 값들) in enumerate(축, start=1):
            s.add(BundleOptionStep(model_code=code, step_no=n, axis_name=축이름,
                                   values_json=json.dumps(값들, ensure_ascii=False)))
        s.flush()
        for u in range(주소):
            b = BundleSourceUrl(model_code=code,
                                source_key=('musinsa' if u % 2 == 0 else 'ssfshop'),
                                url=f'https://example.test/{code}/{u}')
            s.add(b)
            s.flush()
            if 다이음:
                for sku in skus:
                    s.add(OptionSourceUrlLink(option_canonical_sku=sku,
                                              bundle_source_url_id=b.id))

    try:
        축둘 = [('색상', ['블랙', '화이트']), ('사이즈', ['250', '260'])]
        for i in range(1, 24):
            심기(f'U-W4{tag}{i:03d}', f'스물넉 줄 채우기 {i}번 옵션함', 축=축둘,
                주소=(1 if i % 3 else 0), 다이음=(i % 2 == 0),
                브랜드=('마르디 메크르디' if i % 3 == 0 else '나이키'),
                kind=(KIND_DERIVED if i == 2 else KIND_ORIGIN))
        # 맨 위에 오도록 마지막에 심는다(목록은 최근 만든 순).
        긴코드 = f'U-W4{tag}999'
        심기(긴코드, 긴이름, 축=축둘, 주소=2, 다이음=True, 브랜드='르무통',
            kind=KIND_ORIGIN)
        s.commit()

        from werkzeug.serving import make_server
        앱 = appmod.create_app()
        srv = make_server('127.0.0.1', 0, 앱, threaded=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            yield {'url': f'http://127.0.0.1:{srv.server_port}/optgen/?tab=direct',
                   '긴코드': 긴코드, '긴이름': 긴이름, '줄수': len(코드들)}
        finally:
            srv.shutdown()
    finally:
        s.rollback()
        url_ids = [x for (x,) in s.query(BundleSourceUrl.id)
                   .filter(BundleSourceUrl.model_code.in_(코드들)).all()]
        if url_ids:
            (s.query(OptionSourceUrlLink)
             .filter(OptionSourceUrlLink.bundle_source_url_id.in_(url_ids))
             .delete(synchronize_session=False))
        for 표, 칸 in ((BundleSourceUrl, BundleSourceUrl.model_code),
                      (BundleOptionStep, BundleOptionStep.model_code),
                      (Option, Option.model_code),
                      (MatrixOption, MatrixOption.model_code)):
            s.query(표).filter(칸.in_(코드들)).delete(synchronize_session=False)
        s.query(Model).filter(Model.model_code.in_(코드들)).delete(
            synchronize_session=False)
        s.commit()
        s.close()


@pytest.fixture(scope='module')
def 화면(브라우저, 라이브화면):
    pg = 브라우저.new_page(viewport={'width': 1870, 'height': 1000})
    pg.goto(라이브화면['url'], wait_until='networkidle')
    pg.wait_for_timeout(300)
    # 시험이 헛돌지 않는다는 증거 — 줄이 정말 스물 몇 개이고 긴 이름이 올라와 있나.
    줄수 = pg.eval_on_selector_all('.og-row', 'els => els.length')
    assert 줄수 >= 20, f'줄이 {줄수}개뿐이다 — 라이브 분량이 아니라 아무것도 못 잡는다'
    assert 라이브화면['긴이름'] in pg.content(), '44자 이름 표본이 화면에 없다'
    yield pg
    pg.close()


def _잰다(pg, 폭):
    pg.set_viewport_size({'width': 폭, 'height': 1000})
    pg.wait_for_timeout(250)
    return pg.evaluate("""() => {
      const wrap = document.querySelector('.og-tbwrap');
      return {문서: document.documentElement.scrollWidth, 창: window.innerWidth,
              표상자: wrap.clientWidth, 표속: wrap.scrollWidth};
    }""")


@pytest.mark.parametrize('폭', [1870, 1512, 1265, 1080, 768, 375])
def test_문서가_가로로_안_구른다(화면, 폭):
    """🔴 구르면 화면 틀(사이드바·상단탭)까지 같이 밀린다 — 사장님 지적 1순위."""
    잰것 = _잰다(화면, 폭)
    assert 잰것['문서'] <= 잰것['창'], (
        f'{폭}px 창에서 문서가 {잰것["문서"] - 잰것["창"]}px 굴렀다: {잰것}')


def test_사장님_화면_폭에서는_표도_안_밀린다(화면):
    """🔴 4안을 고른 까닭이 「일곱 칸이 한눈에 · 옆으로 밀 일 없음」이다.

    1870 은 사장님 화면 실측 폭(2026-08-07 기록). 여기서 밀리면 고른 이유가 사라진다.
    """
    잰것 = _잰다(화면, 1870)
    assert 잰것['표속'] <= 잰것['표상자'], (
        f'표가 자기 상자보다 {잰것["표속"] - 잰것["표상자"]}px 넓다 — 옆으로 밀어야 한다: {잰것}')


def test_좁은_창에서는_판이_표_밑으로_내려간다(화면):
    """서랍(최대 520)+판(380)이 이미 900을 넘는다 — 셋이 나란히 서면 표 자리가 없다."""
    화면.set_viewport_size({'width': 1000, 'height': 1000})
    화면.wait_for_timeout(250)
    잰것 = 화면.evaluate("""() => {
      const w = document.querySelector('.og-tbwrap').getBoundingClientRect();
      const s = document.querySelector('#og-side').getBoundingClientRect();
      return {표top: w.top, 판top: s.top, 판폭: Math.round(s.width)};
    }""")
    assert 잰것['판top'] > 잰것['표top'] + 40, f'좁은 창인데 판이 아직 옆에 있다: {잰것}'


def test_정보단추를_누르면_그_줄_값이_판에_뜬다(화면, 라이브화면):
    """🔴 글자만 세면 「값은 실렸는데 배선이 죽은」 조용한 실패를 못 잡는다."""
    화면.set_viewport_size({'width': 1870, 'height': 1000})
    화면.wait_for_timeout(250)
    처음 = 화면.eval_on_selector('#og-side-b', 'e => e.innerText.trim()')
    assert 'ⓘ' in 처음, f'판이 안내 글로 시작하지 않는다: {처음!r}'

    화면.eval_on_selector(f'.og-i[data-code="{라이브화면["긴코드"]}"]', 'e => e.click()')
    화면.wait_for_timeout(150)
    뒤 = 화면.eval_on_selector('#og-side-b', 'e => e.innerText.trim()')
    assert 라이브화면['긴이름'] in 뒤, f'누른 줄 값이 판에 안 떴다: {뒤!r}'
    assert '색상 × 사이즈' in 뒤 and '주소 모두 2개' in 뒤, f'판에 값이 덜 찼다: {뒤!r}'
    assert 화면.eval_on_selector_all('.og-row.on', 'els => els.length') == 1, (
        '어느 줄을 보고 있는지 표에 표시가 없다')
    # 🔴 다시 누르면 닫힌다 — 판을 지우려고 엉뚱한 줄을 누르게 하지 않는다.
    화면.eval_on_selector(f'.og-i[data-code="{라이브화면["긴코드"]}"]', 'e => e.click()')
    화면.wait_for_timeout(150)
    assert 'ⓘ' in 화면.eval_on_selector('#og-side-b', 'e => e.innerText.trim()')


def test_정보단추가_다음_화면으로_넘기지_않는다(화면, 라이브화면):
    """줄 클릭은 「이어서 하기」다. ⓘ 가 그걸 같이 일으키면 판은 영영 못 본다."""
    화면.goto(라이브화면['url'], wait_until='networkidle')
    화면.wait_for_timeout(200)
    주소 = 화면.url
    화면.eval_on_selector(f'.og-i[data-code="{라이브화면["긴코드"]}"]', 'e => e.click()')
    화면.wait_for_timeout(250)
    assert 화면.url == 주소, f'ⓘ 를 눌렀는데 화면이 넘어갔다: {화면.url}'


def test_서랍으로_줄을_감추면_판도_비운다(화면, 라이브화면):
    """목록에 없는 줄의 값이 오른쪽에 남으면 화면이 없는 것을 보여 준다."""
    화면.goto(라이브화면['url'], wait_until='networkidle')
    화면.wait_for_timeout(200)
    화면.eval_on_selector(f'.og-i[data-code="{라이브화면["긴코드"]}"]', 'e => e.click()')
    화면.wait_for_timeout(150)
    assert 라이브화면['긴이름'] in 화면.eval_on_selector('#og-side-b', 'e => e.innerText')
    화면.fill('#og-find', '이런이름은없다zzz')
    화면.wait_for_timeout(250)
    남은글 = 화면.eval_on_selector('#og-side-b', 'e => e.innerText.trim()')
    assert 라이브화면['긴이름'] not in 남은글, f'감춘 줄 값이 판에 남았다: {남은글!r}'
