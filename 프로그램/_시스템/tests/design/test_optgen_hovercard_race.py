# -*- coding: utf-8 -*-
"""옵션생성 목록 호버카드(`og새호버카드`) — **응답이 늦게 와도** 카드가 뜨는지
진짜 브라우저 + 진짜 지연 네트워크로 잰다.

왜 이 시험이 필요한가 (2026-08-19 실브라우저 검증 중 발견한 버그)
  미리받기(`mouseover` 시점)와 늦은 그리기(`열자()`, 열기지연 140ms 뒤)가 같은
  code 를 거의 동시에 `받아오기()`에 넘긴다. 먼저 온 호출이 아직 응답 대기
  중이면(`받는중[code]===true`) 나중 호출은 콜백을 등록도 못 하고 그냥
  버려졌다 — 응답이 도착해도 먼저 등록된 빈 콜백만 불려서, 카드가
  "불러오는 중…"에서 영원히 안 바뀌는 경쟁 조건이었다. 마우스를 뗐다가
  다시 올리면(캐시 히트) 정상으로 보여서 놓치기 쉽다.

  글자 세기·CSS 검사로는 이 타이밍 버그를 못 잡는다 — 그래서 실제 네트워크를
  일부러 늦춰(`page.route`) 140ms 열기 지연보다 뒤에 응답이 오게 만든 뒤,
  카드가 그래도 실제 값으로 바뀌는지 **동작으로** 확인한다.

브라우저가 없는 곳(CI 등)에서는 건너뛴다.
"""
import threading
import uuid

import pytest


@pytest.fixture(scope='module')
def 브라우저():
    pw = pytest.importorskip('playwright.sync_api',
                             reason='playwright 가 없으면 이 시험을 못 돌린다')
    with pw.sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception as e:                      # noqa: BLE001
            pytest.skip(f'크로미움을 못 띄웠다(브라우저 미설치): {e}')
        yield br
        br.close()


@pytest.fixture(scope='module')
def 라이브화면():
    import app as appmod
    from shared.db import SessionLocal, init_db
    init_db()

    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.sourcing.models import Model, Option

    tag = uuid.uuid4().hex[:8].upper()
    code = f'U-HCR{tag}'
    s = SessionLocal()
    try:
        s.add(Model(model_code=code, model_name_raw=f'경쟁조건표본{tag}',
                    model_name_display=f'경쟁조건표본{tag}', brand='나이키',
                    is_option_box=True))
        s.add(MatrixOption(model_code=code, display_no=code,
                           name=f'경쟁조건표본{tag}', kind=KIND_ORIGIN))
        s.add(Option(canonical_sku=f'SKU-HCR{tag}00', model_code=code,
                     color_code='블랙', color_display='블랙',
                     size_code='250', size_display='250'))
        s.commit()

        from werkzeug.serving import make_server
        앱 = appmod.create_app()
        srv = make_server('127.0.0.1', 0, 앱, threaded=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            yield {'url': f'http://127.0.0.1:{srv.server_port}/optgen/?tab=direct',
                   'code': code, 'tag': tag}
        finally:
            srv.shutdown()
    finally:
        s.rollback()
        s.query(Option).filter(Option.model_code == code).delete(synchronize_session=False)
        s.query(MatrixOption).filter(MatrixOption.model_code == code).delete(synchronize_session=False)
        s.query(Model).filter(Model.model_code == code).delete(synchronize_session=False)
        s.commit()
        s.close()


def test_응답이_열기지연보다_늦어도_카드가_불러오는_중에_멈추지_않는다(브라우저, 라이브화면):
    """🔴 [2026-08-19] 미리받기·늦은그리기 콜백 경쟁조건 회귀 방지.

    `/optgen/api/sku-identity/<code>` 를 일부러 350ms 늦춰(열기지연 140ms보다
    한참 뒤) 응답하게 만든다. 고치기 전에는 카드가 "불러오는 중…"에서
    멈춘 채였다 — 고친 뒤에는 늦게 와도 실제 값으로 바뀌어야 한다.
    """
    pg = 브라우저.new_page(viewport={'width': 1400, 'height': 900})

    def 늦게응답(route):
        import time
        time.sleep(0.35)
        route.continue_()

    pg.route('**/api/sku-identity/**', 늦게응답)
    try:
        pg.goto(라이브화면['url'], wait_until='networkidle')
        pg.wait_for_timeout(300)

        badge = pg.locator(f'.og-idbadge[data-code="{라이브화면["code"]}"]')
        assert badge.count() == 1, '심은 표본의 SKU 연결상태 배지가 화면에 없다 — 시험이 헛돈다'
        badge.hover()

        # 열기지연 140ms + 일부러 늦춘 350ms + 여유 — 이때도 "불러오는 중"이면 버그.
        pg.wait_for_timeout(700)
        card_text = pg.eval_on_selector('.og-skucard', 'e => e.innerText')
        assert '불러오는 중' not in card_text, (
            f'응답이 늦게 왔는데도 카드가 "불러오는 중"에 멈췄다(경쟁조건 재발): {card_text!r}')
        assert f'SKU-HCR{라이브화면["tag"]}00' in card_text, (
            f'응답이 도착했는데 카드에 실제 SKU 값이 안 실렸다: {card_text!r}')
    finally:
        pg.close()


def test_같은_줄을_두번_호버하면_원래도_됐다_대조용(브라우저, 라이브화면):
    """대조군 — 고치기 전에도 **같은 줄을 두 번** 호버하면(캐시 히트) 항상 됐다.

    (마우스를 뗐다가 다시 올리면 정상으로 보여서 버그를 놓치기 쉬웠던 바로 그 지점.)
    이 시험이 실패하면 위 시험의 실패가 경쟁조건이 아니라 다른 문제(예: 표본이
    화면에 없다·서버가 죽었다)란 뜻 — 새 표본으로 서버를 새로 띄워 격리한다.
    """
    pg = 브라우저.new_page(viewport={'width': 1400, 'height': 900})

    def 늦게응답(route):
        import time
        time.sleep(0.35)
        route.continue_()

    pg.route('**/api/sku-identity/**', 늦게응답)
    try:
        pg.goto(라이브화면['url'], wait_until='networkidle')
        pg.wait_for_timeout(300)

        badge = pg.locator(f'.og-idbadge[data-code="{라이브화면["code"]}"]')
        badge.hover()
        pg.wait_for_timeout(700)                       # 첫 호버 — 버그가 있으면 여기서 멈춘다
        pg.mouse.move(5, 5)                             # 마우스를 뗀다
        pg.wait_for_timeout(400)                        # 250ms 닫힘 지연이 지나가게
        badge.hover()                                   # 같은 줄 다시 호버 — 이번엔 곳간[code] 캐시 히트
        pg.wait_for_timeout(300)
        card_text = pg.eval_on_selector('.og-skucard', 'e => e.innerText')
        assert f'SKU-HCR{라이브화면["tag"]}00' in card_text, (
            f'캐시 히트(두 번째 호버)여야 하는데도 값이 안 실렸다: {card_text!r}')
    finally:
        pg.close()
